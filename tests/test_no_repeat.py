from mock import Mock

from yarp import NoValue, Value, Event, no_repeat


def test_no_repeat_value():
    v = Value(1)

    # Initial value should come through
    nrv = no_repeat(v)
    assert nrv.value == 1

    m = Mock()
    nrv.on_value_changed(m)

    # Same value doesn't pass through
    v.value = 1
    assert not m.called

    # New values do
    v.value = 2
    assert nrv.value == 2
    m.assert_called_once_with(2)


def test_no_repeat_event():
    v = Event()

    nrv = no_repeat(v)

    m = Mock()
    nrv.on_event(m)

    # New value should pass through
    v.emit(1)
    m.assert_called_once_with(1)

    # Repeat should not
    m.reset_mock()
    v.emit(1)
    assert not m.called

    # New value should pass through
    v.emit(2)
    m.assert_called_once_with(2)
