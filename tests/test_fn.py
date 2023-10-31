from mock import Mock

from yarp import NoChange, NoValue, Value, Event, fn, event_to_value


def test_no_args():
    @fn
    def example():
        return 123

    # Function call should return a Value with the function called just the
    # once. Since it takes no arguments, it won't ever be called again.
    result = example()
    assert result.value == 123


def test_positional_args():
    m = Mock()

    @fn
    def example(a, b):
        return a - b

    a_value = Value(10)
    b_value = Value(5)

    # Initial value should pass through
    result = example(a_value, b_value)
    result.on_value_changed(m)
    assert result.value == 5

    # Changes should propagate, callbacks should fire
    m.reset_mock()
    a_value.value = 20
    m.assert_called_once_with(15)
    assert result.value == 15

    m.reset_mock()
    b_value.value = -5
    m.assert_called_once_with(25)
    assert result.value == 25


def test_positional_kwargs():
    m = Mock()

    @fn
    def example(a, b):
        return a - b

    a_value = Value(10)
    b_value = Value(5)

    # Initial value should pass through
    result = example(a=a_value, b=b_value)
    result.on_value_changed(m)
    assert result.value == 5

    # Changes should propagate, callbacks should fire
    m.reset_mock()
    a_value.value = 20
    m.assert_called_once_with(15)
    assert result.value == 15

    m.reset_mock()
    b_value.value = -5
    m.assert_called_once_with(25)
    assert result.value == 25


def test_event_positional_args():
    m = Mock()

    @fn
    def example(*args, **kwargs):
        return (args, kwargs)

    a_value = Event()
    b_value = Event()

    result = example(a_value, b_value)
    assert isinstance(result, Event)
    result.on_event(m)

    # Changes should propagate, callbacks should fire
    m.reset_mock()
    a_value.emit(123)
    m.assert_called_once_with(((123, NoValue), {}))

    m.reset_mock()
    b_value.emit(123)
    m.assert_called_once_with(((NoValue, 123), {}))


def test_event_kwargs():
    m = Mock()

    @fn
    def example(*args, **kwargs):
        return (args, kwargs)

    a_value = Event()
    b_value = Event()

    # No value should be assigned
    result = example(a=a_value, b=b_value)
    assert isinstance(result, Event)
    result.on_event(m)

    # Changes should propagate, callbacks should fire
    m.reset_mock()
    a_value.emit(123)
    m.assert_called_once_with(((), {"a": 123, "b": NoValue}))

    m.reset_mock()
    b_value.emit(123)
    m.assert_called_once_with(((), {"a": NoValue, "b": 123}))


def test_mixed():
    """check that mixed use results in an event, with correct event buffering"""

    @fn
    def example(a, b, c):
        return a, b, c

    # without buffering events until on_inputs_done, value updates would be missed
    e = Event()
    v = event_to_value(e)
    e2 = Event()

    result = example(e, v, e2)
    assert isinstance(result, Event)

    result.on_event(m := Mock())

    m.reset_mock()
    e.emit(5)
    m.assert_called_once_with((5, 5, NoValue))

    m.reset_mock()
    e2.emit(6)
    m.assert_called_once_with((NoValue, 5, 6))


def test_nochange_value():
    v = Value(5)

    @fn
    def f(x):
        return NoChange if x == 10 else x

    vv = f(v)
    vv.on_value_changed(m := Mock())

    assert vv.value == 5

    m.reset_mock()
    v.value = 6
    assert vv.value == 6
    m.assert_called_once_with(6)

    m.reset_mock()
    v.value = 10
    assert vv.value == 6
    m.assert_not_called()


def test_nochange_event():
    e = Event()

    @fn
    def f(x):
        return NoChange if x == 10 else x

    ee = f(e)
    ee.on_event(m := Mock())

    m.reset_mock()
    e.emit(6)
    m.assert_called_once_with(6)

    m.reset_mock()
    e.emit(10)
    m.assert_not_called()
