"""
Temporal filters for :py:class:`Value` values.
"""

import asyncio

from yarp import NoValue, Event, Value, ensure_value, fn

__names__ = [
    "delay",
    "time_window",
    "rate_limit",
]


def emit_at(time) -> Event:
    """emit an event at the times given in time

    time can be None (no events), a time in seconds as given by loop.time()
    (emit None at the given time), or a tuple containing the time and the value
    to emit

    whenever time changes the timer is reloaded, so if the timer for the
    previous value has not fired, it never will. this also means that if the
    time changes to be before the current time, there will be one event per
    change

    this is mostly useful in cases where you can calculate the next time that
    something should happen from on some value
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

    match source:
        case Value():
            output = Value(source.value)

            def emit(value):
                output.value = value

            on_input = source.on_value_changed
        case Event():
            output = Event()
            emit = output.emit
            on_input = source.on_event
        case _:
            assert False

    @on_input
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

    output._keep_alive = timer  # XXX
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
    values_and_times._keep_alive = pop_event  # XXX

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

        case _:
            assert False

    return to_values(values_and_times)


def rate_limit(source_value, min_interval=0.1, loop=None):
    """Prevent changes occurring above a particular rate, dropping or
    postponing changes if necessary.

    The ``min_interval`` argument may be a constant or a :py:class:`Value`. If
    this value is decreased, currently delayed values will be output early (or
    immediately if the value would have been output previously). If increased,
    the current delay will be increased.

    The ``loop`` argument should be an :py:class:`asyncio.BaseEventLoop` in
    which the delays will be scheduled. If ``None``, the default loop is used.
    """

    source_value = ensure_value(source_value)
    output_value = Value(source_value.value)

    min_interval = ensure_value(min_interval)
    loop = loop or asyncio.get_event_loop()

    # The last value to be received from the source
    last_value = None

    # Was last_value blocked from being sent due to the rate limit?
    last_value_blocked = False

    # The time (according to asyncio) the last blockage started. The
    # blockage will be cleared min_interval.delay seconds after this
    # time.
    last_block_start = None

    # The asyncio timer handle for the current blockage timer
    timer_handle = None

    # Is the rate limit currently being applied? (Initially yes for
    # persistant values, otherwise no)
    blocked = source_value.value is not NoValue

    def clear_blockage():
        """Internal. Timeout expired callback."""
        nonlocal blocked, last_value, last_value_blocked, last_block_start, timer_handle
        if last_value_blocked:
            # Pass the delayed value through
            output_value._value = source_value.value
            output_value.set_instantaneous_value(last_value)
            last_value = None
            last_value_blocked = False

            # Start the blockage again
            block()
        else:
            # No values queued up, just unblock
            blocked = False
            last_block_start = None
            timer_handle = None

    def block():
        """Setup a timer to unblock the rate_limit and output the last
        value."""
        nonlocal blocked, last_block_start, timer_handle
        blocked = True
        last_block_start = loop.time()
        timer_handle = loop.call_at(
            last_block_start + min_interval.value, clear_blockage
        )

    @source_value.on_value_changed
    def on_source_value_changed(new_value):
        nonlocal last_value, last_value_blocked
        if not blocked:
            # Pass the value change through
            output_value._value = source_value.value
            output_value.set_instantaneous_value(new_value)

            # Start a timeout
            block()
        else:
            # Keep the value back until we're unblocked
            last_value = new_value
            last_value_blocked = True

    @min_interval.on_value_changed
    def on_min_interval_changed(instantaneous_min_interval):
        nonlocal timer_handle
        now = loop.time()
        if not blocked:
            # No blockage in progress, nothing to do
            pass
        elif now - last_block_start >= min_interval.value:
            # New timeout has already expired, unblock immediately
            timer_handle.cancel()
            clear_blockage()
        else:
            # Reset timer for new time
            timer_handle.cancel()
            timer_handle = loop.call_at(
                last_block_start + min_interval.value, clear_blockage
            )

    if blocked:
        block()

    return output_value
