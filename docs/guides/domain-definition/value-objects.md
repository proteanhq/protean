# Value Objects

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

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
--8<-- "guides/domain-definition/009.py:full"
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

## Configuration

A value object's behavior can be customized by passing options to the
`@domain.value_object` decorator.

### `abstract`

Marks a value object as abstract if `True`. Abstract value objects cannot be
instantiated and are meant to be subclassed. Useful for defining shared
fields across multiple concrete value object types.

### `part_of`

Associates the value object with a specific aggregate. While optional,
setting `part_of` registers the value object within the aggregate's cluster
and ensures it participates in the aggregate's validation lifecycle.

## Embedding Value Objects

Value Objects can be embedded into Aggregates and Entities with the
`ValueObject` field:

```python hl_lines="54"
--8<-- "guides/domain-definition/009.py:full"
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
--8<-- "guides/domain-definition/010.py:full"
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

## Nested Value Objects

Value objects can be composed of other value objects, forming richer domain
concepts:

```python
@domain.value_object
class GeoLocation:
    latitude: Float(required=True)
    longitude: Float(required=True)

@domain.value_object
class Address:
    street: String(max_length=200)
    city: String(max_length=100)
    zip_code: String(max_length=10)
    location = ValueObject(GeoLocation)
```

When embedded in an aggregate, nested value objects are flattened for
persistence. The database columns follow a naming convention that
concatenates field names with underscores:

| Aggregate field | VO field | Nested VO field | Database column |
|---|---|---|---|
| `address` | `street` | — | `address_street` |
| `address` | `location` | `latitude` | `address_location_latitude` |
| `address` | `location` | `longitude` | `address_location_longitude` |

You can initialize nested value objects by passing the inner object
directly or by using flattened attribute names:

```python
# Using nested objects
store = Store(
    name="Downtown",
    address=Address(
        street="123 Main St",
        city="Springfield",
        zip_code="62701",
        location=GeoLocation(latitude=39.78, longitude=-89.65),
    )
)

# Using flattened attributes (equivalent)
store = Store(
    name="Downtown",
    address_street="123 Main St",
    address_city="Springfield",
    address_zip_code="62701",
    address_location_latitude=39.78,
    address_location_longitude=-89.65,
)
```

## Dict-Based Initialization

Value objects can be initialized from dictionaries, which is especially
useful when receiving data from APIs or external sources:

```python
account = Account(
    balance={"currency": "USD", "amount": 100.0},
    name="Checking"
)
# Protean auto-converts the dict to a Balance value object
```

This works for nested value objects too — any dict matching the value
object's field structure will be automatically converted.

## Invariants

When a validation spans across multiple fields, you can specify it in an
`invariant` method. These methods are executed every time the value object is
initialized.

```python hl_lines="13-16"
--8<-- "guides/domain-definition/012.py:full"
```

```shell hl_lines="3"
In [1]: Balance(currency="USD", amount=-100)
...
ValidationError: {'balance': ['Balance cannot be negative for USD']}
```

### Field Validators vs. Invariants

Protean offers two ways to validate value object data:

- **Field-level `validators`**: Callable validators attached to individual
  fields (e.g. `validators=[EmailValidator()]`). Use these for single-field
  format validation — "is this a valid email?" or "is this a valid phone
  number?"
- **`@invariant.post` methods**: Cross-field business rules that span
  multiple attributes (e.g. "balance cannot be negative for USD"). Use
  these when validation depends on the combination of two or more fields.

As a rule of thumb: if the rule involves only one field, use a field
validator; if it involves multiple fields, use an invariant.

Refer to the [Invariants](../domain-behavior/invariants.md) guide for a
deeper explanation, and [Validation Layering](../../patterns/validation-layering.md)
for the overall strategy.

## The `defaults()` Hook

Override the `defaults()` method when a value object attribute's default
depends on other attribute values:

```python
@domain.value_object
class Duration:
    start: DateTime(required=True)
    end: DateTime(required=True)
    total_seconds: Float()

    def defaults(self):
        if self.total_seconds is None and self.start and self.end:
            self.total_seconds = (self.end - self.start).total_seconds()
```

`defaults()` runs during initialization, after all field values have been
set but before invariants are checked.

## Equality

Two value objects are considered to be equal if their values are equal.

```python
--8<-- "guides/domain-definition/011.py:full"
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

```shell
In [1]: @domain.value_object
   ...: class Balance:
   ...:     currency = String(max_length=3, unique=True)
   ...:     amount = Float()
...
IncorrectUsageError: "Value Objects cannot contain fields marked 'unique' (field 'currency')"
```

Same case if you try to find a Value Object's `id_field`:

```shell
In [4]: from protean.utils.reflection import id_field

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

## Hashability

Because value objects are immutable and define equality by their attributes,
they are hashable by default. This means you can use them as dictionary
keys or in sets:

```python
prices = {
    Balance(currency="USD", amount=9.99): "budget",
    Balance(currency="USD", amount=99.99): "premium",
}

unique_emails = {Email(address="a@b.com"), Email(address="c@d.com")}
```

## Common Errors

| Exception | When it occurs |
|---|---|
| `ValidationError` | Field validation fails during construction (e.g. missing `required` field, invalid format). Contains a `messages` dict. |
| `ValidationError` | An `@invariant.post` check raises a validation error (e.g. "balance cannot be negative for USD"). |
| `IncorrectUsageError` | Trying to modify a value object attribute after creation (value objects are immutable). |
| `IncorrectUsageError` | Defining a field with `unique=True` or `identifier=True` — value objects have no concept of identity. |

---

!!! tip "See also"
    **Concept overview:** [Value Objects](../../concepts/building-blocks/value-objects.md) — Immutable objects defined by their attributes, not identity.

    **Decision guidance:** [Choosing Element Types](../../concepts/building-blocks/choosing-element-types.md) — When to use a value object vs. an entity.

    **Patterns:**

    - [Replace Primitives with Value Objects](../../patterns/replace-primitives-with-value-objects.md) — When and why to wrap raw types in domain-specific value objects.
    - [Validation Layering](../../patterns/validation-layering.md) — Where value object validation fits in the overall validation strategy.
