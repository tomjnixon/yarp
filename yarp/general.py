"""
General purpose utility functions for manipulating :py:class:`Value` values.
"""

from yarp import NoValue, Value, Event, fn, ensure_value

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


def no_repeat(source_value):
    r"""
    Don't pass on change callbacks if the :py:class:`Value` hasn't changed.

    Works for both continuous and instantaneous :py:class:`Value`\ s.
    """
    source_value = ensure_value(source_value)
    last_value = source_value.value

    # Initially take on the source value
    output_value = Value(last_value)

    @source_value.on_value_changed
    def on_source_value_changed(new_value):
        nonlocal last_value
        if new_value != last_value:
            last_value = new_value
            # Copy to output whether continuous or instantaneous
            output_value._value = source_value.value
            output_value.set_instantaneous_value(new_value)

    return output_value


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


def filter(source_value, rule=NoValue):
    """Filter change events.

    The filter rule should be a function which takes the new value as an
    argument and returns a boolean indicating if the value should be passed on
    or not.

    If the source value is persistent, the persistent value will remain
    unchanged when a value change is not passed on.

    If the filter rule is ``None``, non-truthy values and ``NoValue`` will be
    filtered out. If the filter rule is ``NoValue`` (the default) only
    ``NoValue`` will be filtered out.
    """
    source_value = ensure_value(source_value)
    output_value = Value(
        source_value.value
        if (
            source_value.value is not NoValue and _check_value(source_value.value, rule)
        )
        else NoValue
    )

    @source_value.on_value_changed
    def on_source_value_changed(new_value):
        if _check_value(new_value, rule):
            output_value._value = source_value.value
            output_value.set_instantaneous_value(new_value)

    return output_value


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
