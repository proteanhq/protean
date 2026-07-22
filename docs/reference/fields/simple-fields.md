# Simple Fields

!!! abstract "Applies to: DDD · CQRS · Event Sourcing"


## String

A string field, for small- to large-sized strings. For large amounts of text,
use [Text](#text).

```python hl_lines="9"
--8<-- "guides/domain-definition/fields/simple-fields/001.py:full"
```

**Optional Arguments**

- **`max_length`**: The maximum length (in characters) of the field.
Defaults to 255.
- **`min_length`**: The minimum length (in characters) of the field.
Defaults to `None` (no minimum).
- **`sanitize`**: Optionally turn off HTML sanitization. Default is `True`.

## Text

A large text field, to hold large amounts of text. Text fields do not have
size constraints.

```python hl_lines="10"
--8<-- "guides/domain-definition/fields/simple-fields/002.py:full"
```

**Optional Arguments**

- **`sanitize`**: Optionally turn off HTML sanitization. Default is `True`.

## Integer

An integer.

```python hl_lines="10"
--8<-- "guides/domain-definition/fields/simple-fields/003.py:full"
```

**Optional Arguments**

- **`max_value`**: The maximum numeric value of the field.
- **`min_value`**: The minimum numeric value of the field.

## Float

A floating-point number represented in Python by a float instance.

```python hl_lines="10"
--8<-- "guides/domain-definition/fields/simple-fields/004.py:full"
```

**Optional Arguments**

- **`max_value`**: The maximum numeric value of the field.
- **`min_value`**: The minimum numeric value of the field.

## Decimal

An exact decimal number, represented in Python by a `decimal.Decimal` instance.
Prefer this over `Float` for money and other values where binary floating-point
rounding is unacceptable. With `precision`/`scale` it is fixed-precision;
without them it is arbitrary-precision where the backend supports it.

```python
from protean.fields import Decimal


@domain.aggregate
class Product:
    price = Decimal(precision=19, scale=4, min_value=0)
```

On SQL providers the field maps to `NUMERIC(precision, scale)`; values are
string-encoded in JSON and event payloads, so they never round-trip through a
binary float and lose precision.

**Optional Arguments**

- **`precision`**: Total number of digits. Maps to `NUMERIC` precision and
  Pydantic `max_digits`.
- **`scale`**: Number of digits after the decimal point. Maps to `NUMERIC`
  scale and Pydantic `decimal_places`.
- **`max_value`**: The maximum numeric value of the field.
- **`min_value`**: The minimum numeric value of the field.

## Date

A date, represented in Python by a `datetime.date` instance.

```python hl_lines="12"
--8<-- "guides/domain-definition/fields/simple-fields/005.py:full"
```

```shell hl_lines="6"
In [1]: p = Post(title="It")

In [2]: p.to_dict()
Out[2]:
{'title': 'It',
 'published_on': '2024-05-09',
 'id': '88a21815-7d9b-4138-9cac-5a06889d4318'}
```

Protean will intelligently convert a valid date string into a date object, with
the help of the venerable
[`dateutil`](https://dateutil.readthedocs.io/en/stable/) module.

```shell
In [1]: post = Post(title='Foo', published_on="2020-01-01")

In [2]: post.to_dict()
Out[2]:
{'title': 'Foo',
 'published_on': '2020-01-01',
 'id': 'ffcb3b26-71f0-45d0-8ca0-b71a9603f792'}

In [3]: Post(title='Foo', published_on="2019-02-29")
ERROR: Error during initialization: {'published_on': ['"2019-02-29" has an invalid date format.']}
...
ValidationError: {'published_on': ['"2019-02-29" has an invalid date format.']}
```


## DateTime

A date and time, represented in Python by a `datetime.datetime` instance.

```python hl_lines="12"
--8<-- "guides/domain-definition/fields/simple-fields/006.py:full"
```

```shell
In [1]: p = Post(title="It")

In [2]: p.to_dict()
Out[2]:
{'title': 'It',
 'created_at': '2024-05-09 17:12:11.373300+00:00',
 'id': '3a96e434-06ab-4244-80a8-76edbd621a27'}
```

### Auto-populated timestamps

`DateTime` and `Date` support two Django-parity flags that let the persistence
layer stamp the field on save:

- **`auto_now_add=True`** — set to the current UTC time on the **create** save,
  then never touched again. Use it for `created_at`.
- **`auto_now=True`** — set to the current UTC time on **every** save (create and
  update). Use it for `updated_at`.

```python
from protean.fields import DateTime, String

@domain.aggregate
class Article:
    title: String(max_length=100)
    created_at: DateTime(auto_now_add=True)
    updated_at: DateTime(auto_now=True)
```

The two flags are mutually exclusive, are only valid on `DateTime`/`Date`
fields, and cannot be combined with `required=True` (the value is filled at save
time, so the field must be optional). Unlike a construction-time
`default=utc_now`, an `auto_now*` field is `None` until the first save — the
value is stamped on the `repository.add()` → save path, not at construction and
not on a bulk `query.update()` (matching Django's `Model.save()` vs
`QuerySet.update()` behavior).

See [Track Audit and Lifecycle Fields](../../patterns/track-audit-fields.md) for
the full recipe (abstract base + timestamps + `created_by`/`updated_by`).

## Boolean

A `True`/`False` field.

```python hl_lines="10"
--8<-- "guides/domain-definition/fields/simple-fields/007.py:full"
```

```shell hl_lines="6"
In [1]: u = User(name="John Doe")

In [2]: u.to_dict()
Out[2]:
{'name': 'John Doe',
 'subscribed': False,
 'id': '69190dd4-12a6-4666-a799-9409ddab39cd'}
```

## Auto

Automatically-generated unique identifiers.

`Auto` field values are auto-generated unless explicitly supplied. This is the
primary difference between `Auto` and `Identifier` fields. Since they are
always auto-generated, `Auto` fields cannot be marked `required=True`.

**Optional Arguments**

- **`increment`**: Auto-increment field value. Defaults to `False`. If set, the
value is expected to be generated by the database at the time of persistence.

!!!note
    It is necessary for the underlying persistence store to support this
    `increment` feature. You have to set up the database schema accordingly.
    Cross-check with the specific adapter's documentation and your database
    to confirm if the database supports this functionality.

- **`identity_strategy`**: The strategy to use to generate an identity value.
If not provided, the strategy defined at the domain level is used.

- **`identity_function`**: A function that is used to generate the identity
value. If not provided, the function defined at the domain level is used.

- **`identity_type`**: The type of the identity value. If not provided, the
type defined at the domain level is used.

The identity params are useful when constructing an entity whose identity
schema differs from the default.

By default, all entities and aggregates create an `Auto` field named `id`
that represents their unique identifier.

```python hl_lines="9"
--8<-- "guides/domain-definition/fields/simple-fields/001.py:full"
```

```shell hl_lines="4 11"
In [1]: declared_fields(Person)
Out[1]:
{'name': String(required=True, max_length=50, min_length=2),
 'id': Auto(identifier=True)}

In [2]: p = Person(name='John Doe')

In [3]: p.to_dict()
Out[3]:
{'name': 'John Doe',
 'id': '7d32e929-e5c5-4856-a6e7-1ebf12e6259e'}
```

Identity values are UUIDs by default. You can customize this behavior with
`identity_strategy` and `identity_type` [config attributes](../configuration/index.md#identity_strategy).

The [Identity](../domain-elements/identity.md) section deep dives into identities in Protean.

## Identifier

An Identifier. The identity type is String type by default, but can be changed
with `identity_type` configuration attribute for all entities, or can be set
per entity with the `identity_type` parameter.

**Optional Arguments**

- **`identity_type`**: The type of the identifier field. If not provided, it
will be picked from the domain configuration. Defaults to `STRING`. Raises
`ValidationError` if the provided identity type is not supported.

```python hl_lines="14"
--8<-- "guides/domain-definition/fields/simple-fields/008.py:full"
```

```shell hl_lines="4"
In [1]: user = User(user_id=1, name="John Doe")

In [2]: user.to_dict()
Out[2]: {'user_id': 1, 'name': 'John Doe', 'subscribed': False}
```

Refer to [Identity](../domain-elements/identity.md) section for a deep dive into identities
in Protean.

## Status

A status field for modeling aggregate lifecycle states with enforced transitions.
Requires an Enum class as the first argument. Valid values are the Enum members'
`value` attributes.

```python
from enum import Enum
from protean.fields import Status

class OrderStatus(Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"

@domain.aggregate
class Order:
    status = Status(OrderStatus, default="DRAFT")
```

Without `transitions`, `Status` behaves like `String(choices=Enum)` — it constrains
values but does not enforce transition rules.

### Enforcing transitions

Pass a `transitions` dict mapping each state to its allowed next states:

```python
@domain.aggregate
class Order:
    status = Status(OrderStatus, default="DRAFT", transitions={
        OrderStatus.DRAFT: [OrderStatus.PLACED, OrderStatus.CANCELLED],
        OrderStatus.PLACED: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
        OrderStatus.CONFIRMED: [OrderStatus.SHIPPED],
        OrderStatus.SHIPPED: [OrderStatus.DELIVERED],
        # DELIVERED and CANCELLED are terminal — absent from keys
    })
```

States not appearing as keys in the transitions dict are **terminal states** — no
outgoing transitions are allowed from them.

Same-value assignments are also validated against the map. To make a state
**idempotent** (self-transition allowed), include it in its own target list:

```python
OrderStatus.CANCELLED: [OrderStatus.CANCELLED],  # cancel() is idempotent
```

```shell hl_lines="6 11"
In [1]: order = Order()

In [2]: order.status = "PLACED"  # DRAFT → PLACED: allowed

In [3]: order.status = "SHIPPED"
ERROR: ...
ValidationError: {'status': ["Invalid status transition from 'PLACED' to 'SHIPPED'. Allowed transitions: CONFIRMED, CANCELLED"]}
```

### Programmatic checking

Use `can_transition_to()` to check whether a transition is valid without raising:

```python
order.can_transition_to("status", OrderStatus.SHIPPED)  # False
order.can_transition_to("status", OrderStatus.CONFIRMED)  # True
```

**Optional Arguments**

- **`transitions`**: A dict mapping each status to a list of allowed target
statuses. When provided, the framework prevents illegal transitions. Accepts
both Enum members and raw strings as keys/values. A state must list itself
as a target to allow idempotent self-transitions.

Refer to the [Status Transitions](../../guides/domain-behavior/status-transitions.md)
guide for detailed usage patterns including `atomic_change` and event-sourced
aggregates.
