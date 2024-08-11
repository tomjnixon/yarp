from .temporal import emit_at
from .value import Value, Event, NoChange
import asyncio
from functools import partial
import sentinel


class FSM:
    """utility for building finite state machines which react to Values, Events
    and timeouts

    Parameters
    ----------
    get_next_state: callable
        Function called to get the next (and first) state and timeout.

        This will be called with:
        - the previous state, or FSM.START on initialisation
        - the timeout; this can be:
            - None, if no timeout has been set
            - 0.0, if get_next_state is being called because the timeout expired
            - some other float, the number of seconds until the timeout will fire
        - one value for each Reactive value specified in inputs
            - for a `Value`, this is the current value
            - for an `Event`, this is a list, either empty if the event has not
              fired, or containing the emitted value if it has

              (if en event emits more than once in a transaction then this can
              contain more than one value, but you can ignore that unless
              you're doing something odd)

        It should return:
        - the next state (of any type)
        - the next timeout, in seconds, or None for no timeout

        This will be called whenever an input value changes or event emits, or
        when the timeout expires. To stay in the same state (and keep the same
        timeout), just return the current state and timeout.
    inputs: list of Reactive
        reactive inputs whose values or events will be passed to get_next_state

    Attributes
    ----------
    state: Value
        The current state, updates whenever get_next_state returns a different
        state than it was called with.
    timeout_length: Value
        The length of the current timeout in seconds, or None for no timeout.
    timeout_time: Value
        The time of the timeout in seconds, relative to loop.time(), or None
        for no timeout.
    """

    START = sentinel.create("START")

    def __init__(self, get_next_state, inputs):
        loop = asyncio.get_running_loop()
        # the time to the next timeout (when it is changed), or None for no timeout
        self.timeout_length = Value(None)

        def get_timeout_time():
            if self.timeout_length.value is not None:
                return loop.time() + self.timeout_length.value

        # the loop time of the next timeout (or None)
        self.timeout_time = Value(
            get_value=get_timeout_time, inputs=[self.timeout_length]
        )

        # fires on timeout
        self.timeout_event = emit_at(self.timeout_time)

        # values to pass to get_next_state, updated on change
        inputs_list = []

        def update_value(i, value):
            inputs_list[i] = value

        def update_event(i, value):
            inputs_list[i].append(value)

        for i, input in enumerate(inputs):
            match input:
                case Value():
                    inputs_list.append(input.value)
                    input.on_value_changed(partial(update_value, i))
                case Event():
                    inputs_list.append([])
                    input.on_event(partial(update_event, i))
                case _:
                    assert False

        # true if we're currently handling a timeout; set from the event, and
        # cleared agter calculating the new state
        handling_timeout = False

        @self.timeout_event.on_event
        def on_timeout(_):
            nonlocal handling_timeout
            handling_timeout = True

        # the current state
        state_value = self.START

        def get_state():
            nonlocal handling_timeout, inputs_list, state_value

            if handling_timeout:
                current_timeout = 0.0
            else:
                if self.timeout_time.value is None:
                    current_timeout = None
                else:
                    current_timeout = self.timeout_time.value - loop.time()

            try:
                next_state, next_timeout = get_next_state(
                    state_value, current_timeout, *inputs_list
                )
            finally:
                handling_timeout = False
                for i, input in enumerate(inputs):
                    if isinstance(input, Event):
                        inputs_list[i].clear()

            if next_timeout != current_timeout:
                self.timeout_length.value = next_timeout

            if next_state != state_value:
                state_value = next_state
                return state_value
            else:
                return NoChange

        self.state = Value(get_value=get_state, inputs=[*inputs, self.timeout_event])

        self.timeout_length.add_input(self.state)
