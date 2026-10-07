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

```python hl_lines="8-30 33-41"
--8<-- "guides/domain-definition/009.py:full"
```

The complex validation logic of an email address is contained in a
validator class attached to the `Email` Value Object. Assigning an invalid
email address now raises a `ValidationError`.

```shell
In [1]: Email(address="john.doe@gmail.com")
Out[1]: <Email: Email object ({'address': 'john.doe@gmail.com'})>

In [2]: Email(address="john.doegmail.com")
...
ValidationError: {'address': ['Invalid email address']}
```

`Email` is now a Value Object that can be used across your application.

!!!note
    This example was for illustration purposes only. It is better to
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

```python hl_lines="46"
--8<-- "guides/domain-definition/009.py:full"
```

!!!note
    You can also specify a Value Object's class name as input to the
    `ValueObject` field, which will be resolved when the domain is initialized.
    This can help avoid the problem of circular references.

    ```python
    --8<-- "guides/domain-definition/value-objects/001.py:aggregate"
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
{'name': 'John Doe',
 'timezone': 'America/Los_Angeles',
 'id': '9b03b7ff-ccfa-41f8-9467-b98588aa4302',
 'email': {'address': 'john.doe@gmail.com'},
 '_version': -1}
```

Supplying an invalid email address throws a `ValidationError`:

```shell
In [3]: User(
   ...:     email_address='john.doegmail.com',
   ...:     name='John Doe',
   ...:     timezone='America/Los_Angeles'
   ...: )
ValidationError: {'address': ['Invalid email address']}
```

## Assigning Values

Value Objects are typically initialized along with the enclosing entity.

```python hl_lines="20"
--8<-- "guides/domain-definition/010.py:full"
```

`Balance` holds money, so `amount` is a `Decimal` field. The examples import
Python's `decimal.Decimal` as `D` so it does not clash with the field of the
same name: `from decimal import Decimal as D`.

Assigning value is straight-forward with a `Balance` object:

```shell
...
In [1]: account = Account(
   ...:     balance=Balance(currency="USD", amount=D("100.00")),
   ...:     name="Checking"
   ...:     )

In [2]: account.to_dict()
Out[2]:
{'name': 'Checking',
 'id': '74731f8b-a58e-4666-858b-b2e57e42ce68',
 'balance': {'currency': 'USD', 'amount': '100.00'},
 '_version': -1}
```

It is also possible to initialize a Value Object by its attributes:

```shell
...
In [1]: account = Account(
   ...:     balance_currency="USD",
   ...:     balance_amount=D("100.00"),
   ...:     name="Checking"
   ...:     )

In [2]: account.to_dict()
Out[2]:
{'name': 'Checking',
 'id': 'a41a0ac9-9e6d-4300-96e3-054c70201e51',
 'balance': {'currency': 'USD', 'amount': '100.00'},
 '_version': -1}
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
--8<-- "guides/domain-definition/value-objects/002.py:value_objects"
```

When a value object is embedded in an aggregate, its fields are flattened
one level for persistence. Each column name joins the aggregate's field name
and the value object's field name with an underscore. A nested value object
is not flattened further: it is stored whole in one column.

| Aggregate field | VO field | Database column |
|---|---|---|
| `address` | `street` | `address_street` |
| `address` | `city` | `address_city` |
| `address` | `zip_code` | `address_zip_code` |
| `address` | `location` | `address_location` (the whole `GeoLocation`) |

Build a nested value object and pass it in:

```python
--8<-- "guides/domain-definition/value-objects/002.py:nested"
```

The aggregate also accepts the flattened names from the table, one level
deep. A nested value object is still passed as an object. Deeper names such
as `address_location_latitude` are rejected with a `ValidationError`:

```python
--8<-- "guides/domain-definition/value-objects/002.py:flattened"
```

## Dict-Based Initialization

Value objects can be initialized from dictionaries, which is especially
useful when receiving data from APIs or external sources:

```python
--8<-- "guides/domain-definition/value-objects/003.py:dict"
```

This works for nested value objects too, any dict matching the value object's
field structure will be automatically converted.

## Invariants

When a validation spans across multiple fields, you can specify it in an
`invariant` method. These methods are executed every time the value object is
initialized.

```python hl_lines="13-16"
--8<-- "guides/domain-definition/012.py:full"
```

```shell hl_lines="3"
In [1]: Balance(currency="USD", amount=D("-100.00"))
...
ValidationError: {'balance': ['Balance cannot be negative for USD']}
```

### Field Validators vs. Invariants

Protean offers two ways to validate value object data:

- **Field-level `validators`**: Callable validators attached to individual
  fields (e.g. `validators=[EmailValidator()]`). Use these for single-field
  format validation, "is this a valid email?" or "is this a valid phone
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
--8<-- "guides/domain-definition/value-objects/004.py:value_object"
```

`defaults()` runs during initialization, after all field values have been
set but before invariants are checked.

## Equality

Two value objects are considered to be equal if their values are equal.

```python
--8<-- "guides/domain-definition/011.py:full"
```

```shell
In [1]: bal1 = Balance(currency='USD', amount=D('100.00'))

In [2]: bal2 = Balance(currency='USD', amount=D('100.00'))

In [3]: bal3 = Balance(currency='CAD', amount=D('100.00'))

In [4]: bal1 == bal2
Out[4]: True

In [5]: bal1 == bal3
Out[5]: False
```

Value objects compare their `to_dict()` output, where a `Decimal` becomes its
string. `D('100.0')` and `D('100.00')` are equal numbers, but a `Balance`
holding one does not equal a `Balance` holding the other. Quantize amounts to
the field's scale before you compare them.

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
   ...:     amount = Decimal(precision=19, scale=4)
...
IncorrectUsageError: "Value Objects cannot contain fields marked 'unique' (field 'currency')"
```

A Value Object also has no `id_field`. Asking for it returns `None`:

```shell
In [4]: from protean.utils.reflection import id_field

In [5]: id_field(Balance) is None
Out[5]: True
```

## Immutability

A Value Object cannot be altered once initialized. Trying to do so raises an
`IncorrectUsageError`.

```shell
In [1]: bal1 = Balance(currency='USD', amount=D('100.00'))

In [2]: bal1.currency = "CAD"
...
IncorrectUsageError: "Value Objects are immutable and cannot be modified once created"
```

## Replacing Fields

Since value objects are immutable, you cannot modify them after creation.
Instead, use `replace()` to create a new instance with selected fields
changed, similar to `dataclasses.replace()`:

```python
--8<-- "guides/domain-definition/value-objects/005.py:replace"
```

`replace()` copies all current field values, overlays the provided keyword
arguments, and constructs a new instance of the same class. Invariants are
re-validated on the new instance, so invalid replacements are rejected. Here
`Balance` is the version from [Invariants](#invariants), which rejects negative
USD amounts:

```python
--8<-- "guides/domain-definition/012.py:full"

--8<-- "guides/domain-definition/value-objects/006.py:replace"
```

Passing `field=None` explicitly sets the field to `None`. It does not keep the
old value. Only omitted fields retain their original values:

```python
--8<-- "guides/domain-definition/value-objects/007.py:replace"
```

Unknown field names raise `IncorrectUsageError`:

```python
--8<-- "guides/domain-definition/value-objects/006.py:unknown"
```

`replace()` also works with nested value objects. Pass a new value object
instance for the nested field, or omit it to preserve the original.

## Hashability

Because value objects are immutable and define equality by their attributes,
they are hashable by default. This means you can use them as dictionary
keys or in sets:

```python
--8<-- "guides/domain-definition/value-objects/008.py:hash"
```

## Projecting Entities into Value Objects

When building commands and events, you often need a value object that
mirrors an entity's fields, for example, to carry `OrderItem` data in a `PlaceOrder` command.
Manually duplicating the fields is tedious and error-prone. Protean provides
`value_object_from_entity()` to auto-generate the VO class:

```python
--8<-- "guides/domain-definition/value-objects/009.py:derive"
```

The generated `OrderItemVO` has the same fields as `OrderItem`, with these
adjustments:

- **Identity fields become optional**: Identifier and unique fields are
  made optional with `None` defaults, since identity is not a value concern.
- **`Reference` fields are excluded**: Foreign key references are
  infrastructure concerns, not domain values.
- **`HasOne`/`HasMany` associations are recursively converted**: Child
  entities become nested value objects or lists of value objects.
- **Private fields (prefixed with `_`) are skipped.**
- **Field constraints are not copied**: each field keeps its type and
  default, but options such as `max_length` are left behind.

You can customize the generated class name and exclude specific fields:

```python
--8<-- "guides/domain-definition/value-objects/009.py:custom"
```

### Inline field descriptor

For inline use in commands and events, use the `ValueObjectFromEntity`
field descriptor instead of calling the function separately:

```python
--8<-- "guides/domain-definition/value-objects/009.py:command"
```

This derives the VO class from the entity at class-body evaluation time, no
separate variable needed.

### Round-trip: VO back to Entity

To convert a value object back into an entity instance (e.g., in a command
handler), use the `from_value_object()` classmethod on the entity:

```python
--8<-- "guides/domain-definition/value-objects/009.py:handler"
```

`from_value_object()` calls `vo.to_dict()`, strips `None` values for
identifier/unique fields (so auto-generated defaults kick in), and
constructs the entity. This is the inverse of `value_object_from_entity()`.

### Fact event refactoring

Protean's fact event generation internally uses `value_object_from_entity()`
to convert entity associations in aggregates. If your aggregate has
`fact_events=True` and contains `HasOne`/`HasMany` entity associations,
the generated fact event automatically includes value object projections
of those entities.

## Common Errors

| Exception | When it occurs |
|---|---|
| `ValidationError` | Field validation fails during construction (e.g. missing `required` field, invalid format). Contains a `messages` dict. |
| `ValidationError` | An `@invariant.post` check raises a validation error (e.g. "balance cannot be negative for USD"). |
| `IncorrectUsageError` | Trying to modify a value object attribute after creation (value objects are immutable). Use `replace()` instead. |
| `IncorrectUsageError` | Passing an unknown field name to `replace()`. |
| `IncorrectUsageError` | Defining a field with `unique=True` or `identifier=True`, value objects have no concept of identity. |

---

!!! tip "See also"
    **Concept overview:** [Value Objects](../../concepts/building-blocks/value-objects.md): Immutable objects defined by their attributes, not identity.

    **Decision guidance:** [Choosing Element Types](../../concepts/building-blocks/choosing-element-types.md): When to use a value object vs. an entity.

    **Patterns:**

    - [Replace Primitives with Value Objects](../../patterns/replace-primitives-with-value-objects.md): When and why to wrap raw types in domain-specific value objects.
    - [Validation Layering](../../patterns/validation-layering.md): Where value object validation fits in the overall validation strategy.
    - [Fact Events as Integration Contracts](../../patterns/fact-events-as-integration-contracts.md): How fact events use entity-to-VO projection for cross-context state transfer.
