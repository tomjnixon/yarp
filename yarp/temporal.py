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


def delay(source_value, delay_seconds, loop=None):
    r"""
    Produce a time-delayed version of a :py:class:`Value`.

    Supports both instantaneous and continous :py:class:`Values`. For
    continuous :py:class:`Value`\ s, the initial value is set immediately.

    The ``delay_seconds`` argument may be a constant or a Value giving the
    number of seconds to delay value changes. If it is increased, previously
    delayed values will be delayed further. If it is decreased, values which
    should already have been output will be output rapidly one after another.

    The ``loop`` argument should be an :py:class:`asyncio.BaseEventLoop` in
    which the delays will be scheduled. If ``None``, the default loop is used.
    """

    source_value = ensure_value(source_value)
    delay_seconds = ensure_value(delay_seconds)
    output_value = Value(source_value.value)

    # An array of (insertion_time, value, instantaneous_value, handle)
    # tuples for values due to be sent.
    timers = []

    loop = loop or asyncio.get_event_loop()

    def pop_value():
        """Internal. Outputs a previously delayed value."""
        insertion_time, value, instantaneous_value, handle = timers.pop(0)
        output_value._value = value
        output_value.set_instantaneous_value(instantaneous_value)

    @source_value.on_value_changed
    def on_source_value_changed(instantaneous_value):
        """Internal. Schedule an incoming value to be output later."""
        insertion_time = loop.time()
        handle = loop.call_at(insertion_time + delay_seconds.value, pop_value)
        timers.append((insertion_time, source_value.value, instantaneous_value, handle))

    @delay_seconds.on_value_changed
    def on_delay_seconds_changed(new_delay_seconds):
        """Internal. Handle the delay changing."""
        nonlocal timers

        now = loop.time()
        max_age = delay_seconds.value

        # Expire any delayed values which should have been removed by now
        while timers:
            insertion_time, value, instantaneous_value, handle = timers[0]
            age = now - insertion_time
            if age >= max_age:
                handle.cancel()
                pop_value()
            else:
                # If this timer is young enough, all others inserted after it
                # must also be young enough.
                break

        # Update the timeouts of the remaining timers
        def update_timer(it_v_iv_h):
            insertion_time, value, instantaneous_value, handle = it_v_iv_h
            handle.cancel()
            return (
                insertion_time,
                value,
                instantaneous_value,
                loop.call_at(insertion_time + delay_seconds.value, pop_value),
            )

        timers = list(map(update_timer, timers))

    return output_value


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

    # tuples of (value, time)
    # for values, time is when it changed to another value, or None for the current value
    # for events, time is when it was emitted
    seen_values = []

    # the strategy is to use one timer for the next value to be dropped
    timer = None
    # and store the time for which that timer will drop values, and the time
    # when that timer will fire, so we know if it needs updating or not
    timer_info = (None, None)

    loop = asyncio.get_event_loop()

    output = Value(inputs=(source, duration_seconds))

    def expire(exp_time):
        """expire values at or before exp_time"""
        updated = False
        while (
            seen_values
            and seen_values[0][1] is not None
            and seen_values[0][1] <= exp_time
        ):
            seen_values.pop(0)
            updated = True
        if updated:
            output.value = [value for value, t in seen_values]

    def cancel_timer():
        """cancel the timer and clear the info"""
        nonlocal timer, timer_info
        if timer is not None:
            timer.cancel()
            timer = None
            timer_info = (None, None)

    def update_timer():
        """set, clear or update the timer to take the next action at the right time"""
        nonlocal timer, timer_info

        next_exp_time = seen_values[0][1] if seen_values else None
        next_exp_time_at = (
            None if next_exp_time is None else next_exp_time + duration_seconds.value
        )
        next_timer_info = next_exp_time, next_exp_time_at

        if timer_info != next_timer_info:
            cancel_timer()

            if next_exp_time_at is None:
                return

            def on_timer():
                nonlocal timer, timer_info
                timer = None
                timer_info = (None, None)
                expire(next_exp_time)
                update_timer()

            timer = loop.call_at(next_exp_time_at, on_timer)
            timer_info = next_exp_time, next_exp_time_at

    match source:
        case Value():
            seen_values.append((source.value, None))

            @source.on_value_changed
            def _(new_value):
                # update the expiry time for the last value first
                old_value, _none = seen_values[-1]
                seen_values[-1] = old_value, loop.time()
                seen_values.append((new_value, None))

                output.value = [value for value, t in seen_values]
                update_timer()

        case Event():

            @source.on_event
            def _(event):
                seen_values.append((event, loop.time()))

                output.value = [value for value, t in seen_values]
                update_timer()

        case _:
            assert False

    output.value = [value for value, t in seen_values]

    @duration_seconds.on_value_changed
    def _(new_duration):
        now = loop.time()
        expire(now - new_duration)
        update_timer()

    return output


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
