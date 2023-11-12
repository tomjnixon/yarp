.. currentmodule:: yarp

Using Values and Events
=======================

The two fundamental types in ``yarp`` are `Value` and `Event`. Basic uses of
these are shown in the introduction, and the API docs describe their API, but
the purpose of this page is to show some of the different ways that these
should be used.

Using `fn` and ``yarp`` utilities
---------------------------------

The most straightforward way to build things with yarp is to transform `Value`\
s and `Event`\ s using pure functions and `fn`, and use the utilities in `yarp`
to add stateful behaviours where necessary.

Say for example we have a function ``motion_sensor()``, which returns an `Event`
which emits whenever motion is detected in a room, and a function
``set_lights(Value)`` which accepts a `Value` containing a bool, and turns the
lights on or off depending on that value, whenever it changes.

We can use `time_window` and `fn` to make a simple timer-controlled light
behaviour:

.. code-block::

    # an Event representing detected motion
    motion_event = motion_sensor()

    # a Value containing a list of the values emitted by motion_event in the
    # last minute
    recent_motion = time_window(motion_event, 60)

    # a function which takes the list of recent motion events (as a `Value`)
    # and returns True if it contains any events
    @fn
    def any_motion(recent_motion):
        return len(recent_motion) > 0

    # a Value containing a bool, indicating whether the lights should be on or off
    light_state = any_motion(recent_motion)
    # continuously set the lights to the desired state
    set_lights(light_state)

In this case it would be possible to implement without `fn`, using yarp's
wrapped built-ins and operator overloading, for example:

.. code-block::

    # yarp.len returns a Value, which has an overloaded > operator, which also
    # returns a Value
    light_state = yarp.len(recent_motion) > 0

A case where this might actually be necessary is if we wanted to add a way to
override the light state. For example if we have a function ``get_override()``
which returns a `Value` containing None (no override) or True/False (override
to on or off):

.. code-block::

    @fn
    def apply_override(input, override):
        if override is None:
            return input
        else:
            return override

    set_lights(apply_override(light_state, get_override()))

Here, ``apply_override`` takes two `Value`\ s, and combines them into one with the
override logic applied.

There's more that can be done with `fn` (see the documentation, it can handle
`Event`\ s too), and this technique can get you quite far, but what if you need
to implement your own stateful things, or the input/output functions used
above?

Using Values
------------

The exact behaviours of Value are described in `the API documentation<Value>`,
but in practice there are 5 main ways to interact with them (beyond using `fn`,
overloads and utilities in `yarp`), shown in the examples below.

Source Values
~~~~~~~~~~~~~

These represent the value of some external state, and have no dependencies:

.. code-block::

    def get_value():
        v = Value(initial_value=get_current_state())

        def some_callback(new_state):
            # later, inside an asyncio callback indicating that the state has changed
            v.value = new_state

        something.register_callback(some_callback)

        return v

`Value.value` is set in some asyncio callback; this runs its `on_value_changed`
callbacks, informing listeners that the value has changed.

.. _output-values:

Output Values
~~~~~~~~~~~~~

Functions like ``set_lights`` in the example above take a `Value` and make
changes to other systems or the real world depending based in its value. For
example if ``change_light_state`` takes a plain bool and turns the light
on/off:

.. code-block::

    def set_lights(state):
        change_light_state(state.value)

        state.on_value_changed(change_light_state)

Note that it's possible that after calling this, there are no references to
``state``, so it may be garbage collected (bad). Real implementations must
either keep a reference to the input values in functions like ``set_lights``,
or make sure to keep references to the values passed to them:

.. code-block::

    # bad
    set_lights(apply_override(...))

    # good
    light_state = apply_override(...)
    set_lights(light_state)

Functional Values
~~~~~~~~~~~~~~~~~

These represent a transformation of some other value. These should generally
be made with `fn` or overloads instead:

.. testsetup::

    >>> from yarp import Event, Value, event_to_value

.. doctest::


    >>> x = Value(1)
    >>> y = Value(inputs=(x,), get_value=lambda: x.value + 1)
    >>> y.value
    2
    >>> x.value = 3
    >>> y.value
    4

Any input values used in ``get_value`` must be specified in ``inputs``.

Stateful Values Using get_value
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is when state is mutated state using callbacks, but updated in
``get_value``.  This is particularly useful when merging multiple values to
avoid updating the value more than once in a transaction.

.. doctest::

    >>> def history(input_value):
    ...     '''a value containing the historic values of input_value'''
    ...     values = [input_value.value]
    ...     input_value.on_value_changed(values.append)
    ...     return Value(inputs=(input_value,), get_value=values.copy)

    >>> x = Value(1)
    >>> h = history(x)
    >>> h.value
    [1]
    >>> x.value = 2
    >>> h.value
    [1, 2]

All `Value`\ s and `Event`\ s which mutate the state must be listed in
``inputs``, otherwise ``get_value`` will never be called and the result will
not update.

Stateful Values by Setting .value
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This is when `Value.value` is written directly in a callback. This is most
useful when the value reacts to both input values (specified in inputs) and
external events (e.g. asyncio callbacks).

.. doctest::

    >>> def integrate(input_value):
    ...     '''get a value containing the sum of all input values of
    ...      input_value over time'''
    ...     result = Value(input_value.value, inputs=(input_value,))
    ...
    ...     @input_value.on_value_changed
    ...     def on_value_changed(new_value):
    ...         result.value = result.value + new_value
    ...
    ...     return result

    >>> x = Value(0)
    >>> i = integrate(x)
    >>> i.value
    0
    >>> x.value = 2
    >>> x.value = 3
    >>> i.value
    5

Using Events
------------

`Event`\ s largely follow the same patterns as `Value`\ s, with minor
differences. Again, see `the API documentation<Event>` first for the exact
semantics.

Source Events
~~~~~~~~~~~~~

These represent events from something outside yarp, and have no dependencies:

.. code-block::

    def get_event():
        e = Event()

        def some_callback(value):
            # later, inside an asyncio callback indicating that something has happened
            e.emit(value)

        something.register_callback(some_callback)

        return e

`Event.emit` is called in some asyncio callback; this runs its `Event.on_event`
callbacks, informing listeners that something has happened.

Output Events
~~~~~~~~~~~~~

It's possible (though perhaps unusual) to define functions that take an `Event`
and make something happen in the real world when it emits a value:

.. code-block::

    def do_something_on_event(event):
        event.on_event(actually_do_something)

The same warnings about dangling references in :ref:`output-values` apply here too.

Functional Events
~~~~~~~~~~~~~~~~~

These represent a transformation of some other event. These should generally
be made with `fn` or overloads instead:

.. doctest::

    >>> x = Event()
    >>> y = Event(inputs=(x,))
    >>> x.on_event(lambda value: y.emit(value + 1))
    <...>
    >>> y.on_event(print)  # normally you'd do something else with y here
    <...>
    >>> x.emit(1)
    2

Any `Event` or `Value` that can trigger ``y.emit`` should be listed in the
``inputs`` of ``y``.

Stateful Events
~~~~~~~~~~~~~~~

This is largely the same as above, but using some nonlocal state:

.. doctest::

    >>> def diff(input):
    ...     last = 0
    ...
    ...     result = Event(inputs=(input,))
    ...
    ...     @input.on_event
    ...     def on_event(value):
    ...         nonlocal last
    ...         result.emit(value - last)
    ...         last = value
    ...
    ...     return result

    >>> x = Event()
    >>> y = diff(x)
    >>> y.on_event(print)  # normally you'd do something else with y here
    <...>
    >>> x.emit(1)
    1
    >>> x.emit(5)
    4

Using on_inputs_done
~~~~~~~~~~~~~~~~~~~~

When combining Events and Values it may be necessary to use ``on_inputs_done``
to get the correct behaviour. This callback runs when all Values or Events
listed in ``inputs`` have finished updating. If it is not used when combining
Events and Values, then value updates that happen in the same transaction as
the event may be missed. For example, this shows one way this can go wrong:

.. doctest::

    >>> def add_badly(value, event):
    ...     result = Event(inputs=(value, event))
    ... 
    ...     @event.on_event
    ...     def on_event(event_value):
    ...         result.emit(value.value + event_value)
    ... 
    ...     return result

    >>> e = Event()
    >>> ee = Event(inputs=(e,))
    >>> e.on_event(ee.emit)
    <...>
    >>> v = event_to_value(e, initial_value=0)
    >>> s = add_badly(v, ee)
    >>> s.on_event(print)
    <...>
    >>> e.emit(2)
    2
    >>> e.emit(2)
    4

What's going on here? When ``e`` emits, the first callback is for ``ee.emit``,
which in turn triggers ``on_emit`` in ``add_badly``, which finally calls
``result.emit``. This all happens before the second callback registered on
``e`` (in `event_to_value`) which updates ``v.value``, so ``on_event`` sees the
old value of ``v`` (0), and emits the wrong value.

In the second call to ``e.emit``, the old value was again used, but this time
it's accidentally correct.

This seems contrived (it is, particularly as the problem doesn't appear if ``ee``
is made using `fn` because of lucky dependency ordering), but can happen in
real-world situations.

How to solve this problem?

First, just use `fn`, it handles this for you.

To implement things like `fn`, though, use ``on_inputs_done`` to emit events
after inputs have finished updating:

.. doctest::

    >>> def add_goodly(value, event):
    ...     event_buf = []
    ...     event.on_event(event_buf.append)
    ...
    ...     def on_inputs_done(emit):
    ...         for ev in event_buf:
    ...             emit(value.value + ev)
    ...         event_buf.clear()
    ... 
    ...     return Event(inputs=(value, event), on_inputs_done=on_inputs_done)

    >>> e = Event()
    >>> ee = Event(inputs=(e,))
    >>> e.on_event(ee.emit)
    <...>
    >>> v = event_to_value(e, initial_value=0)
    >>> s = add_goodly(v, ee)
    >>> s.on_event(print)
    <...>
    >>> e.emit(2)
    4

The chain of callbacks described above (``e`` -> ``ee`` -> ``event.on_event``
in ``add_goodly``) still happens, but now events aren't emitted from ``s``
until ``e``, ``ee`` and ``v`` have finished updating, so the result is as
expected.

Note that events are buffered in a list. This is because events can emit more
than once in a transaction. ``on_inputs_done`` is called with the `Event.emit`
function of the Event that it's registered to, to avoid a circular reference.

Transactions
------------

Transactions are mentioned a few times above, but what are they and how do they
work?

Transactions exist only to run the ``get_value`` and ``on_inputs_done``
callbacks on Values and Events, once the objects listed in their ``inputs``
have finished updating.

These callbacks are necessary to have a place to update a Value or Event once,
even if there is a diamond in the graph of dependencies, as in the example
above.

Transactions are started automatically, and consist of the following steps:

- Something outside of yarp initiates a change to a `Value` or `Event` (called
  the "initial object" below), by setting `Value.value` or calling
  `Event.emit`. This starts the transaction.

- Change recording starts: any `Value` or `Event` objects which are changed are
  recorded.

- The ``on_value_changed`` or ``on_event`` callbacks of the initial object are
  ran, possibly causing updates to dependent objects, which are recorded.

- The ``get_value`` and ``on_inputs_done`` callbacks of transitive dependencies
  of the initial object are ran, in topologically-sorted order.

  Objects are skipped if none of their inputs have been marked as changed. Each
  of these callbacks may cause more callbacks to run, and thus more objects to
  be marked as changed.

- Change recording stops, and the transaction ends.

The dependency information (``inputs``) are required to correctly order the
dependencies. Some missing dependencies can be detected, but not all. When a
dependency is missing, all callbacks will still run (possibly in a nested
transaction, with a warning), but possibly not in the order that solves the
issue shown above.

It is sometimes not possible to specify all inputs in the `Event` or `Value`
constructor. In that case, use `Reactive.add_input`.

Thread Safety
-------------

There is none -- yarp is intended to be used without concurrency or with
asynchronous programming. If you really want to use it with threads, either
ensure that all yarp operations (constructing or updating objects) happen on
only one thread, or are protected by a lock.
