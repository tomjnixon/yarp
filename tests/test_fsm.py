from yarp.fsm import FSM
from yarp.value import Value, Event
import pytest
import asyncio
import gc


def example_fsm(button_pressed: Event, force_off: Value, timeout_len=1.0):
    """Example use of FSM with a boolean state.

    The state toggles when button_pressed emits, but can only be True for
    timeout_len before being reset back to False.

    If force_off is true, the state will be set to False.
    """

    def next_state(state, timeout, button_pressed, force_off):
        # pattern match is more selective than necessary for testing purposes
        match state, timeout, button_pressed, force_off:
            case FSM.START, None, [], _:
                return False, None
            # button pressed while off -> on with timeout
            case False, None, [None], False:
                return True, timeout_len
            # button pressed while on -> off
            case True, _, [None], False:
                return False, None
            # timeout while on -> off
            case True, 0.0, [], False:
                return False, None
            # force off -> off
            case _, _, _, True:
                return False, None
            # leave force off -> still off
            case False, None, [], False:
                return False, None

    return FSM(next_state, [button_pressed, force_off]).state


@pytest.mark.asyncio
async def test_fsm():
    time_scale = 0.15

    button_pressed = Event()
    force_off = Value(False)
    state = example_fsm(button_pressed, force_off, time_scale)
    gc.collect()

    assert state.value is False

    # button -> on -> off
    button_pressed.emit(None)
    assert state.value is True
    await asyncio.sleep(time_scale * 2)
    assert state.value is False

    # button -> on -> button -> off
    button_pressed.emit(None)
    assert state.value is True
    button_pressed.emit(None)
    assert state.value is False

    # force off while off -> no change
    force_off.value = True
    assert state.value is False

    # button while forced off -> no change
    button_pressed.emit(None)
    assert state.value is False

    # leave force off -> no change
    force_off.value = False

    # button -> on -> force off -> off
    button_pressed.emit(None)
    assert state.value is True
    force_off.value = True
    assert state.value is False
    await asyncio.sleep(time_scale * 2)
    assert state.value is False
