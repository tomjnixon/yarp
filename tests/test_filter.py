import pytest

from mock import Mock

from yarp import NoValue, Event, Value, filter, replace_novalue
from yarp.general import _check_value


@pytest.mark.parametrize(
    "rule,pass_values,block_values",
    [
        (NoValue, [0, 123, True, False, None], [NoValue]),
        (None, [123, True], [NoValue, False, None, 0]),
        (lambda x: x != 123, [0, True, False, None, NoValue], [123]),
    ],
)
def test_check_value(rule, pass_values, block_values):
    # Test the internal rule-checking implementation
    for value in pass_values:
        assert _check_value(value, rule) is True
    for value in block_values:
        assert _check_value(value, rule) is False


def test_check_initial_value():
    # Initial value should also be filtered
    rule = lambda x: x == 123

    v = Value(123)
    fl = filter(v, rule)
    assert fl.value == 123

    v = Value(321)
    fl = filter(v, rule)
    assert fl.value is NoValue


def test_change_persistent():
    rule = lambda x: x < 10

    m = Mock()
    v = Value(1)
    fl = filter(v, rule)
    fl.on_value_changed(m)
    assert fl.value == 1

    v.value = 2
    assert fl.value == 2
    m.assert_called_once_with(2)

    # Above ten, shouldn't get through
    v.value = 100
    assert fl.value == 2
    m.assert_called_once_with(2)


def test_change_persistent_initial_value_filtered():
    rule = lambda x: x < 10

    v = Value(123)
    fl = filter(v, rule)

    # Initial value should be rejected by the filter and thus not passed
    # through
    assert fl.value is NoValue


def test_change_instantaneous():
    rule = lambda x: x < 10

    m = Mock()
    e = Event()
    fl = filter(e, rule)
    fl.on_event(m)

    e.emit(2)
    m.assert_called_once_with(2)

    # Above ten, shouldn't get through
    e.emit(100)
    m.assert_called_once_with(2)


def test_replace_novalue():
    a = Value()
    replacement = Value(123)
    ar = replace_novalue(a, replacement)

    assert ar.value == 123

    a.value = "hi"
    assert ar.value == "hi"

    a.value = NoValue
    assert ar.value == 123

    replacement.value = 321
    assert ar.value == 321

    a.value = "bye"
    assert ar.value == "bye"
