.. currentmodule:: yarp

.. _yarp-introduction:

Introduction
============

This programming style will be familiar to anyone who has used a spreadsheet.
In a spreadsheet you can put values into cells. You can also put functions into
cells which compute new values based on the values in other cells. The neat
feature of spreadsheets is that if you change the value in a cell, any other
cell whose value depends on it is automatically recomputed.

Using ``yarp`` you can define :py:class:`Value`\ s, and functions acting on
those values, which are automatically reevaluated when changed. For example:

.. doctest::

    >>> from yarp import Value, fn
    
    >>> # Lets define two Values which for the moment will just be '1'
    >>> a = Value(1)
    >>> b = Value(1)
    
    >>> # Define a function 'add' which adds two numbers together. The
    >>> # @fn decorator automatically wraps 'add' so that it takes Value
    >>> # objects as arguments and returns a Value object. The definition,
    >>> # however, is written just like you'd write any normal function:
    >>> # accepting and returning regular Python types.
    >>> @fn
    ... def add(a, b):
    ...     return a + b
    
    >>> # Calling 'add' on our 'a' and 'b' Value objects returns a new Value
    >>> # object with the result. Get the actual value using the 'value'
    >>> # property.
    >>> a_plus_b = add(a, b)
    >>> a_plus_b.value
    2
    
    >>> # Changing one of the input values will cause 'add' to automatically be
    >>> # reevaluated.
    >>> a.value = 5
    >>> a_plus_b.value
    6
    >>> b.value = 10
    >>> a_plus_b.value
    15
    
    >>> # Accessing attributes of a Value returns a Value-wrapped version of
    >>> # that attribute, e.g.
    >>> c = Value(complex(1, 2))
    >>> r = c.real
    >>> r.value
    1.0
    >>> i = c.imag
    >>> i.value
    2.0
    >>> c.value = complex(10, 100)
    >>> r.value
    10.0
    >>> i.value
    100.0
    
    >>> # You can also call (side-effect free) methods of Values to get a
    >>> # Value-wrapped version of the result which updates when the Value
    >>> # change:
    >>> c2 = c.conjugate()
    >>> c2.value
    (10-100j)
    >>> c.value = complex(123, 321)
    >>> c2.value
    (123-321j)

As well as representing continuous values which change at defined points in
time ``yarp`` can also represent :py:class:`Event`\ s which have a defined value
only instantaneously, for example an ephemeral sensor reading. For example:

.. doctest::

    >>> from yarp import Event

    >>> # Create an Event object which represents the speed of cars driving past a
    >>> # speed check. This has no value normally, but 'emits' a value (the car's
    >>> # speed) every time one passes.

    >>> car_speed_mph = Event()

    >>> # We live in a civilised world so lets convert that into KM/H. When an
    >>> # Event object is passed to a function decorated with `fn` (described
    >>> # above), the result is a new Event object which emits transformed
    >>> # events.
    >>> @fn
    ... def mph_to_kph(mph):
    ...     return mph * 1.6

    >>> car_speed_kph = mph_to_kph(car_speed_mph)

    >>> # Lets setup a callback to print a car's speed whenever it is measured
    >>> @car_speed_kph.on_event
    ... def on_car_measured(speed_kph):
    ...     print("A car passed at {} KM/H".format(speed_kph))

    >>> # Now lets instantaneously set the value as if a car has just gone past
    >>> # and watch as our callback is called with the speed in KM/H
    >>> car_speed_mph.emit(30)
    A car passed at 48.0 KM/H


As in these examples, the intention is that most ``yarp``-using code will be
based entirely on passing :py:class:`Value`\ s and :py:class:`Event`\ s around
between functions wrapped with :py:func:`fn`.

:ref:`using-values-and-events` shows how to use `fn` and the ``yarp``
utilities, and what to do when they are not enough.
