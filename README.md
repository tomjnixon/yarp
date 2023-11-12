`yarp`: Yet Another Reactive(-ish) Programming library for Python
=================================================================

This library facilitates a programming style which is a little bit like
[(functional-ish) reactive
programming](https://en.wikipedia.org/wiki/Functional_reactive_programming).

This particular repository is a fork of
[mossblaser/yarp](https://github.com/mossblaser/yarp), which exchanged
continuous/instantaneous values for two separate types, and adds a transaction
mechanism to avoid glitches when multiple values are combined.

Motivating Example
------------------

This programming style will be familiar to anyone who has used a spreadsheet.
In a spreadsheet you can put values into cells. You can also put functions into
cells which compute new values based on the values in other cells. The neat
feature of spreadsheets is that if you change the value in a cell, any other
cell whose value depends on it is automatically recomputed.

Using `yarp` you can define values, and functions acting on those values, which
are automatically re-evaluated when changed. For example:

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
time `yarp` can also represent events which have a defined value only
instantaneously, for example an ephemeral sensor reading. For example:

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

Comparison with other libraries
-------------------------------

`yarp`'s interpretation of the reactive programming model is a little
idiosyncratic. It was designed for defining certain simpler types of home
automation rules and may have shortcomings or missing features which prevent
its use in more sophisticated applications.

The [ReactiveX](http://reactivex.io/) [RxPY](https://github.com/ReactiveX/RxPY)
library is a particularly feature-rich reactive programming library aimed at
more 'serious' use than this library. As well as its fairly extensive library
of built-in facilities, performance, dynamically changing graphs of functions
and error handling were considered during its design. Meanwhile `yarp` eschews
all of this on the basis that it doesn't intend to be a comprehensive
programming system. If in doubt, this is likely the library you want to be
using, not `yarp`! With this said, one of RxPY's downsides is its verbosity.
Within its niche `yarp` can be both concise and 'obvious' in meaning.  This
makes it ideal for setting up quick-n-dirty home automation rules.  Further,
the ReactiveX model only supports instantaneous values while `yarp` supports
both instantaneous and persistent values.

The
[`metapensiero.reactive`](https://github.com/metapensiero/metapensiero.reactive)
library, inspired by the ['tracker' library for
Meteor](https://github.com/metapensiero/metapensiero.reactive) is an
impressively simple and initially magic seeming implementation of reactive
programming. Like `yarp` it allows you to (mostly) write your functions and
combine them just like you normally would. Unlike `yarp`, it doesn't wrap or
modify your functions and they even remain completely useable in a non-reactive
style. Instead it uses an 'auto-runner' which executes your function, logging
any uses of variables you have explicitly marked up and then re-runs the
function whenever a marked variable changes. Refer to the original Meteor
'tracker' implementation for a good description of how all this works.
Unfortunately `metapensiero.reactive` only supports continuous values while
`yarp` supports both continuous and persistent values.

Documentation
-------------

Documentation for `yarp` can be found on
[ReadTheDocs](http://yarp.readthedocs.io/).
