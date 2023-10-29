import functools
import sentinel
import weakref

__names__ = [
    "NoValue",
    "Value",
    "value_list",
    "value_tuple",
    "value_dict",
    "ensure_value",
    "make_instantaneous",
    "make_persistent",
]


NoValue = sentinel.create("NoValue")
"""
A special value indicating that a ``yarp`` value has not been assigned a value.
"""

NoChange = sentinel.create("NoChange")


class Reactive:
    def __init__(self, inputs):
        self._inputs = tuple(inputs)

        self._dependencies = []
        # incremented whenever _dependencies is modified.
        # each Reactive checks that all dependents have not been modified when
        # it's ran by looking at this. an alternative would be to mark all
        # inputs redursively as dirty on construction/destruction, but that
        # would make graph construction/destruction O(n^2)
        self._dependencies_version = 0

        # dependency information used to update downstream values/events
        # this is calculated when it's needed, and when any downstream
        # dependencies are changed.
        # all dependencies topologically sorted (including self)
        self._all_dependencies = None
        # the version for each dependency
        self._all_dependencies_versions = None
        # for each dependency, the index of dependents in _all_dependencies
        self._dependent_idxes = None

        # temporary list the same length as _all_dependencies to keep track of
        # dependencies to skip
        self._tmp_skip_dep = None

        # add self to dependency lists of inputs. because no new inputs can be
        # added to this FnValue, all dependency lists remain topologically sorted
        for input in self._inputs:
            input._add_dependency(self)

    def _on_inputs_changed(self):
        # called when inputs have finished changing (all on-change callbacks have ran)
        # should return true if dependents need to run
        raise NotImplementedError()

    def _on_external_change(self):
        # called when something external has changed this (e.g. by writing to
        # .value), and all dependents need to update too
        if self._all_dependencies is None or any(
            dep._dependencies_version != expected_version
            for dep, expected_version in zip(
                self._all_dependencies, self._all_dependencies_versions
            )
        ):
            self._all_dependencies = self._toposorted_dependencies()
            self._all_dependencies_versions = [
                dep._dependencies_version for dep in self._all_dependencies
            ]
            idx_by_id = {id(dep): idx for idx, dep in enumerate(self._all_dependencies)}
            self._dependent_idxes = [
                [idx_by_id[id(dep_dep)] for dep_dep in dep._dependencies]
                for dep in self._all_dependencies
            ]
            self._tmp_skip_dep = [False] * len(self._all_dependencies)

        for i in range(len(self._tmp_skip_dep)):
            self._tmp_skip_dep[i] = False

        for i in range(1, len(self._tmp_skip_dep)):
            skip = self._tmp_skip_dep[i]
            if skip:
                dep = self._all_dependencies[i]()
                if dep is not None:
                    skip = not self._all_dependencies[i]._on_inputs_changed()
                else:
                    skip = True

            if skip:
                for dep_i in self._dependent_idxes[i]:
                    self._tmp_skip_dep[dep_i] = True

    def _add_dependency(self, dependency):
        self._dependencies.append(weakref.ref(dependency, self._remove_dependency))
        self._dependencies_version += 1

    def _remove_dependency(self, weak_dependency):
        for i, dep in enumerate(self._dependencies):
            if dep is weak_dependency:
                del self._dependencies[i]
                self._dependencies_version += 1
                break
        else:
            assert False, "inconsistent dependency references"

    def _toposorted_dependencies(self):
        all_deps = []

        self._dfs_deps(all_deps, visited=set())

        all_deps.reverse()
        assert all_deps[0] is self

        return all_deps

    def _dfs_deps(self, all_deps, visited):
        if id(self) in visited:
            return

        for weak_dependency in self._dependencies:
            if (dependency := weak_dependency()) is not None:
                dependency._dfs_deps(all_deps, visited)

        visited.add(id(self))
        all_deps.append(weakref.ref(self))


class Value(Reactive):
    def __init__(self, initial_value=NoValue, inputs=(), get_value=None):
        super(Value, self).__init__(inputs)

        self._value = initial_value
        self._on_value_changed = []
        self._get_value = get_value

    @property
    def value(self):
        """
        A property holding the current continuous value held by this object. If
        not yet set, or if this object represents only instantaneous values,
        this will be ``NoValue``.

        Setting this property sets the (continuous) contents of this value
        (raising the :py:meth:`on_value_changed` callback afterwards).

        To change the value without raising a callback, set the
        :py:attr:`_value` attribute directly. This may be useful if you wish to
        make this Value mimic another by, in a callback function, setting
        :py:attr:`_value` in this Value directly from the other Value's
        :py:attr:`value` and calling :py:meth:`set_instantaneous_value` with
        the passed variable explicitly. You must always be sure to call
        :py:meth:`set_instantaneous_value` after changing :py:attr:`_value`.
        """
        return self._value

    @value.setter
    def value(self, new_value):
        self._value = new_value
        for cb in self._on_value_changed:
            cb(new_value)
        self._on_external_change()

    def on_value_changed(self, cb):
        """
        Registers ``callback`` as a callback function to be called when this
        value changes.

        The callback function will be called with a single argument: the value
        now held by this object.

        .. note::

            There is no way to remove callbacks. For the moment this is an
            intentional restriction: if this causes you difficulties this is a
            good sign what you're doing is 'serious' enough that ``yarp`` is
            not for you.

        This function returns the callback passed to it making it possible to
        use it as a decorator if desired.
        """
        self._on_value_changed.append(cb)
        return cb

    def _on_inputs_changed(self):
        if self._get_value is None:
            return False

        new_value = self._get_value()
        if new_value is NoChange:
            return False

        self._value = new_value
        for cb in self._on_value_changed:
            cb(new_value)

    def __repr__(self):
        return "Value({})".format(repr(self.value))

    def __str__(self):
        return repr(self)


class Event(Reactive):
    def __init__(self, inputs=(), on_inputs_done=None):
        super(Value, self).__init__(inputs)

        self._callbacks = []
        self._on_inputs_done = on_inputs_done

    def on_event(self, cb):
        self._callbacks.append(cb)
        return cb

    def emit(self, value):
        for cb in self._callbacks:
            cb(value)
        self._on_external_change()

    def emit_in_transaction(self, value):
        for cb in self._callbacks:
            cb(value)

    def _on_inputs_changed(self):
        emitted = False
        if self._on_inputs_done is not None:

            def emit(value):
                nonlocal emitted
                emitted = True
                for cb in self._callbacks:
                    cb(value)

            self._on_inputs_changed(emit)

        return emitted


def value_list(list_of_values):
    r"""
    Returns a :py:class:`Value` consisting of a fixed list of other
    :py:class:`Values <Value>`. The returned :py:class:`Value` will change
    whenever one of its members does.

    Parameters
    ----------
    list_of_values: [:py:class:`Value`, ...]
        A fixed list of :py:class:`Value`\ s. The :py:attr:`value` of this
        object will be an array of the underlying values. Callbacks will be
        raised whenever a value in the list changes.

        It is not possible to modify the list or set the contained values
        directly from this object.

        For instantaneous list members, the instantaneous value will be
        present in the version of this list passed to registered callbacks
        but otherwise not retained. (Typically the instantaneous values
        will be represented by :py:class:`NoValue` in :py:attr:`value` or
        in callbacks resulting from other :py:class:`Value`\ s changing.
    """
    output_value = Value([v.value for v in list_of_values])

    def element_changed(index, new_value):
        output_value._value[index] = list_of_values[index].value

        # Substitute in the instantaneous value of the changed element
        instantaneous_value = output_value.value.copy()
        instantaneous_value[index] = new_value

        output_value.set_instantaneous_value(instantaneous_value)

    for i, value in enumerate(list_of_values):
        value.on_value_changed(functools.partial(element_changed, i))

    return output_value


def value_tuple(tuple_of_values):
    r"""
    A :py:class:`Value` consisting of a tuple of other :py:class:`Values
    <Value>`.

    Parameters
    ----------
    tuple_of_values: (:py:class:`Value`, ...)
        A fixed tuple of :py:class:`Value`\ s. The :py:attr:`value` of this
        object will be a tuple of the underlying values. Callbacks will be
        raised whenever a value in the tuple changes.

        It is not possible to modify the tuple or set the contained values
        directly from this object.

        For instantaneous tuple members, the instantaneous value will be
        present in the version of this tuple passed to registered callbacks
        but otherwise not retained. (Typically the instantaneous values
        will be represented by :py:class:`NoValue` in :py:attr:`value` or
        in callbacks resulting from other :py:class:`Value`\ s changing.
    """
    output_value = Value(tuple(v.value for v in tuple_of_values))

    def element_changed(index, new_value):
        output_value._value = tuple(v.value for v in tuple_of_values)

        # Substitute in the instantaneous value of the changed element
        instantaneous_value = tuple(
            v.value if i != index else new_value for i, v in enumerate(tuple_of_values)
        )

        output_value.set_instantaneous_value(instantaneous_value)

    for i, value in enumerate(tuple_of_values):
        value.on_value_changed(functools.partial(element_changed, i))

    return output_value


def value_dict(dict_of_values):
    r"""
    A :py:class:`Value` consisting of a dictionary where the values (but not
    keys) are  :py:class:`Values <Value>`.

    Parameters
    ----------
    dict_of_values: {key: :py:class:`Value`, ...}
        A fixed dictionary of :py:class:`Value`\ s. The :py:attr:`value` of this
        object will be a dictionary of the underlying values. Callbacks will be
        raised whenever a value in the dictionary changes.

        It is not possible to modify the set of keys in the dictionary nor
        directly change the values of its elements from this object.

        For instantaneous dictionary members, the instantaneous value will
        be present in the version of this dict passed to registered
        callbacks but otherwise not retained. (Typically the instantaneous
        values will be represented by :py:class:`NoValue` in
        :py:attr:`value` or in callbacks resulting from other
        :py:class:`Value`\ s changing.
    """
    output_value = Value({k: v.value for k, v in dict_of_values.items()})

    def element_changed(key, new_value):
        output_value._value[key] = dict_of_values[key].value

        instantaneous_value = output_value.value.copy()
        instantaneous_value[key] = new_value

        output_value.set_instantaneous_value(instantaneous_value)

    for key, value in dict_of_values.items():
        value.on_value_changed(functools.partial(element_changed, key))

    return output_value


def ensure_value(value):
    """Ensure a variable is a :py:class:`Value` object, wrapping it accordingly
    if not.

    * If already a :py:class:`Value`, returns unmodified.
    * If a list, tuple or dict, applies :py:func:`ensure_value` to all contained values and
      returns a :py:class:`value_list`, :py:class:`value_tuple` or
      :py:class:`value_dict` respectively.
    * If any other type, wraps the variable in a continous :py:class:`Value`
      with the initial value set to the defined value.
    """
    if isinstance(value, Value):
        return value
    elif isinstance(value, list):
        return value_list([ensure_value(v) for v in value])
    elif isinstance(value, tuple):
        return value_tuple(tuple(ensure_value(v) for v in value))
    elif isinstance(value, dict):
        return value_dict({k: ensure_value(v) for k, v in value.items()})
    else:
        return Value(value)


def make_instantaneous(source_value):
    """
    Make a persistent :py:class`Value` into an instantaneous one which 'fires'
    whenever the persistant value is changed.
    """
    output_value = Value()
    ensure_value(source_value).on_value_changed(output_value.set_instantaneous_value)
    return output_value


def make_persistent(source_value, initial_value=NoValue):
    """
    Make an instantaneous :py:class:`Value` into a persistant one, keeping the old value
    between changes. Initially sets the :py:class:`Value` to ``initial_value``.
    """

    output_value = Value(initial_value)
    source_value = ensure_value(source_value)

    @source_value.on_value_changed
    def on_source_value_changed(new_value):
        output_value.value = new_value

    return output_value
