import functools
import sentinel
import warnings
import weakref
import threading
from contextlib import contextmanager
from typing import Optional

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


def _toposorted_dependencies(reactive):
    """get a list of topologically-sorted dependencies of reactive"""
    all_deps = []

    _dfs_deps(reactive, all_deps, visited=set())

    all_deps.reverse()
    assert all_deps[0] is reactive

    return all_deps


def _dfs_deps(reactive, all_deps: list, visited: set):
    """visit dependencies of reactive in depth-first order, then append to
    all_deps, using visited to skip repeated dependencies
    """
    if id(reactive) in visited:
        return

    for weak_dependency in reactive._dependencies:
        if (dependency := weak_dependency()) is not None:
            _dfs_deps(dependency, all_deps, visited)

    visited.add(id(reactive))
    all_deps.append(reactive)


class _TransactionInfo:
    """A cache of dependency information and temporary values needed to run a
    transaction starting at a given reactive value
    """

    def __init__(self, reactive):
        self.update(reactive)

    def update(self, reactive):
        def deref_weak(weak):
            """dereference a weak reference, asserting on failure"""
            ref = weak()
            assert ref is not None
            return ref

        all_deps = _toposorted_dependencies(reactive)
        # weak references to all dependencies topologically sorted (including
        # self)
        self._all_dependencies = [weakref.ref(dep) for dep in all_deps]

        # the version for each dependency
        self._all_dependencies_versions = [
            dep._dependencies_version for dep in all_deps
        ]

        # the index of each dependency, to be looked up by object id
        self._id_to_idx = {id(dep): idx for idx, dep in enumerate(all_deps)}

        # for each dependency, the index of dependents in _all_dependencies
        # note: we hold a non-weak reference to all dependencies, so
        # dereferencing dep_dep should not fail
        self._dependent_idxes = [
            [self._id_to_idx[id(deref_weak(dep_dep))] for dep_dep in dep._dependencies]
            for dep in all_deps
        ]

        # temporary lists the same length as _all_dependencies to keep track of
        # dependencies to run

        # was this dependency changed in this transaction? used to avoid
        # setting dependents to true in _tmp_to_run more than once
        self._tmp_changed = [False] * len(self._all_dependencies)
        # should this dependency run?
        self._tmp_to_run = [False] * len(self._all_dependencies)

    def needs_update(self):
        """does this need to be updated?"""
        for dep_ref, expected_version in zip(
            self._all_dependencies, self._all_dependencies_versions
        ):
            dep = dep_ref()
            if dep is None or dep._dependencies_version != expected_version:
                return True

        return False


class Reactive:
    """base class for reactive types (`Value` and `Event`)

    this only exists to handle dependency tracking and transactions
    """
    def __init__(self, inputs):
        self._inputs = list(inputs)

        self._dependencies = []
        # incremented whenever _dependencies is modified.
        # each Reactive checks that all dependents have not been modified when
        # it's ran by looking at this. an alternative would be to mark all
        # inputs recursively as dirty on construction/destruction, but that
        # would make graph construction/destruction O(n^2)
        self._dependencies_version = 0

        # information only needed if this value is the changed externally,
        # starting a transaction rooted here
        self._transaction_info: Optional[_TransactionInfo] = None

        # add self to dependency lists of inputs
        for input in self._inputs:
            input._add_dependency(self)

    def add_input(self, input: "Reactive"):
        """register a new input to this value

        Normally inputs should be specified in the constructor, but this is
        needed when the logical structure of dependencies (but not the actual
        dependencies) is circular. This can happen when using asyncio (which
        breaks loops by running callbacks asynchronously) -- see for example
        the implementation of functions like `rate_limit`.
        """
        self._inputs.append(input)
        input._add_dependency(self)

    def _on_inputs_done(self):
        # called when inputs have finished changing (all on-change callbacks have ran)
        raise NotImplementedError()

    @contextmanager
    def _in_transaction(self):
        """a context manager which runs the contained code in a transaction

        when called inside a transaction this just marks the current value as
        having been changed

        when called outside a transaction, it runs the code inside
        _in_new_transaction
        """
        mark_changed = _transaction_state.mark_changed
        if mark_changed is None:
            with self._in_new_transaction():
                yield
        else:
            if not mark_changed(self):
                # recursive transaction -- this is not a great idea, but
                # mark_changed already raised a warning
                with self._in_new_transaction():
                    yield
            else:
                yield

    @contextmanager
    def _in_new_transaction(self):
        """a context manager which runs the contained code in a new transaction

        this just records which dependencies have changed (according to whether
        they have called _in_transaction and therefore mark_changed), and runs
        the dependencies of those that have in topological order
        """
        # if we have no dependencies, mark_changed should always warn, and
        # there's no need to make a whole _TransactionInfo object. this is
        # mainly useful because it's reasonable to set Value.value during (or
        # just after) construction, before dependencies have been added
        if not self._dependencies:

            def mark_changed(obj):
                warnings.warn(
                    f"untracked dependency from {self!r} (id {id(self)}) "
                    f"to {obj!r} (id {id(obj)})"
                )

            old_mark_changed = _transaction_state.mark_changed
            _transaction_state.mark_changed = mark_changed

            try:
                yield
            finally:
                _transaction_state.mark_changed = old_mark_changed
            return

        # make sure _transaction_info is up-to-date
        if self._transaction_info is None:
            self._transaction_info = _TransactionInfo(self)
        elif self._transaction_info.needs_update():
            self._transaction_info.update(self)

        id_to_idx = self._transaction_info._id_to_idx
        tmp_changed = self._transaction_info._tmp_changed
        tmp_to_run = self._transaction_info._tmp_to_run
        dependent_idxes = self._transaction_info._dependent_idxes
        all_dependencies = self._transaction_info._all_dependencies

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
            yield

            for i in range(1, len(all_dependencies)):
                if tmp_to_run[i]:
                    dep = all_dependencies[i]()
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
        with self._in_transaction():
            self._value = new_value
            for cb in self._on_value_changed:
                cb(new_value)

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
        with self._in_transaction():
            for cb in self._callbacks:
                cb(value)

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
