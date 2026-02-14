# Value Objects

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


Value Objects represent distinct domain concepts, with attributes, behavior and
validations built into them. They don't have distinct identities, so they are
*identified* by attributes values. They tend to act primarily as data
containers, enclosing attributes of primitive types.

## Defining a Value Object

Consider the example of an Email Address. A User’s Email can be treated
as a simple “String.” If we do so, validations that check for the value
correctness (an email address) are either specified as part of the `User`
class' lifecycle methods or as independent business logic present in the
services layer.

But an Email is more than just another string in the system. It has
well-defined, explicit rules associated with it, like:

- The presence of an @ symbol
- A string with acceptable - characters (like . or _) before the @ symbol
- A valid domain URL right after the @ symbol
- The domain URL to be among the list of acceptable domains, if defined
- A total length of less 255 characters

So it makes better sense to make Email a Value Object, with a simple string
representation to the outer world, but having a distinct local_part (the part
of the email address before @) and domain_part (the domain part of the
address). Any value assignment will have to satisfy the domain rules listed
above.

Below is a sample implementation of the `Email` concept as a Value Object:

```python hl_lines="8-38 40-49"
{! docs_src/guides/domain-definition/009.py !}
```

The complex validation logic of an email address is elegantly encapsulated in a
validator class attached to the `Email` Value Object. Assigning an invalid
email address now throws an elegant `ValidationError`.

```shell
In [1]: Email(address="john.doe@gmail.com")
Out[1]: <Email: Email object ({'address': 'john.doe@gmail.com'})>

In [2]: Email(address="john.doegmail.com")
06:40:44,241 ERROR: defaultdict(<class 'list'>, {'address': ['Invalid email address']})
...
ValidationError: {'address': ['Invalid email address']}
```

`Email` is now a Value Object that can be used across your application.

!!!note
    This example was for illustration purposes only. It is far more elegant to
    validate an email address with [regex](https://emailregex.com/).

## Embedding Value Objects

Value Objects can be embedded into Aggregates and Entities with the
`ValueObject` field:

```python hl_lines="54"
{! docs_src/guides/domain-definition/009.py !}
```

!!!note
    You can also specify a Value Object's class name as input to the
    `ValueObject` field, which will be resolved when the domain is initialized.
    This can help avoid the problem of circular references.

    ```python
    @domain.aggregate
    class User:
       email = ValueObject("Email")
       name: String(max_length=30)
       timezone: String(max_length=30)
    ```

An email address can be supplied during user object creation, and the
value object takes care of its own validations.

```shell
...
In [1]: user = User(
   ...:     email_address='john.doe@gmail.com',
   ...:     name='John Doe',
   ...:     timezone='America/Los_Angeles'
   ...: )

In [2]: user.to_dict()
Out[2]: 
{'email': {'address': 'john.doe@gmail.com'},
 'name': 'John Doe',
 'timezone': 'America/Los_Angeles',
 'id': '9b03b7ff-ccfa-41f8-9467-b98588aa4302'}
```

Supplying an invalid email address throws a `ValidationError`:

```shell
In [3]: User(
   ...:     email_address='john.doegmail.com',
   ...:     name='John Doe',
   ...:     timezone='America/Los_Angeles'
   ...: )
ValidationError: {'email_address': ['Invalid email address']}
```

## Assigning Values

Value Objects are typically initialized along with the enclosing entity.

```python hl_lines="14"
{! docs_src/guides/domain-definition/010.py !}
```

Assigning value is straight-forward with a `Balance` object:

```shell
...
In [1]: account = Account(
   ...:     balance=Balance(currency="USD", amount=100.0),
   ...:     name="Checking"
   ...:     )

In [2]: account.to_dict()
Out[2]: 
{'balance': {'currency': 'USD', 'amount': 100.0},
 'name': 'Checking',
 'id': '74731f8b-a58e-4666-858b-b2e57e42ce68'}
```

It is also possible to initialize a Value Object by its attributes:

```shell
...
In [1]: account = Account(
   ...:     balance_currency = "USD",
   ...:     balance_amount = 100.0,
   ...:     name="Checking"
   ...:     )

In [2]: account.to_dict()
Out[2]: 
{'balance': {'currency': 'USD', 'amount': 100.0},
 'name': 'Checking',
 'id': 'a41a0ac9-9e6d-4300-96e3-054c70201e51'}
```

The attribute names are a combination of the field name defined in `Account`
class (`balance`) and the field names defined in the `Balance` Value Object
(`currency` and `amount`).

The resultant `Account` object would be the same in all aspects in either case.
But note that you can only assign by attributes when initializing an
entity. Trying to update an attribute value directly after initialization does
not work because Value Objects are immutable - they cannot be changed once
initialized. Read more in [Immutability](#immutability) section.

The approach of assigning an entirely new Value Object instead of editing
attributes also makes sense because all invariants (validations) should be
satisfied at all times.

!!!note
    It is recommended that you always deal with Value Objects by their class.
    Attributes are generally used by Protean during persistence and retrieval.

## Invariants

When a validation spans across multiple fields, you can specify it in an
`invariant` method. These methods are executed every time the value object is
initialized.

```python hl_lines="13-16"
{! docs_src/guides/domain-definition/012.py !}
```

```shell hl_lines="3"
In [1]: Balance(currency="USD", amount=-100)
...
ValidationError: {'balance': ['Balance cannot be negative for USD']}
```

Refer to [`invariants`](../domain-behavior/invariants.md) section for a
deeper explanation of invariants.

## Equality

Two value objects are considered to be equal if their values are equal.

```python
{! docs_src/guides/domain-definition/011.py !}
```

```shell
In [1]: bal1 = Balance(currency='USD', amount=100.0)

In [2]: bal2 = Balance(currency='USD', amount=100.0)

In [3]: bal3 = Balance(currency='CAD', amount=100.0)

In [4]: bal1 == bal2
Out[4]: True

In [5]: bal1 == bal3
Out[5]: False
```

## Identity

Unlike Aggregates and Entities, Value Objects do not have any inbuilt concept
of unique identities. This allows two instances of value objects to be swapped
or even be replaced by a single object instance.

This also means that all functionalities related to identity or uniqueness
are not applicable to Value Objects.

For example, trying to mark a Value Object field with `unique = True` or
`identifier = True` will throw a `IncorrectUsageError` exception.

<!-- FIXME Remove usage of `BaseValueObject` in the below code snippet -->
```shell
In [1]: from protean.fields import Float, String

In [2]: from protean.core.value_object import BaseValueObject

In [3]: class Balance(BaseValueObject):
   ...:     currency = String(max_length=3, unique=True)
   ...:     amount = Float()
...
IncorrectUsageError: "Value Objects cannot contain fields marked 'unique' (field 'currency')"
```

Same case if you try to find a Value Object's `id_field`:

```shell
In [4]: from protean.reflection import id_field

In [5]: id_field(Balance)
...
IncorrectUsageError: "<class '__main__.Balance'> does not have identity fields"
```

## Immutability

A Value Object cannot be altered once initialized. Trying to do so will throw a TypeError.

```shell
In [1]: bal1 = Balance(currency='USD', amount=100.0)

In [2]: bal1.currency = "CAD"
...
IncorrectUsageError: "Value Objects are immutable and cannot be modified once created"
```
