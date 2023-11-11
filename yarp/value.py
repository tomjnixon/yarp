import functools
import sentinel
import warnings
import weakref
import threading
from contextlib import contextmanager

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
"""
a value returned by callbacks indicating that no change should be made to a value
"""


_transaction_state = threading.local()
_transaction_state.mark_changed = None


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
        # dependencies to run
        self._tmp_changed = None
        self._tmp_to_run = None
        # mapping from id of dependencies to their index
        self._id_to_idx = None

        # add self to dependency lists of inputs. because no new inputs can be
        # added to this FnValue, all dependency lists remain topologically sorted
        for input in self._inputs:
            input._add_dependency(self)

    def _on_inputs_done(self):
        # called when inputs have finished changing (all on-change callbacks have ran)
        raise NotImplementedError()

    def _on_change(self):
        # call when this has changed and dependencies need to run
        mark_changed = _transaction_state.mark_changed
        if mark_changed is None:
            self._on_external_change()
        else:
            if not mark_changed(self):
                self._on_external_change()

    def _on_external_change(self):
        # called when something external has changed this (e.g. by writing to
        # .value), and all dependents need to update too
        # XXX: fix lax weak dereference

        if not self._dependencies:
            # nothing to do, don't bloat this object with dependency information
            return

        if self._all_dependencies is None or any(
            dep()._dependencies_version != expected_version
            for dep, expected_version in zip(
                self._all_dependencies, self._all_dependencies_versions
            )
        ):
            self._all_dependencies = self._toposorted_dependencies()
            # XXX: fix lax weak dereference
            self._all_dependencies_versions = [
                dep()._dependencies_version for dep in self._all_dependencies
            ]
            # XXX: fix lax weak dereference
            self._id_to_idx = {
                id(dep()): idx for idx, dep in enumerate(self._all_dependencies)
            }
            # XXX: fix lax weak dereferences
            self._dependent_idxes = [
                [self._id_to_idx[id(dep_dep())] for dep_dep in dep()._dependencies]
                for dep in self._all_dependencies
            ]
            self._tmp_changed = [False] * len(self._all_dependencies)
            self._tmp_to_run = [False] * len(self._all_dependencies)

        id_to_idx = self._id_to_idx
        tmp_changed = self._tmp_changed
        tmp_to_run = self._tmp_to_run
        dependent_idxes = self._dependent_idxes

        for i in range(len(tmp_changed)):
            tmp_changed[i] = False
            tmp_to_run[i] = False

        def mark_changed(obj):
            try:
                idx = id_to_idx[id(obj)]
            except KeyError:
                warnings.warn(
                    f"untracked dependency from {self!r} (id {id(self)}) "
                    f"to {obj!r} (id {id(obj)})"
                )
                return False
            else:
                if not tmp_changed[idx]:
                    tmp_changed[idx] = True
                    for dep_idx in dependent_idxes[idx]:
                        tmp_to_run[dep_idx] = True
                return True

        mark_changed(self)

        old_mark_changed = _transaction_state.mark_changed
        _transaction_state.mark_changed = mark_changed

        try:
            for i in range(1, len(self._all_dependencies)):
                if tmp_to_run[i]:
                    dep = self._all_dependencies[i]()
                    if dep is not None:
                        dep._on_inputs_done()
        finally:
            _transaction_state.mark_changed = old_mark_changed

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
        assert all_deps[0]() is self

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
    """represents a value that changes over time

    Parameters
    ----------
    initial_value
        the value of this object on construction
    inputs : Iterable[Reactive]
        other reactive objects (`Value` or `Event`) whose changes cause the
        value of this object to be updated, either through ``get_value``, or
        assignment to `value` inside their `on_value_changed` or
        `Event.on_event` callbacks
    get_value : Callable[[], Any]
        a callback which when called with no arguments returns a new value for
        this object

        If provided, this is called during construction (overriding
        ``initial_value``), and once after all objects specified in ``inputs``
        have finished updating in a transaction.

        This may return `NoChange`, in which case `value` will not be updated.

    """

    def __init__(self, initial_value=NoValue, inputs=(), get_value=None):
        super(Value, self).__init__(inputs)

        self._value = initial_value
        self._on_value_changed = []
        self._get_value = get_value

        # sets value to _get_value(), with conditions
        self._on_inputs_done()

    @property
    def value(self):
        """
        the current value of this object

        If not yet set (either in the constructor or by assigning to this
        property), this will be ``NoValue``.

        Setting this property will call the :py:class:`on_value_changed`
        callbacks.
        """
        return self._value

    @value.setter
    def value(self, new_value):
        self._value = new_value
        for cb in self._on_value_changed:
            cb(new_value)
        self._on_change()

    def on_value_changed(self, cb):
        """
        Registers ``cb`` as a callback function to be called when this
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

    def _on_inputs_done(self):
        if self._get_value is None:
            return

        new_value = self._get_value()
        if new_value is not NoChange:
            self.value = new_value

    def __repr__(self):
        return "Value({})".format(repr(self.value))

    def __str__(self):
        return repr(self)


class Event(Reactive):
    def __init__(self, inputs=(), on_inputs_done=None):
        super(Event, self).__init__(inputs)

        self._callbacks = []
        self._on_inputs_done_cb = on_inputs_done

    def on_event(self, cb):
        self._callbacks.append(cb)
        return cb

    def emit(self, value):
        for cb in self._callbacks:
            cb(value)
        self._on_change()

    def _on_inputs_done(self):
        if self._on_inputs_done_cb is not None:
            self._on_inputs_done_cb(self.emit)


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
    result_list = [v.value for v in list_of_values]

    def element_changed(index, new_value):
        result_list[index] = new_value

    for i, value in enumerate(list_of_values):
        value.on_value_changed(functools.partial(element_changed, i))

    def get_value():
        return result_list.copy()

    return Value(inputs=list_of_values, get_value=get_value)


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
    result_list = [v.value for v in tuple_of_values]

    def element_changed(index, new_value):
        result_list[index] = new_value

    for i, value in enumerate(tuple_of_values):
        value.on_value_changed(functools.partial(element_changed, i))

    def get_value():
        return tuple(result_list)

    return Value(inputs=tuple_of_values, get_value=get_value)


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
    result_dict = {k: v.value for k, v in dict_of_values.items()}

    def element_changed(key, new_value):
        result_dict[key] = new_value

    for key, value in dict_of_values.items():
        value.on_value_changed(functools.partial(element_changed, key))

    def get_value():
        return result_dict.copy()

    return Value(inputs=tuple(dict_of_values.values()), get_value=get_value)


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


def value_to_event(source_value):
    """make an Event which emits the new value of source_value whenever it changes"""
    event = Event(inputs=(source_value,))
    source_value.on_value_changed(event.emit)
    return event


def event_to_value(source_event, initial_value=NoValue):
    """make a Value which takes its value from events of source_event"""
    value = Value(initial_value=initial_value, inputs=(source_event,))

    @source_event.on_event
    def _(new_value):
        value.value = new_value

    return value
