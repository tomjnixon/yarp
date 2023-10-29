"""
Wrappers for making reactive Python functions which accept and produce
:py:class:`Value` objects.
"""

import functools

from yarp import NoValue, Value, Event, Reactive

__names__ = [
    "fn",
]


def fn(f):
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

                    emit(f(*arg_values, **kwarg_values))

                    values[key] = NoValue

                event_buffer.clear()

            return Event(inputs=inputs, on_inputs_done=on_inputs_done)
        else:

            def get_value():
                return f(*arg_values, **kwarg_values)

            return Value(inputs=inputs, get_value=get_value)

    return wrapped
