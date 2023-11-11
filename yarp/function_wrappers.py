"""
Wrappers for making reactive Python functions which accept and produce
:py:class:`Value` and :py:class:`Event` objects.
"""

import functools

from yarp import NoValue, NoChange, Value, Event, Reactive

__names__ = [
    "fn",
]


def fn(f):
    """Wrap a function operating on plain values so that it can accept
    Value/Event arguments and produces a Value/Event result.

    If the function is called with only Value (or non-reactive) arguments, the
    result will be a Value, the result of calling the function, which updates
    whenever any of the inputs change. See the README example.

    If the function is called with any Event values, then the result will be an
    Event, which emits once each time any input Event emits, with the result of
    calling the wrapped function with the value emitted by the event and the
    latest version of any Value inputs. Value changes do not cause the
    resulting Event to emit. For example:

    >>> @fn
    ... def passthrough(*args):
    ...     return args

    >>> a = Value(1)
    >>> b = Event()
    >>> res = passthrough(a, b)
    >>> res.on_event(print)
    <...>

    >>> b.emit(2)
    (1, 2)
    >>> a.value = 3 # nothing
    >>> b.emit(4)
    (3, 4)

    If multiple Events are passed to the wrapped function, the "one output per
    input event" rule still holds, and the non-firing event inputs are replaced
    with NoValue. For example:

    >>> @fn
    ... def passthrough(*args):
    ...     return args

    >>> a = Event()
    >>> b = Event()
    >>> res = passthrough(a, b)
    >>> res.on_event(print)
    <...>

    >>> a.emit(1)
    (1, NoValue)
    >>> b.emit(2)
    (NoValue, 2)

    This happens even if two events occur at the same time (within one transaction):

    >>> res = passthrough(a, a)
    >>> res.on_event(print)
    <...>

    >>> a.emit(1)
    (1, NoValue)
    (NoValue, 1)

    If the function returns NoChange, then the resulting Event will not emit,
    or the Value will not change.

    Notes
    -----
    **event behaviour**: It would be possible instead to only call the function
    once for events which occur in the same transaction, and only produce one
    result.

    This isn't done because it's possible (though maybe it shouldn't be) for
    an Event to emit more than once in a transaction. This isn't a niche
    issue -- think about something that turns high-level commands into
    multiple lower-level ones. What should be done then?

    We could turn the values into a list, but that's either inconsistent (if
    singular events are not wrapped) or messy (if they are always wrapped).
    It seems bad to force users to think about this annoyance in the
    transaction mechanism.

    We could call it once per event, but what if multiple input events emit
    more than once? I don't think there's a good answer to this.

    Or, we could ignore all but the last event, but that's definitely bad.

    This behaviour is chosen, even if it isn't perfect for all uses, because
    it's consistent and doesn't force the user to understand how it interacts
    with the transaction processing.

    The major downside is the inability to use some overloads on events (e.g.
    ``e ** 2 + e``) -- just use a fn for that kind of thing.

    If a different behaviour is needed, either write it manually, write
    something which merges events in the way you need (then process the result
    with fn), or add options to this to pick a different behaviour.
    """

    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        has_events = False

        event_buffer = []
        inputs = []

        def handle_arg(values, key, reactive):
            nonlocal has_events

            if isinstance(reactive, Reactive):
                inputs.append(reactive)

                if isinstance(reactive, Value):
                    values[key] = reactive.value

                    @reactive.on_value_changed
                    def _(new_value):
                        values[key] = new_value

                elif isinstance(reactive, Event):
                    values[key] = NoValue
                    has_events = True

                    @reactive.on_event
                    def _(value):
                        event_buffer.append((values, key, value))

                else:
                    assert False, f"unknown reactive: {reactive!r}"
            else:
                values[key] = reactive

        arg_values = [None] * len(args)
        kwarg_values = {}

        for i, arg in enumerate(args):
            handle_arg(arg_values, i, arg)
        for key, arg in kwargs.items():
            handle_arg(kwarg_values, key, arg)

        if has_events:

            def on_inputs_done(emit):
                for values, key, value in event_buffer:
                    values[key] = value

                    ret = f(*arg_values, **kwarg_values)
                    if ret is not NoChange:
                        emit(ret)

                    values[key] = NoValue

                event_buffer.clear()

            return Event(inputs=inputs, on_inputs_done=on_inputs_done)
        else:

            def get_value():
                return f(*arg_values, **kwarg_values)

            return Value(inputs=inputs, get_value=get_value)

    return wrapped
