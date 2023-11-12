import pytest

from mock import Mock

from yarp import (
    NoValue,
    Event,
    Value,
    value_list,
    value_tuple,
    value_dict,
    ensure_value,
    value_to_event,
    event_to_value,
)


def test_initial_value_default():
    v = Value()
    assert v.value is NoValue


def test_initial_value_specified():
    v = Value(123)
    assert v.value == 123


def test_change_callback():
    m = Mock()

    v = Value()
    v.on_value_changed(m)

    v.value = 123
    m.assert_called_once_with(123)


@pytest.mark.parametrize("f", [repr, str])
def test_repr(f):
    assert f(Value(123)) == "Value(123)"
    assert f(Value("hi")) == "Value('hi')"


def test_value_list_persistent():
    a = Value("a")
    b = Value("b")
    c = Value("c")

    lst = value_list([a, b, c])

    # Initial value should have passed through
    assert lst.value == ["a", "b", "c"]

    m = Mock()
    lst.on_value_changed(m)

    # Changes should propagate through
    a.value = "A"
    assert lst.value == ["A", "b", "c"]
    m.assert_called_once_with(["A", "b", "c"])

    m.reset_mock()
    b.value = "B"
    assert lst.value == ["A", "B", "c"]
    m.assert_called_once_with(["A", "B", "c"])

    m.reset_mock()
    c.value = "C"
    assert lst.value == ["A", "B", "C"]
    m.assert_called_once_with(["A", "B", "C"])


def test_value_tuple_persistent():
    a = Value("a")
    b = Value("b")
    c = Value("c")

    tup = value_tuple((a, b, c))

    # Initial value should have passed through
    assert tup.value == ("a", "b", "c")

    m = Mock()
    tup.on_value_changed(m)

    # Changes should propagate through
    a.value = "A"
    assert tup.value == ("A", "b", "c")
    m.assert_called_once_with(("A", "b", "c"))

    m.reset_mock()
    b.value = "B"
    assert tup.value == ("A", "B", "c")
    m.assert_called_once_with(("A", "B", "c"))

    m.reset_mock()
    c.value = "C"
    assert tup.value == ("A", "B", "C")
    m.assert_called_once_with(("A", "B", "C"))


def test_value_dict_persistent():
    a = Value("a")
    b = Value("b")
    c = Value("c")

    dct = value_dict({"a": a, "b": b, "c": c})

    # Initial value should have passed through
    assert dct.value == {"a": "a", "b": "b", "c": "c"}

    m = Mock()
    dct.on_value_changed(m)

    # Changes should propagate through
    a.value = "A"
    assert dct.value == {"a": "A", "b": "b", "c": "c"}
    m.assert_called_once_with({"a": "A", "b": "b", "c": "c"})

    m.reset_mock()
    b.value = "B"
    assert dct.value == {"a": "A", "b": "B", "c": "c"}
    m.assert_called_once_with({"a": "A", "b": "B", "c": "c"})

    m.reset_mock()
    c.value = "C"
    assert dct.value == {"a": "A", "b": "B", "c": "C"}
    m.assert_called_once_with({"a": "A", "b": "B", "c": "C"})


def test_ensure_value_non_value():
    v = ensure_value(123)
    assert isinstance(v, Value)
    assert v.value == 123


def test_ensure_value_already_value():
    v = Value(123)
    vv = ensure_value(v)
    assert vv is v


def test_ensure_value_list():
    a = 123
    b = Value(456)

    v = ensure_value([a, b])
    assert isinstance(v, Value)
    assert v.value == [123, 456]

    b.value = 789
    assert v.value == [123, 789]


def test_ensure_value_tuple():
    a = 123
    b = Value(456)

    v = ensure_value((a, b))
    assert isinstance(v, Value)
    assert v.value == (123, 456)

    b.value = 789
    assert v.value == (123, 789)


def test_ensure_value_dict():
    a = 123
    b = Value(456)

    v = ensure_value({"a": a, "b": b})
    assert isinstance(v, Value)
    assert v.value == {"a": 123, "b": 456}

    b.value = 789
    assert v.value == {"a": 123, "b": 789}


def test_ensure_value_nested():
    a = Value(123)
    b = Value(456)
    c = Value(789)

    v = ensure_value({"a": a, "bc": [b, c]})
    assert isinstance(v, Value)
    assert v.value == {"a": 123, "bc": [456, 789]}

    b.value = 654
    assert v.value == {"a": 123, "bc": [654, 789]}


def test_value_to_event():
    v = Value(1)

    e = value_to_event(v)
    m = Mock()
    e.on_event(m)

    v.value = 2
    m.assert_called_once_with(2)


def test_event_to_value():
    e = Event()

    v = event_to_value(e)
    assert v.value is NoValue

    m = Mock()
    v.on_value_changed(m)

    e.emit(2)
    assert v.value == 2
    m.assert_called_once_with(2)


def test_dep_ordering():
    def add(value, event):
        event_buf = []
        event.on_event(event_buf.append)

        def on_inputs_done(emit):
            for ev in event_buf:
                emit(value.value + ev)
            event_buf.clear()

        return Event(inputs=(value, event), on_inputs_done=on_inputs_done)

    # this particular structure if guaranteed to be broken if add doesn't use
    # on_inputs_done

    e = Event()

    ee = Event(inputs=(e,))
    e.on_event(ee.emit)

    v = event_to_value(e, initial_value=0)

    s = add(v, ee)
    results = []
    s.on_event(results.append)

    e.emit(2)
    assert results == [4]

    e.emit(3)
    assert results == [4, 6]


@pytest.mark.parametrize("has_dep", [True, False])
def test_missing_dep(has_dep):
    initial = Value(0)
    if has_dep:
        hanging_dep = initial + 1

    missing_input = Value(initial.value)

    @initial.on_value_changed
    def initial_changed(new_value):
        missing_input.value = new_value

    missing_input_dep = missing_input + 1

    with pytest.warns(UserWarning, match="untracked dependency"):
        initial.value = 2

    assert missing_input.value == 2
    assert missing_input_dep.value == 3
    if has_dep:
        assert hanging_dep.value == 3


def test_loop_dep():
    v1 = Value()
    v2 = Value(v1.value, inputs=(v1,))

    v1.add_input(v2)

    with pytest.raises(RuntimeError, match="dependency loop"):
        v1.value = 1
