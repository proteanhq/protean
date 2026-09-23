---
name: projection
description: Define a Protean projection (read model) - a denormalized, query-optimized data structure used on the read side of CQRS. Projections are closer to the database than domain aggregates and can be stored in either a database (provider) or cache (e.g., Redis). They support basic field types (String, Integer, Float, Identifier, DateTime, etc.) and ValueObject fields (stored as flattened shadow fields) - but not References or Associations. Every projection must have at least one identifier field. Projections are populated by projectors in response to domain events. Use when you need to define a read model, create a query-optimized view, build a denormalized data structure, define a CQRS read side schema, or when the user asks to "create a projection", "define a read model", "add a query view", "build a denormalized view", "create a CQRS projection", or "define a read-optimized model".
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
  diagnostic_codes:
    - PROJECTION_WITHOUT_PROJECTOR
    - UNSOURCED_PROJECTION_FIELD
    - USAGE_NOT_A_PROJECTION
---

# Projection

## How projections differ from aggregates

| Aspect | Aggregate | Projection |
|--------|-----------|------------|
| **Purpose** | Enforce business rules (write side) | Optimized for querying (read side) |
| **Field types** | All types (References, Associations, ValueObjects) | Basic types plus ValueObjects (flattened); no References or Associations |
| **Data shape** | Normalized, bounded by consistency boundary | Denormalized, flattened for query efficiency |
| **Populated by** | Commands and domain logic | Projectors consuming domain events |
| **Storage** | Database via repository | Database (provider) or cache |
| **Decorator** | `@domain.aggregate` | `@domain.projection` |
| **Identity** | Auto-generated `id` or custom | Must declare at least one `identifier=True` field |

## Basic structure

```python
from protean import Domain
from protean.fields import DateTime, Float, Identifier, Integer, String, Text

domain = Domain()

@domain.projection
class ProductInventory:
    product_id: Identifier(identifier=True, required=True)
    name: String(max_length=100, required=True)
    description: Text()
    price: Float(required=True)
    stock_quantity: Integer(default=0)
    last_updated: DateTime()
```

## Key rules

1. **At least one identifier field** - Every non-abstract projection must have a field with `identifier=True`; abstract projections are exempt from this check
2. **No Reference or Association fields** - `Reference` and Associations (`HasOne`/`HasMany`) are rejected. Basic field types and `ValueObject` fields are allowed; a `ValueObject` is stored as flattened shadow fields (e.g. `address_street`, `address_city`)
3. **Use @domain.projection decorator** - Register with domain: `@domain.projection` or `domain.register(MyProjection)`
4. **Projections are denormalized** - Flatten nested/related data into basic fields
5. **Default provider is "default"** - Uses the default database provider unless overridden
6. **Cache overrides provider** - When both `cache` and `provider` are specified, `cache` takes precedence
7. **Default query limit is 100** - Can be overridden; set to `None` or negative for unlimited
8. **Schema name auto-derived** - Defaults to underscore-cased class name (e.g., `ProductInventory` -> `product_inventory`)
9. **Identifier values are immutable** - Once set, the identifier field cannot be changed
10. **Identifier values auto-generate when omitted, for `Identifier`/`Auto` fields** - An `identifier=True` field declared as `Identifier` or `Auto` generates a value on creation if you do not supply one (a UUID by default), the same as aggregates. An `identifier=True` field declared with another field type (e.g. `String`) gets no default and stays required

## Projection options

| Option | Default | Purpose |
|--------|---------|---------|
| `provider` | `"default"` | Database provider for storing projection data |
| `cache` | `None` | Cache provider (e.g., `"redis"`); overrides `provider` when set |
| `schema_name` | underscore class name | Custom table/schema name in the database |
| `order_by` | `()` | Default ordering for query results |
| `limit` | `100` | Default query result limit; `None` for unlimited |
| `abstract` | `False` | If `True`, projection is an abstract base class |
| `database_model` | `None` | Custom model name for storage |

## Supported field types

Projections support these basic field types:

| Type | Import | Example |
|------|--------|---------|
| `Identifier` | `from protean.fields import Identifier` | `user_id: Identifier(identifier=True)` |
| `Auto` | `from protean.fields import Auto` | `id: Auto(identifier=True)` |
| `String` | `from protean.fields import String` | `name: String(max_length=100)` |
| `Text` | `from protean.fields import Text` | `description: Text()` |
| `Integer` | `from protean.fields import Integer` | `count: Integer(default=0)` |
| `Float` | `from protean.fields import Float` | `price: Float(required=True)` |
| `Boolean` | `from protean.fields import Boolean` | `active: Boolean(default=True)` |
| `DateTime` | `from protean.fields import DateTime` | `created_at: DateTime()` |
| `Date` | `from protean.fields import Date` | `birth_date: Date()` |

Projections also accept `ValueObject` fields (`from protean.fields import ValueObject`, e.g. `shipping_address = ValueObject(Address)`). A value object is stored as flattened shadow fields (`shipping_address_street`, `shipping_address_city`, ...) and each attribute is queryable on its own.

## Quick example: Database-backed projection

```python
@domain.projection(provider="postgres", schema_name="product_inventory")
class ProductInventory:
    product_id: Identifier(identifier=True, required=True)
    name: String(max_length=100, required=True)
    stock_quantity: Integer(default=0)
```

## Quick example: Cache-backed projection

```python
@domain.projection(cache="redis")
class ActiveSession:
    session_id: Identifier(identifier=True, required=True)
    user_id: Identifier(required=True)
    email: String(required=True)
```

## Quick example: Custom query limit and ordering

```python
@domain.projection(order_by=("last_name",), limit=50)
class UserDirectory:
    user_id: Identifier(identifier=True, required=True)
    first_name: String(max_length=50)
    last_name: String(max_length=50)
    email: String(required=True)
```

## Quick example: Projection with defaults method

```python
from enum import Enum

class BuildingStatus(Enum):
    WIP = "WIP"
    DONE = "DONE"

@domain.projection
class Building:
    building_id: Identifier(identifier=True)
    name: String(max_length=50)
    floors: Integer()
    status: String(choices=BuildingStatus)

    def defaults(self):
        if not self.status:
            if self.floors == 4:
                self.status = BuildingStatus.DONE.value
            else:
                self.status = BuildingStatus.WIP.value
```

## Querying read models

Projections are queried through the same repository/DAO interface as aggregates:

```python
repo = domain.repository_for(ProductInventory)

# Flat COUNT without loading rows
low_stock = repo._dao.query.filter(stock_quantity__lt=10).count()

# isnull lookup — records where a field is / isn't set
never_updated = repo._dao.query.filter(last_updated__isnull=True).all().items

# Fetch items without the separate total-count round-trip
page = repo._dao.query.filter(stock_quantity__lt=10).all(with_total=False).items
```

See the `repository` skill for the full querying surface (filtering, ordering,
pagination, Q objects).

`view_for()` and `connection_for()` operate on projections only; passing a
non-projection element (an aggregate, say) raises `USAGE_NOT_A_PROJECTION`.

## Common mistakes

### Missing identifier field

```python
@domain.projection
class UserView:
    name: String()  # Wrong! No identifier field
    email: String()
```

Instead: Add at least one identifier field

```python
@domain.projection
class UserView:
    user_id: Identifier(identifier=True)  # Correct!
    name: String()
    email: String()
```

### Using Reference or Association fields

```python
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    customer = Reference(Customer)      # Wrong!
    items = HasMany(OrderItem)           # Wrong!
```

`ValueObject` fields are allowed (they flatten to shadow fields); `Reference`
and Associations (`HasOne`/`HasMany`) are not. Flatten related data into basic
fields instead:

```python
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    customer_name: String()
    customer_email: String()
    item_count: Integer()
    shipping_city: String()
    shipping_zip: String()
```

### No provider and no cache

```python
domain.register(MyProjection, provider=None, cache=None)  # Wrong!
```

Instead: Always have at least a provider or a cache

### No projector to populate it

A projection with no projector is never populated, so queries against it always return empty. `check` reports this as `PROJECTION_WITHOUT_PROJECTOR`. Add a projector for the projection, or set `externally_populated=True` if a subscriber fills it instead.

### Field the projector never writes

A projection field no projector handler ever writes renders as a dead column. `check` reports this as `UNSOURCED_PROJECTION_FIELD`. Write every field from the projector handler for the event that carries it, or drop the field.

### Confusing projection with aggregate

```python
# Wrong! Projections are read models, not write models
@domain.projection
class Order:
    order_id: Identifier(identifier=True)
    items = HasMany(OrderItem)  # Fails! No associations

    def place(self):
        # Business logic doesn't belong in projections
        ...
```

Instead: Use `@domain.aggregate` for write models with business logic

## Detailed references

### Core Concepts
- [Basic Projection](references/basic-projection.md) - Defining a simple projection with field types
- [Configuration Options](references/configuration-options.md) - Provider, cache, schema_name, limit, and order_by
- [Persistence & Querying](references/persistence-querying.md) - Persisting and querying projection data
- [Field Type Restrictions](references/field-type-restrictions.md) - Why only basic types are allowed
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Simple Projection](assets/projection_simple.py) - Basic projection with identifier and fields
- [Projection with Options](assets/projection_with_options.py) - Custom provider, schema, limit, ordering
- [Projection with Defaults](assets/projection_with_defaults.py) - Projection using defaults() method
- [Projection Persistence](assets/projection_persistence.py) - Persisting and querying projections
- [Field Validation](assets/projection_field_validation.py) - Demonstrating field type restrictions

### Related Skills
- `projector` - Projectors populate projections from domain events
- `aggregate` - Aggregates are the write-side counterpart to projections
- `event` - Events are the bridge between aggregates and projections
- `patterns/cqrs` - Projections implement the query side of CQRS

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
