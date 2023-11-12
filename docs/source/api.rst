.. module:: yarp

``yarp`` API
============

Value and Event types
---------------------

At the core of the ``yarp`` API are the `Value` and `Event` types, defined below.

.. autoclass:: Value

.. autoclass:: Event

.. autoclass:: Reactive

.. autodata:: NoValue

    A special value indicating that a ``yarp`` value has not been assigned a value.

.. autodata:: NoChange

    A value returned by callbacks indicating that no change should be made to a
    value, or no event should be emitted.

Aggregate Values
----------------

The ``yarp`` API provides a limited set of convenience functions which which
turn certain native Python data structures into :py:class:`Value`\ s which
update whenever the underlying :py:class:`Value`\ s do.

.. autofunction:: value_list

.. autofunction:: value_tuple

.. autofunction:: value_dict

Value casting
-------------

The following low-level functions are provided for creating and casting
`Value` and `Event` objects.

.. autofunction:: ensure_value

.. autofunction:: value_to_event

.. autofunction:: event_to_value

Value Operators
---------------

The `Value` and `Event` classes also supports many (but not all) of the native
Python operations, producing corresponding `Value` or `Event` objects. These
operations support the mixing of `Value`, `Event` and other suitable Python
objects, following the same rules as `fn`. The following operators are
supported:

* Arithmetic
    * ``a + b``
    * ``a - b``
    * ``a * b``
    * ``a @ b``
    * ``a / b``
    * ``a // b``
    * ``a % b``
    * ``divmod(a, b)``
    * ``a ** b``
* Bit-wise
    * ``a << b``
    * ``a >> b``
    * ``a & b``
    * ``a | b``
    * ``a ^ b``
* Unary
    * ``-a``
    * ``+a``
    * ``abs(a)``
    * ``~a``
* Comparison
    * ``a < b``
    * ``a <= b``
    * ``a == b``
    * ``a != b``
    * ``a >= b``
    * ``a > b``
* Container operators
    * ``a[key]``
* Numerical conversions
    * ``complex(a)``
    * ``int(a)``
    * ``float(a)``
    * ``round(a)``
* Python object/function usage
    * ``a(...)`` will call the value as a function and return a
      `Value` or `Event` containing the result. This will be updated by
      re-calling the function whenever the input changes. Like :py:func:`fn`,
      arguments may be `Value` or `Event` objects and these will be unwrapped
      before the function is called and will also cause the function to be
      re-evaluated whenever they change. Do not use this to call functions with
      side effects.
    * ``a.name`` equivalent to ``yarp.getattr(a, "name")``


Unfortunately this list *doesn't* include boolean operators (i.e.  ``not``,
``and``, ``or`` and ``bool``). This is due to a limitation of the Python data
model which means that ``bool`` may only return an actual boolean value, not
some other type of object. As a workaround you can substitute:

* ``bool(a)`` for ``a == True`` (works in most cases)
* ``a and b`` for ``a & b`` (works for boolean values but produces numbers)
* ``a or b`` for ``a | b`` (works for boolean values but produces numbers)

For a similar reasons, the ``len`` and ``in`` operators are also not supported.

This list also doesn't include mutating operators, for example ``a[key] = b``.
This is because the Python objects within a :py:class:`Value` are treated as
being immutable.

Python builtins
---------------

The ``yarp`` API provides versions of a number of
Python builtins and functions from the standard library which work with `Value`
and `Event`:

* Builtins
    * ``bool(a)``
    * ``any(a)``
    * ``all(a)``
    * ``min(a)``
    * ``max(a)``
    * ``sum(a)``
    * ``map(a)``
    * ``sorted(a)``
    * ``str(a)``
    * ``repr(a)``
    * ``str_format(a, ...)`` (equivalent to ``a.format(...)``)
    * ``oct(a)``
    * ``hex(a)``
    * ``zip(a)``
    * ``len(a)``
    * ``getattr(object, name[, default])``
* Most non-mutating, non-underscore prefixed functions from the
  :py:mod:`operator` module.

As above, these follow the same rules as `fn`: the result will be an `Event` if
any of the inputs are `Event`\ s, otherwise `Value`.

Function wrappers
-----------------

The primary mode of interaction with ``yarp`` `Value`\ s and `Event`\ s is
intended to be via simple Python functions wrapped with `fn`, defined below.

.. autofunction:: fn

General Value manipulation
--------------------------

The following utility functions are defined.

.. autofunction:: replace_novalue

.. autofunction:: window

.. autofunction:: no_repeat

.. autofunction:: filter

Temporal Value manipulation
---------------------------

The following utility functions are used to modify or observe how `Value`\ s
and `Event`\ s change over time. These all use :py:mod:`asyncio` internally and
require that a :py:class:`asyncio.BaseEventLoop` be running.

.. autofunction:: delay

.. autofunction:: time_window

.. autofunction:: rate_limit

.. autofunction:: emit_at

File-backed Values
------------------

The following function can be used to make *very* persistent
:py:class:`Value`\ s

.. autofunction:: file_backed_value

Time Values
-----------

The following function can be used to get the (continously changing) date and
time:

.. autofunction:: now
