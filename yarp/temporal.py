"""
Temporal filters for :py:class:`Value` values.
"""

import asyncio

from yarp import NoValue, Event, Value, ensure_value, fn
from .utils import make_same_type, emit_fn, on_value

__names__ = [
    "emit_at",
    "delay",
    "time_window",
    "rate_limit",
]


def emit_at(time: Value | float | int | None) -> Event:
    """emit an event at the times given in time

    Time can be None (no events), a time in seconds as given by loop.time()
    (emit None at the given time), or a tuple containing the time and the value
    to emit.

    Whenever time changes the timer is reloaded, so if the timer for the
    previous value has not fired, it never will. This also means that if the
    time changes to be before the current time, there will be one event per
    change.

    This is mostly useful in cases where you can calculate the next time that
    something should happen from some Value.

    The resulting Event does not depend on ``time``, because it is always
    emitted in an asyncio callback (never synchronously on ``time`` changes,
    even if ``time`` is in the past).  This makes it safe to modify ``time``
    (or one of its inputs) in a callback attached to the result.
    """
    time = ensure_value(time)

    event = Event()

    timer = None
    timer_time = None
    timer_emit = None

    loop = asyncio.get_event_loop()

    def on_timer():
        nonlocal timer, timer_time, timer_emit
        # clear first in case emitting the event causes setup_timer to be called
        to_emit = timer_emit
        timer, timer_time, timer_emit = None, None, None

        event.emit(to_emit)

    def setup_timer(value):
        nonlocal timer, timer_time, timer_emit
        if not isinstance(value, tuple):
            value = (value, None)

        new_time, new_emit = value
        assert new_time is None or isinstance(new_time, (float, int))

        if (new_time, new_emit) != (timer_time, timer_emit):
            if timer is not None:
                timer.cancel()
                timer = None

            timer_time, timer_emit = new_time, new_emit

            if new_time is not None:
                timer = loop.call_at(new_time, on_timer)

    setup_timer(time.value)
    time.on_value_changed(setup_timer)
    event._keep_alive = time  # XXX

    return event


def delay(source, delay_seconds):
    r"""
    Produce a time-delayed version of a :py:class:`Value` or :py:class:`Event`.

    For :py:class:`Value`\ s, the initial value is set immediately.

    The ``delay_seconds`` argument may be a constant or a Value giving the
    number of seconds to delay value changes. If it is increased, previously
    delayed values will be delayed further. If it is decreased, values which
    should already have been output will be output rapidly one after another.
    """
    delay_seconds = ensure_value(delay_seconds)
    loop = asyncio.get_event_loop()

    values_and_times = Value([], inputs=(source, delay_seconds))

    output = make_same_type(source, inputs=(delay_seconds,))
    emit = emit_fn(output)

    @on_value(source, current=False)
    def _(value):
        values_and_times.value = values_and_times.value + [(value, loop.time())]

    @fn
    def next_time(values_and_times, delay_seconds):
        return values_and_times[0][1] + delay_seconds if values_and_times else None

    timer = emit_at(next_time(values_and_times, delay_seconds))

    @timer.on_event
    def pop_one(_ev):
        emit(values_and_times.value[0][0])
        values_and_times.value = values_and_times.value[1:]

    values_and_times.add_input(timer)
    output.add_input(timer)

    @delay_seconds.on_value_changed
    def on_delay_changed(new_delay):
        # drop and emit values that should have expired already. this is only
        # needed to make the values come out in the same asyncio time step
        vt = values_and_times.value.copy()
        changed = False
        expiry_time = loop.time() - new_delay

        while vt and vt[0][1] <= expiry_time:
            emit(vt.pop(0)[0])
            changed = True

        if changed:
            values_and_times.value = vt

    return output


def time_window(source, duration_seconds):
    """Produce a moving window over the historical values of a Value or the
    events of an Event within a given time period.

    ``duration_seconds`` may be a constant or a Value giving the window
    duration as a number of seconds. The duration should be a number of seconds
    greater than zero and never be ``NoValue``. If the value is reduced,
    previously inserted values will be expired earlier, possibly immediately if
    they should already have expired. If the value is increased, previously
    inserted values will have an increased timeout.
    """
    duration_seconds = ensure_value(duration_seconds)

    loop = asyncio.get_event_loop()

    # value containing a list of values and the time at which they were last
    # seen. the time may be None for the current value of a Value
    values_and_times = Value([], inputs=(source, duration_seconds))

    @fn
    def to_values(values_and_times):
        return [value for value, time in values_and_times]

    @fn
    def next_time_to_pop(values_and_times, duration_seconds):
        if values_and_times and values_and_times[0][1] is not None:
            return values_and_times[0][1] + duration_seconds
        else:
            return None

    pop_event = emit_at(next_time_to_pop(values_and_times, duration_seconds))
    values_and_times.add_input(pop_event)

    @pop_event.on_event
    def pop_one_value(_value):
        values_and_times.value = values_and_times.value[1:]

    @duration_seconds.on_value_changed
    def drop_expired_values(new_duration):
        expiry_time = loop.time() - new_duration

        vt = values_and_times.value.copy()
        while vt and vt[0][1] is not None and vt[0][1] <= expiry_time:
            vt.pop(0)

        if len(vt) < len(values_and_times.value):
            values_and_times.value = vt

    match source:
        case Value():
            values_and_times.value = [(source.value, None)]

            @source.on_value_changed
            def _(new_value):
                # update the expiry time for the last value first
                old_value, _old_time = values_and_times.value[-1]
                values_and_times.value = values_and_times.value[:-1] + [
                    (old_value, loop.time()),
                    (new_value, None),
                ]

        case Event():

            @source.on_event
            def _(event):
                values_and_times.value = values_and_times.value + [(event, loop.time())]

        case _:  # pragma: no cover
            assert False

    return to_values(values_and_times)


def rate_limit(source, min_interval=0.1):
    """Prevent changes occurring above a particular rate, dropping or
    postponing changes if necessary.

    ``source`` may be a Value or Event.

    The ``min_interval`` argument may be a constant or a :py:class:`Value`. If
    this value is decreased, currently delayed values will be output early (or
    immediately if the value would have been output previously). If increased,
    the current delay will be increased.
    """
    loop = asyncio.get_event_loop()

    # the start time of the current block if one is active
    block_time = Value(None, inputs=(source,))
    has_value = False  # was there a value in the current block?
    next_value = None  # if so, what is it?

    output = make_same_type(source, inputs=(source,), initial_value=NoValue)
    emit = emit_fn(output)

    @on_value(source)
    def _(value):
        nonlocal has_value, next_value
        if block_time.value is not None:
            # blocking, save until end
            next_value = value
            has_value = True
        else:
            # not blocking, emit and start blocking
            emit(value)
            block_time.value = loop.time()

    @fn
    def block_end_time(block_time, min_interval):
        return None if block_time is None else block_time + min_interval

    block_end_event = emit_at(block_end_time(block_time, min_interval))

    @block_end_event.on_event
    def end_block(_value):
        nonlocal has_value, next_value
        if has_value:
            # had a value in this block, emit it and start a new block
            emit(next_value)
            has_value = False
            next_value = None

            block_time.value = loop.time()
        else:
            # no value in this block, stop blocking
            block_time.value = None

    output.add_input(block_end_event)
    block_time.add_input(block_end_event)

    return output
