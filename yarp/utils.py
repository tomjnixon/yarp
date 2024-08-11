"""semi-internal utilities, mostly to make it easier to handle Value or Event
with the same code
"""

from .value import Value, Event

NO_CB = object()


def on_value(source, cb=NO_CB, current=True):
    """call cb for each value in source. if cb is not provided, return a
    decorator that accepts the callback

    for Value, call once with the current value (if current), then on change

    for Event, call on each event
    """
    if cb is NO_CB:

        def decorator(cb):
            on_value(source, cb=cb, current=current)
            return cb

        return decorator

    match source:
        case Value():
            if current:
                cb(source.value)
            source.on_value_changed(cb)
        case Event():
            source.on_event(cb)
        case _:  # pragma: no cover
            assert False


def emit_fn(reactive):
    """get a function to emit a change or event in reactive"""
    match reactive:
        case Value():

            def emit(new_value):
                reactive.value = new_value

            return emit
        case Event():
            return reactive.emit
        case _:  # pragma: no cover
            assert False


COPY = object()


def make_same_type(reactive, inputs=(), initial_value=COPY):
    """make a new reactive with the same type

    if reactive is a Value and initial_value is COPY (the default), the input
    value will be copied, otherwise it will be initial_value
    """
    match reactive:
        case Value():
            return Value(
                initial_value=(
                    reactive.value if initial_value is COPY else initial_value
                ),
                inputs=inputs,
            )
        case Event():
            return Event(inputs=inputs)
        case _:  # pragma: no cover
            assert False
