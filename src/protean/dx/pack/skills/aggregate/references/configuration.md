# Aggregate Configuration Options

## Passing options

Pass every option as a keyword argument to the decorator:

```python
@domain.aggregate(
    provider="default",
    schema_name="order_records"
)
class Order:
    ...
```

An inner `class Meta:` on the aggregate is ignored. Protean does not read it, so options set there have no effect. Use the decorator options.

## Configuration Options

### `abstract`

**Type:** `bool`
**Default:** `False`

Marks an aggregate as abstract. Abstract aggregates cannot be instantiated and must be subclassed.

```python
from datetime import datetime, timezone

from protean.exceptions import NotSupportedError


def utc_now():
    return datetime.now(timezone.utc)


@domain.aggregate(abstract=True)
class TimeStamped:
    created_at: DateTime(default=utc_now)
    updated_at: DateTime(default=utc_now)

@domain.aggregate
class User(TimeStamped):
    name: String(required=True)

domain.init(traverse=False)

with domain.domain_context():
    user = User(name="John")  # OK

    try:
        TimeStamped()
    except NotSupportedError:
        print("Abstract aggregates cannot be instantiated")
```

**Related:** See [assets/aggregate_inheritance.py](../assets/aggregate_inheritance.py) for examples.

---

### `auto_add_id_field`

**Type:** `bool`
**Default:** `True`

Controls whether Protean automatically adds an `id` field as the identifier.

```python
# Default behavior - auto-generated id field
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
# Has: id: Auto()

# Custom identifier
@domain.aggregate(auto_add_id_field=False)
class Product:
    sku: String(required=True, identifier=True)
    name: String(required=True)
# No auto id field
```

Use it for a natural identifier such as a SKU, an email or an account number. If set to `False`, declare your own field with `identifier=True`. Without one the aggregate has no identity field at all, and nothing raises at registration.

**Related:** See [assets/aggregate_inheritance.py](../assets/aggregate_inheritance.py) for abstract base without ID.

---

### `provider`

**Type:** `str`
**Default:** `"default"`

Names the database the aggregate is persisted to. The value is a key in the `databases` section of the domain config. Each entry in that section names its adapter by its registered name (`memory`, `sqlite`, `postgresql`, `mssql`, `mysql`, `elasticsearch`), not by a class path.

```toml
# In domain.toml
[databases.default]
provider = "sqlite"
database_uri = "sqlite:///primary.db"

[databases.orders_db]
provider = "postgresql"
database_uri = "postgresql://localhost/orders"

[databases.analytics_db]
provider = "elasticsearch"
database_uri = "http://localhost:9200"
```

```python
# Use specific provider
@domain.aggregate(provider="orders_db")
class Order:
    ...

# Another aggregate uses different database
@domain.aggregate(provider="analytics_db")
class OrderReport:
    ...
```

At least one provider named `"default"` must be configured.

---

### `schema_name`

**Type:** `str`
**Default:** Snake-case version of class name

Customizes the table/collection name in the database.

```python
# Default: uses "user_account" as table name
@domain.aggregate
class UserAccount:
    ...

# Custom: uses "users" as table name
@domain.aggregate(schema_name="users")
class UserAccount:
    ...

# Custom: uses "active_orders" as table name
@domain.aggregate(schema_name="active_orders")
class Order:
    ...
```

---

### Custom database models

**Default:** Auto-generated

Protean builds a database model for every aggregate. To control the mapping
yourself, register your own model against the aggregate with
`@domain.database_model`.

Declare only the columns you want to control. Protean fills in the rest of the
aggregate's fields, and `schema_name` sets the table name.

```python
from sqlalchemy import Column, Text
from protean.core.database_model import BaseDatabaseModel

@domain.aggregate
class User:
    email: String(required=True, max_length=255)
    full_name: String(required=True, max_length=200)

@domain.database_model(part_of=User, schema_name="users")
class CustomUserModel(BaseDatabaseModel):
    email = Column(Text, unique=True)
```

**Important:**
- Register the model with `@domain.database_model(part_of=<Aggregate>)`.
- Every column must match a field declared on the aggregate. A column for
  anything else is rejected at registration with `IncorrectUsageError`.
- Custom models are provider-specific (a SQLAlchemy model won't work with
  Elasticsearch)

---

### `stream_category`

**Type:** `str`
**Default:** Snake-case version of class name, prefixed with the domain name

Names the stream the aggregate's events and commands are written to. The event store, the handlers and the subscriptions all find the aggregate's messages by it. Protean prefixes the value with the domain name at registration, so in a domain named `test` the aggregate below has the category `test::order`.

```python
# Default: stream category is "<domain>::order"
@domain.aggregate
class Order:
    ...

# Custom: stream category is "<domain>::customer_orders"
@domain.aggregate(stream_category="customer_orders")
class Order:
    ...
```

**Event sourcing:**

```python
# Event-sourced aggregate
@domain.aggregate(
    event_sourced=True,
    stream_category="order"
)
class Order:
    ...

# In a domain named `test`:
# Events are stored in: test::order-{aggregate_id}
# Commands are sent to: test::order:command-{aggregate_id}
```

**Related:** See [Stream Categories](https://docs.proteanhq.com/concepts/async-processing/stream-categories/) documentation.

---

## Common Patterns

### Abstract Base with No ID

```python
@domain.aggregate(abstract=True, auto_add_id_field=False)
class AuditedEntity:
    created_at: DateTime(default=utc_now)
    created_by: String(max_length=100)
```

## Related

- [Aggregate Inheritance](../assets/aggregate_inheritance.py)
- [Stream Categories](https://docs.proteanhq.com/concepts/async-processing/stream-categories/)
- [Database Providers](https://docs.proteanhq.com/reference/adapters/database/)
