"""
General purpose utility functions for manipulating :py:class:`Value` values.
"""

from yarp import NoChange, NoValue, Value, Event, fn, ensure_value


__names__ = [
    "window",
    "no_repeat",
    "filter",
    "replace_novalue",
]


def window(source_value: Value | Event, num_values: int | Value) -> Value:
    """make a Value with the num_values most recent values or events from
    source_value

    If num_values is decreased then the return value will be cropped. If it is
    increased, then the return value will lengthen gradually with new events or
    changes.
    """
    num_values = ensure_value(num_values)

    output_values = []

    @num_values.on_value_changed
    def limit_values(num_values_value):
        while len(output_values) > num_values_value:
            output_values.pop(0)

    def add_value(new_value):
        output_values.append(new_value)
        limit_values(num_values.value)

    match source_value:
        case Event():
            source_value.on_event(add_value)
        case Value():
            output_values.append(source_value.value)
            source_value.on_value_changed(add_value)

    return Value(
        inputs=(source_value, num_values),
        get_value=lambda: output_values.copy(),
    )


def no_repeat(source):
    """don't repeat the previous event or value of source"""
    last_value = object()

    @fn
    def f(value):
        nonlocal last_value

        if value != last_value:
            last_value = value
            return value
        else:
            return NoChange

    return f(source)


def _check_value(value, rule):
    """Internal. Test a value, return whether it should be retained or
    not according to the provided rule.

    If the rule is NoValue, returns True for non-NoValue values, including None
    or falsey values.

    If the rule is None, returns True for non-NoValue values which are truthy.

    If the rule is a function, calls it with the value and expects a boolean to
    be returned.
    """
    if rule is NoValue:
        return value is not NoValue
    elif rule is None:
        return value is not NoValue and bool(value)
    else:
        return rule(value)


@fn
def filter(source, rule=NoValue):
    """Filter change events.

    The filter rule should be a function which takes the new value as an
    argument and returns a boolean indicating if the value should be passed on
    or not.

    If the source value is a Value, the old value will remain
    unchanged when a value change is not passed on. If the initial value does
    not pass the test, the initial value of the result will be NoValue.

    If the filter rule is ``None``, non-truthy values and ``NoValue`` will be
    filtered out. If the filter rule is ``NoValue`` (the default) only
    ``NoValue`` will be filtered out.
    """
    return source if _check_value(source, rule) else NoChange


@fn
def replace_novalue(source_value, replacement_if_novalue=None):
    """
    If the ``source_value`` is :py:data:`NoValue`, return
    ``replacement_if_novalue`` instead.

    Parameters
    ----------
    source_value : :py:class:`Value`
        An instantaneous or continuous :py:class:`Value`.
    replacement_if_novalue : Python object or :py:class:`Value`
        Replacement value to use if ``source_value`` has the value
        :py:data:`NoValue`.

    Returns
    -------
    A continuous :py:class:`Value` which will be a copy of ``source_value`` if
    ``source_value`` is not :py:data:`NoValue`, otherwise the value of
    ``replacement_if_novalue`` is used instead.
    """
    if source_value is NoValue:
        return replacement_if_novalue
    else:
        return source_value
