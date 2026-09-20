# Aggregate Configuration Options

Aggregates can be customized through various configuration options passed to the decorator or defined in a Meta class.

## Overview

Configuration options control:
- Whether the aggregate is abstract
- Identity field behavior
- Database/provider selection
- Persistence schema naming
- Custom model mapping
- Event sourcing stream categories

## Configuration Methods

### Via Decorator Parameters

```python
@domain.aggregate(
    abstract=True,
    provider="orders_db",
    schema_name="order_records"
)
class Order:
    ...
```

### Via Meta Class

```python
@domain.aggregate
class Order:
    class Meta:
        abstract = False
        provider = "orders_db"
        schema_name = "order_records"
```

Both approaches are equivalent. Choose decorator parameters for simple cases, Meta class when you have many options.

## Configuration Options

### `abstract`

**Type:** `bool`
**Default:** `False`

Marks an aggregate as abstract. Abstract aggregates cannot be instantiated and must be subclassed.

```python
@domain.aggregate(abstract=True)
class TimeStamped:
    created_at: DateTime(default=utc_now)
    updated_at: DateTime(default=utc_now)

@domain.aggregate
class User(TimeStamped):
    name: String(required=True)

# OK
user = User(name="John")

# Raises NotSupportedError
timestamped = TimeStamped()
```

**Use cases:**
- Base classes with common fields
- Template aggregates for inheritance hierarchies
- Mixins for cross-cutting concerns

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
    customer_id: String(required=True)
# Has: id: Auto()

# Custom identifier
@domain.aggregate(auto_add_id_field=False)
class Product:
    sku: String(required=True, identifier=True)
    name: String(required=True)
# No auto id field
```

**Use cases:**
- When you have natural identifiers (SKU, email, account number)
- When migrating from legacy systems with existing IDs
- When using composite keys (though not recommended)

**Important:** If set to `False`, you must provide your own field with `identifier=True`.

**Related:** See [assets/aggregate_inheritance.py](../assets/aggregate_inheritance.py) for abstract base without ID.

---

### `provider`

**Type:** `str`
**Default:** `"default"`

Specifies which database/provider to use for persistence.

```python
# In domain.toml
[databases.default]
provider = "protean.adapters.repository.sqlalchemy.SAProvider"
database_uri = "sqlite:///primary.db"

[databases.orders_db]
provider = "protean.adapters.repository.sqlalchemy.SAProvider"
database_uri = "postgresql://localhost/orders"

[databases.analytics_db]
provider = "protean.adapters.repository.elasticsearch.ESProvider"
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

**Use cases:**
- Microservices with separate databases
- CQRS with separate read/write databases
- Multi-tenant systems
- Polyglot persistence (SQL + NoSQL)

**Important:** At least one provider named `"default"` must be configured.

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

**Use cases:**
- Matching existing database schemas
- Following specific naming conventions
- Avoiding conflicts with reserved words
- Backwards compatibility with legacy systems

---

### `model`

**Type:** Model class
**Default:** Auto-generated

Allows you to specify a custom database model instead of using the auto-generated one.

```python
from sqlalchemy import Column, String, Integer, Table
from protean.adapters.repository.sqlalchemy import SqlalchemyModel

# Define custom SQLAlchemy model
class CustomUserModel(SqlalchemyModel):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True)
    full_name = Column(String(200))

@domain.aggregate(model=CustomUserModel)
class User:
    email: String(required=True, max_length=255)
    full_name: String(required=True, max_length=200)
```

**Use cases:**
- Complex database mappings not handled by auto-generation
- Legacy database schemas
- Performance optimizations (indexes, partitioning)
- Database-specific features

**Important:**
- Custom models are provider-specific (SQLAlchemy model won't work with Elasticsearch)
- You must ensure field mappings are correct
- Custom models bypass some Protean optimizations

---

### `stream_category`

**Type:** `str`
**Default:** Snake-case version of class name

Defines the logical grouping for messages (events/commands) related to the aggregate.

```python
# Default: stream category is "order"
@domain.aggregate
class Order:
    ...

# Custom: stream category is "customer_orders"
@domain.aggregate(stream_category="customer_orders")
class Order:
    ...
```

The stream category is used by:
- **Event Store**: To organize events in event sourcing
- **Handlers**: To subscribe to the right message streams
- **Brokers**: To route messages correctly
- **Subscriptions**: To poll for new messages

**Use cases:**
- Grouping related aggregates under one stream
- Organizing messages by business domain
- Multi-tenant systems (e.g., `tenant_1_orders`)
- Customizing event sourcing stream structure

**Important for Event Sourcing:**

```python
# Event-sourced aggregate
@domain.aggregate(
    is_event_sourced=True,
    stream_category="order"
)
class Order:
    ...

# Events are stored in: order-{aggregate_id}
# Commands are sent to: order:command-{aggregate_id}
```

**Related:** See [Stream Categories](https://protean.readthedocs.io/guides/essentials/stream-categories.html) documentation.

---

## Example: Full Configuration

```python
from datetime import datetime, timezone

@domain.aggregate(
    abstract=False,
    auto_add_id_field=True,
    provider="orders_db",
    schema_name="customer_orders",
    stream_category="order"
)
class Order:
    """Fully configured order aggregate."""

    customer_id: String(required=True, max_length=50)
    status: String(max_length=20, default="draft")
    total_amount: Float(default=0.0)
    created_at: DateTime(default=lambda: datetime.now(timezone.utc))
```

This aggregate:
- Is not abstract (can be instantiated)
- Has an auto-generated `id` field
- Is persisted to the `orders_db` provider
- Uses the table/collection name `customer_orders`
- Groups messages under the `order` stream category

## Best Practices

1. **Use abstract=True for base classes** - Prevent accidental instantiation
2. **Keep auto_add_id_field=True unless necessary** - Natural IDs are rare
3. **Use provider for database separation** - Keep reads/writes separate in CQRS
4. **Customize schema_name for legacy integration** - Match existing schemas
5. **Use custom models sparingly** - Let Protean handle mappings when possible
6. **Use meaningful stream_category names** - Reflects business domain, not technical structure

## Common Patterns

### Abstract Base with No ID

```python
@domain.aggregate(abstract=True, auto_add_id_field=False)
class AuditedEntity:
    created_at: DateTime(default=utc_now)
    created_by: String(max_length=100)
```

### Multi-Database Setup

```python
@domain.aggregate(provider="write_db")
class Order:
    # Write model - normalized
    ...

@domain.aggregate(provider="read_db")
class OrderSummary:
    # Read model - denormalized
    ...
```

### Custom Table Names for Legacy DB

```python
@domain.aggregate(schema_name="tbl_users")
class User:
    ...

@domain.aggregate(schema_name="tbl_orders")
class Order:
    ...
```

## Related

- [Aggregate Inheritance](../assets/aggregate_inheritance.py)
- [Stream Categories](https://protean.readthedocs.io/guides/essentials/stream-categories.html)
- [Database Providers](https://protean.readthedocs.io/guides/adapters/database.html)
