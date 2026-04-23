# Identity

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Every aggregate and entity in Protean has a unique identity that is
generated at construction time, before the object is ever persisted.
This guide walks through the everyday tasks around identity: accepting
the defaults, naming the identifier field, choosing a different type,
plugging in a custom generator, and using natural keys supplied by your
users.

For the design rationale — why identity is generated on construction and
why composite keys aren't supported — see
[Identity](../../concepts/foundations/identity.md) and the
[Creating Identities Early](../../patterns/creating-identities-early.md)
pattern.

## Accept the defaults

If you don't declare an identifier field, Protean adds one for you. It's
an `Auto` field named `id`, generated as a UUID rendered as a string:

```python
from protean import Domain
from protean.fields import String

domain = Domain()

@domain.aggregate
class Customer:
    name: String(max_length=100, required=True)
```

```shell
In [1]: customer = Customer(name="Jane Doe")

In [2]: customer.to_dict()
Out[2]: {'name': 'Jane Doe', 'id': '9cf4ddc4-2919-4021-bd1a-c8083b5fdda7'}
```

This is the right choice for most aggregates: UUIDs are globally unique,
can be generated without coordination, and are safe to reference across
aggregates, events, and bounded contexts.

---

## Name the identifier field

When you want the identifier to have a domain-meaningful name, declare
it explicitly with `Auto(identifier=True)`:

```python
from protean.fields import Auto, String

@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    name: String(required=True)
```

```shell
In [1]: user = User(name="John Doe")

In [2]: user.to_dict()
Out[2]: {'user_id': '9cf4ddc4-2919-4021-bd1a-c8083b5fdda7', 'name': 'John Doe'}
```

The default `id` field is dropped once you declare your own identifier.

!!! note "Only one identifier per aggregate"
    Protean does not support composite keys. Declaring more than one
    field with `identifier=True` raises `NotSupportedError`. If a
    concept needs two or more attributes to be unique together, model
    them as a [value object](./value-objects.md) and give the aggregate
    a surrogate identity.

---

## Change the identity type

Identities are strings by default. Switch the type domain-wide by
setting `identity_type` in configuration:

```toml
# domain.toml
identity_strategy = "uuid"
identity_type = "uuid"          # native UUID objects
```

Supported types are `string`, `uuid`, and `integer`:

| Type | Generated value | Use when... |
|---|---|---|
| `string` (default) | `"9cf4ddc4-2919-..."` | You want portability across every adapter |
| `uuid` | `UUID('9cf4ddc4-...')` | Your database has a native UUID column (e.g. PostgreSQL) |
| `integer` | `154702789254628181...` | Your persistence layer requires integer ids |

You can also override the type for a single aggregate without changing
the domain default:

```python
@domain.aggregate
class Reading:
    reading_id: Auto(identifier=True, identity_type="integer")
    value: String(max_length=50)
```

See [`identity_strategy`](../../reference/configuration/index.md#identity_strategy)
and [`identity_type`](../../reference/configuration/index.md#identity_type)
in Configuration for the complete listing.

---

## Use a custom identity function

When UUIDs don't fit — you need epoch-millisecond IDs, snowflake IDs, a
prefixed business key, or anything else — switch the strategy to
`function` and supply a callable.

### At the domain level

Set the strategy in config and pass `identity_function=` when constructing
the domain. Every aggregate in the domain will use this function:

```python
import time
from protean import Domain

def epoch_ms_id() -> int:
    return int(time.time() * 1000)

domain = Domain(
    config={
        "identity_strategy": "function",
        "identity_type": "integer",
    },
    identity_function=epoch_ms_id,
)

@domain.aggregate
class Event:
    name: String(max_length=100, required=True)
```

```shell
In [1]: event = Event(name="launch")

In [2]: event.to_dict()
Out[2]: {'name': 'launch', 'id': 1718139167980}
```

The function's return type must match `identity_type`. Returning a
string while `identity_type="integer"` raises `ValidationError` on
construction.

### Per aggregate

To override the default for one aggregate — for example, to mint a
prefixed key — set the strategy and function directly on the field:

```python
import uuid
from protean.fields import Auto, String

def invoice_number() -> str:
    return f"INV-{uuid.uuid4().hex[:12].upper()}"

@domain.aggregate
class Invoice:
    invoice_number: Auto(
        identifier=True,
        identity_strategy="function",
        identity_function=invoice_number,
        identity_type="string",
    )
    customer_name: String(max_length=100, required=True)
```

```shell
In [1]: Invoice(customer_name="Acme Corp").to_dict()
Out[1]: {'invoice_number': 'INV-A3F2B9C81D4E', 'customer_name': 'Acme Corp'}
```

Field-level settings take precedence over domain configuration, so this
`Invoice` generates prefixed IDs while every other aggregate in the
domain keeps the default UUID strategy.

---

## Accept identities from the outside

Not every identifier is generated by your system. When users supply the
identity — email addresses, SKUs, tax IDs, tenant-assigned tokens — use
`Identifier` instead of `Auto`:

```python
from protean.fields import Identifier, String

@domain.aggregate
class User:
    email: Identifier(identifier=True)
    name: String(required=True)
```

`Identifier` fields are **not** auto-generated. If you construct a `User`
without an `email`, Protean raises `ValidationError`:

```shell
In [1]: User(name="John Doe")
...
ValidationError: {'email': ['is required']}

In [2]: User(email="john@example.com", name="John Doe").to_dict()
Out[2]: {'email': 'john@example.com', 'name': 'John Doe'}
```

!!! tip "Natural keys are rarely stable"
    If the "natural" identifier of a concept can change — an email
    address being the classic example — then it's not really an
    identity. Treat it as a regular attribute and keep a surrogate
    `Auto` identifier. See
    [Identity Should Be Immutable](../../concepts/foundations/identity.md#identity-should-be-immutable).

---

## Let the database generate the id

Some teams prefer auto-incrementing integer IDs generated by the
database itself. Set `increment=True` on the `Auto` field — the value
is left unset at construction time and assigned on persistence:

```python
@domain.aggregate
class AuditEntry:
    entry_id: Auto(identifier=True, increment=True, identity_type="integer")
    message: String(max_length=500, required=True)
```

This only works when:

- The underlying adapter supports auto-incrementing columns (e.g.
  PostgreSQL, SQLite).
- The database schema declares the column as `SERIAL`, `AUTOINCREMENT`,
  or equivalent — Protean does not create the sequence for you.

Because the id isn't available until the aggregate is saved, this mode
trades away the "identity at creation" guarantee. Prefer `uuid` or a
custom function unless you have a strong reason to defer identity
generation to the database.

---

## Common errors

| Exception | When it occurs |
|---|---|
| `NotSupportedError` | Two or more fields on the same aggregate are declared `identifier=True`. Protean doesn't support composite keys — use a value object for multi-attribute uniqueness. |
| `ValidationError` | An `Identifier` field is left empty. These fields are not auto-generated; the caller must supply a value. |
| `ValidationError` | A custom `identity_function` returns a value that doesn't match `identity_type` (e.g. returns a string while `identity_type="integer"`). |
| `ConfigurationError` | `identity_strategy="function"` is configured but no `identity_function` was passed to `Domain(...)` or `Auto(...)`. |
| `ConfigurationError` | An unknown `identity_strategy` or `identity_type` value is set in configuration. |

---

!!! tip "See also"
    **Concept overview:** [Identity](../../concepts/foundations/identity.md) — Why identity is fundamental to DDD and what makes an identity stable.

    **Pattern:** [Creating Identities Early](../../patterns/creating-identities-early.md) — Why Protean generates identities at construction time.

    **Reference:**

    - [Identity Reference](../../reference/domain-elements/identity.md) — Full configuration surface, strategies, and types.
    - [`Auto` field](../../reference/fields/simple-fields.md#auto) — Options for auto-generated identifiers.
    - [`Identifier` field](../../reference/fields/simple-fields.md#identifier) — Options for user-supplied identifiers.
    - [`identity_function` parameter](../../reference/domain-elements/domain-constructor.md#identity_function) — Passing a generator to the Domain constructor.
    - [Configuration: `identity_strategy`](../../reference/configuration/index.md#identity_strategy), [`identity_type`](../../reference/configuration/index.md#identity_type).

    **Related guides:**

    - [Fields](./fields.md) — Declaring attributes on domain elements.
    - [Value Objects](./value-objects.md) — Modeling concepts without identity.
