# Fields

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Fields are the attributes you declare on aggregates, entities, value objects,
commands, and events. They define what data an element carries, which values
are valid, how defaults are supplied, and how relationships are expressed.

This guide walks through the everyday task of **putting fields on a domain
element**: picking the right type, making them required, giving them
defaults, constraining values, and hooking up relationships. For the full
list of field types and every argument they accept, see the
[Fields Reference](../../reference/fields/index.md).

## Declaring a field

Fields are declared inside a domain element using one of Protean's field
functions — `String`, `Integer`, `Float`, `DateTime`, `List`, and so on.
The recommended form is an annotation:

```python
from protean import Domain
from protean.fields import String, Float, DateTime

domain = Domain()

@domain.aggregate
class Product:
    name: String(max_length=100, required=True)
    price: Float(min_value=0)
    created_at: DateTime(default="utc_now")
```

You can also assign fields as class attributes (`name = String(...)`) — the
two styles are interchangeable and can be mixed freely. A third escape
hatch lets you use raw Pydantic annotations when you need more control.

See [Defining Fields](../../reference/fields/defining-fields.md) for the
differences between styles and a caveat about
`from __future__ import annotations`.

---

## Choosing a field type

Protean groups field types into three families. Pick from the family that
matches the shape of the data you're modeling:

| You need to store...                                   | Use a... |
|---|---|
| A primitive value (string, number, date, boolean, id)   | [Simple field](../../reference/fields/simple-fields.md) |
| A list, dict, or embedded value object                 | [Container field](../../reference/fields/container-fields.md) |
| A relationship to another entity or aggregate          | [Association field](../../reference/fields/association-fields.md) |

A typical aggregate uses all three:

```python
from protean.fields import String, Float, DateTime, List, HasMany

@domain.aggregate
class Order:
    customer_name: String(max_length=100, required=True)   # simple
    placed_at: DateTime(default="utc_now")                 # simple
    tags: List(content_type=String)                        # container
    items = HasMany("LineItem")                            # association
```

Lifecycle state gets its own type — use [`Status`](../../reference/fields/simple-fields.md#status)
when the value must move through a defined state machine. See the
[Status Transitions](../domain-behavior/status-transitions.md) guide for
patterns like `atomic_change` and event-sourced flows.

---

## Making a field required

By default, every field is optional. Mark a field `required=True` to
reject construction when the value is missing or blank:

```python
@domain.aggregate
class Customer:
    email: String(required=True)
    name: String(max_length=100)
```

Attempting to build a `Customer` without an email raises a
`ValidationError` with a `messages` dict pointing at the offending field:

```shell
In [1]: Customer(name="Jane Doe")
...
ValidationError: {'email': ['is required']}
```

Identifier fields are an exception — they are auto-generated when you
don't provide one. See [Identity](../../reference/domain-elements/identity.md)
for how identity generation is configured.

---

## Setting defaults

Use `default` for a literal value or a callable that produces one. Call
the callable (don't invoke it yourself) so Protean can evaluate it at
construction time:

```python
from datetime import datetime, timezone

def _utc_now():
    return datetime.now(timezone.utc)

@domain.aggregate
class ShoppingCart:
    created_at: DateTime(default=_utc_now)
    currency: String(default="USD")
```

!!! warning "Don't use mutable defaults"
    Passing a list, dict, set, or entity instance as `default=` shares a
    single object across every instance of the aggregate. Wrap the value
    in a callable instead:

    ```python
    # Wrong — every Customer shares the same list
    tags: List(default=[])

    # Right — each Customer gets a fresh list
    tags: List(default=list)
    ```

When a default needs to reference other field values (e.g. `total =
subtotal * (1 + tax_rate)`), override the aggregate's
[`defaults()` hook](./aggregates.md#the-defaults-hook) rather than
computing the value in `default=`.

---

## Constraining values

Most field types accept constraints as arguments. The common ones:

```python
from protean.fields import String, Integer, Float

@domain.aggregate
class Listing:
    title: String(max_length=200, min_length=3)           # length bounds
    priority: Integer(min_value=1, max_value=5)           # numeric bounds
    discount: Float(min_value=0, max_value=1)
    status: String(choices=["DRAFT", "PUBLISHED", "SOLD"]) # enumerated
```

`choices` also accepts an `Enum` class, which is the preferred form when
the set of values is reused across the domain. See the
[Arguments reference](../../reference/fields/arguments.md) for the full
list of options.

### Enforcing uniqueness

Add `unique=True` to require that no two aggregates share the same value
for a field. Uniqueness is enforced by the underlying persistence store
when the aggregate is saved:

```python
@domain.aggregate
class User:
    email: String(required=True, unique=True)
    name: String(max_length=100)
```

---

## Adding custom validation

For single-field format checks that go beyond length or numeric bounds —
email addresses, phone numbers, SKUs — pass a callable to `validators`:

```python
from protean.fields import String
from protean.exceptions import ValidationError

class EmailDomainValidator:
    def __init__(self, allowed_domain: str):
        self.allowed_domain = allowed_domain

    def __call__(self, value: str) -> None:
        if not value.endswith(f"@{self.allowed_domain}"):
            raise ValidationError(
                f"Email does not belong to {self.allowed_domain}"
            )

@domain.aggregate
class Employee:
    email: String(validators=[EmailDomainValidator("mydomain.com")])
```

Validators run on every assignment and raise `ValidationError` if the
value is rejected.

!!! tip "Single field vs. cross-field rules"
    Use `validators` when the rule involves **one field in isolation**.
    When a rule spans multiple fields — "shipping date must be after
    order date", "balance cannot go negative for USD" — express it as
    an [invariant](../domain-behavior/invariants.md) on the aggregate or
    value object instead.

---

## Expressing relationships

Associations connect aggregates to the entities they own and let entities
reference their parent aggregate. Use the association field that matches
the cardinality you need:

- `HasOne` — the aggregate owns exactly one child entity.
- `HasMany` — the aggregate owns zero or more child entities.
- `Reference` — the inverse link from a child entity back to its
  aggregate (Protean adds this automatically when you define `HasOne` or
  `HasMany`).

```python
from protean.fields import HasMany

@domain.aggregate
class Post:
    title: String(max_length=200, required=True)
    comments = HasMany("Comment")

@domain.entity(part_of=Post)
class Comment:
    content: String(max_length=500)
```

Aggregates never reference each other directly — cross-aggregate links
are modeled as `Identifier` fields. See
[Expressing Relationships](./relationships.md) for the full treatment,
including bidirectional navigation, `via`, and shadow fields.

---

## Embedding value objects

When a group of fields always travels together and represents a single
concept (money, an address, a coordinate), promote them to a
[value object](./value-objects.md) and embed it with `ValueObject`:

```python
from protean.fields import ValueObject

@domain.value_object
class Money:
    currency: String(max_length=3, required=True)
    amount: Float(min_value=0, required=True)

@domain.aggregate
class Account:
    owner: String(max_length=100, required=True)
    balance = ValueObject(Money)
```

You can hand in a `Money(...)` instance or the flattened attributes
(`balance_currency`, `balance_amount`) — Protean reconstitutes the VO in
either case.

---

## Mapping to a different storage name

Use `referenced_as` when the persisted column or document key needs to
differ from the Python attribute name — typically when matching an
existing database schema:

```python
@domain.aggregate
class Person:
    name: String(required=True, referenced_as="full_name")
    email: String()
```

The attribute on the aggregate stays `name`, but the persisted field is
`full_name`. This is a persistence-layer concern only; domain code never
sees the `referenced_as` name.

---

## Introspecting fields

To see what's declared on an element — during debugging, or inside a
custom behaviour — use the helpers in `protean.utils.reflection`:

```shell
In [1]: from protean.utils.reflection import declared_fields

In [2]: declared_fields(Post)
Out[2]:
{'title': String(max_length=200, required=True),
 'comments': HasMany('Comment'),
 'id': Auto(identifier=True)}
```

`attributes()` additionally exposes shadow fields such as the foreign
key columns that `HasMany` and `Reference` create behind the scenes.

---

## Common errors

| Exception | When it occurs |
|---|---|
| `ValidationError` | A `required` field is missing, a length/numeric bound is violated, or a value isn't in the declared `choices`. Contains a `messages` dict keyed by field name. |
| `ValidationError` | A custom `validators` callable raises it. The message from the validator is preserved. |
| `ValidationError` | A `unique` field collides with an existing record at persistence time. |
| `IncorrectUsageError` | A value object field is marked `unique=True` or `identifier=True` — value objects have no concept of identity. |
| Silent mis-declaration | `from __future__ import annotations` is active and the annotation style is used — the `FieldSpec` is treated as a string. Use assignment style instead. See [Defining Fields](../../reference/fields/defining-fields.md#known-limitation-from-__future__-import-annotations). |

---

!!! tip "See also"
    **Reference:**

    - [Fields Overview](../../reference/fields/index.md) — All field types and options.
    - [Common Arguments](../../reference/fields/arguments.md) — `required`, `default`, `choices`, `unique`, `validators`, `referenced_as`, and more.
    - [Simple Fields](../../reference/fields/simple-fields.md), [Container Fields](../../reference/fields/container-fields.md), [Association Fields](../../reference/fields/association-fields.md) — Per-type specs.

    **Related guides:**

    - [Expressing Relationships](./relationships.md) — `HasOne`, `HasMany`, `Reference`, `via`, and shadow fields.
    - [Value Objects](./value-objects.md) — Immutable, attribute-identified types.
    - [Validations](../domain-behavior/validations.md) and [Invariants](../domain-behavior/invariants.md) — Single-field vs. cross-field rules.
    - [Status Transitions](../domain-behavior/status-transitions.md) — Enforced lifecycle states with the `Status` field.

    **Explanation:**

    - [Field system internals](../../concepts/internals/field-system.md) — How Protean resolves field declarations and integrates with Pydantic.
