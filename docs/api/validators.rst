==========
Validators
==========

A validator is a callable that takes a value and raises a :ref:`ValidationError` if it doesn't meet some criteria. Validators can be useful for re-using validation logic between different types of fields.

For example, here's a validator that only allows positive numbers:

.. code-block:: python

    class PositiveNumberValidator:
        def __call__(self, value):
            if value < 0:
                raise ValidationError({'invalid': f"Value {value} is less than zero"})

    @domain.aggregate
    class Balance:
        account = String(required=True)
        currency = String(max_length=3, required=True)
        amount = Float(default=0.0, validators=[PositiveNumberValidator()])

Specifying negative balances throws a :ref:`ValidationError`::

    >>> balance = Balance(account='AC12345', currency='USD', amount=-599.0)
    ValidationError                           Traceback (most recent call last)
    ...
    ValidationError: {'amount': [{'invalid': 'Value -599.0 is less than zero'}]}


Built-in validators
-------------------

The ``protean.core.field.validators`` module contains a collection of callable validators for use with entity fields. They're used internally but are available for use with your own fields, too. They can be used in addition to, or in lieu of custom :ref:`Aggregate's Clean` method.

RegexValidator
~~~~~~~~~~~~~~

**class RegexValidator(regex=None, message=None, code=None, inverse_match=None, flags=None)**

Parameters:

- ``regex`` – The regular expression pattern to search for within the provided value, using re.search(). This may be a string or a pre-compiled regular expression created with re.compile(). Defaults to the empty string, which will be found in every possible value.
- ``message`` – The error message used by ``ValidationError`` if validation fails. Defaults to **"invalid value"**.
- ``code`` – The error code used by ``ValidationError`` if validation fails. Defaults to **"invalid"**.
- ``inverse_match`` – The match mode for ``regex``. Defaults to ``False``.
- ``flags`` – The |regex flags| used when compiling the regular expression string regex. If regex is a pre-compiled regular expression, and flags is overridden, TypeError is raised. Defaults to 0.

A ``RegexValidator`` searches the provided value for a given regular expression with ``re.search()``. By default, it raises a ``ValidationError`` with ``message`` and ``code`` if a match *is not* found. Its behavior can be inverted by setting ``inverse_match`` to True, in which case the ``ValidationError`` is raised when a match is found.

.. _max-value-validator:

MaxValueValidator
~~~~~~~~~~~~~~~~~

**class MaxValueValidator(max_value)**

Raises a ``ValidationError`` if value is greater than ``max_value``.

.. _min-value-validator:

MinValueValidator
~~~~~~~~~~~~~~~~~

**class MinValueValidator(max_value)**

Raises a ``ValidationError`` if value is greater than ``min_value``.

.. _max-length-validator:

MaxLengthValidator
~~~~~~~~~~~~~~~~~~

**class MaxLengthValidator(max_length)**

Raises a ``ValidationError`` if value is longer than ``max_value``.

.. _min-length-validator:

MinLengthValidator
~~~~~~~~~~~~~~~~~~

**class MinLengthValidator(min_length)**

Raises a ``ValidationError`` if value is longer than ``min_value``.

Writing custom validators
-------------------------

A validator is any *callable* class accepting a ``value``. The class can accept one or more rules as arguments during initialization. The ``__call__`` method accepts the value during runtime and validates it against configured rules.

For example, here's a trivial validator that only allows even or odd numbers as per setup:

.. code-block:: python

    class OddEvenValidator:
        def __init__(self, odd_or_even):
            self.is_even = odd_or_even=="EVEN"

        def __call__(self, value):
            if (self.is_even and value % 2 != 0) or (not self.is_even and value % 2 == 0):
                raise ValidationError(
                    {
                        'invalid': f"Value '{value}' is not {'Even' if self.is_even else 'Odd'}"
                    }
                )

    @domain.aggregate
    class HopScotch:
        step = Integer(validators=[OddEvenValidator("EVEN")])

Now assigning an odd value will result in a ``ValidationError``::

    >>> h1 = HopScotch(step=3)
    ValidationError                           Traceback (most recent call last)
    ...
    ValidationError: {'step': [{'invalid': 'Value '3' is not Even'}]}

.. |regex flags| raw:: html

    <a href="https://docs.python.org/3/library/re.html#contents-of-module-re" target="_blank">Regex Flags</a>
