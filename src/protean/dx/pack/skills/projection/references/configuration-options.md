# Projection Configuration Options

## Overview

Projections can be configured with several options to control storage, querying, and schema behavior. Options are passed directly to the `@domain.projection` decorator or to `domain.register()`.

## Storage options

### Database provider (default)

By default, projections use the `"default"` database provider:

```python
@domain.projection  # Uses provider="default"
class ProductInventory:
    product_id: Identifier(identifier=True)
    name: String(required=True)
```

Specify a custom provider:

```python
@domain.projection(provider="postgres")
class ProductInventory:
    product_id: Identifier(identifier=True)
    name: String(required=True)
```

### Cache provider

Use a cache instead of a database:

```python
@domain.projection(cache="redis")
class ActiveSession:
    session_id: Identifier(identifier=True)
    user_id: Identifier(required=True)
```

**Important**: When both `cache` and `provider` are specified, `cache` takes precedence and `provider` is set to `None`. A projection connects to only one data source.

### No provider or cache

A projection must have at least one storage backend. Registering with both set to `None` raises `NotSupportedError`:

```python
# This will raise NotSupportedError
domain.register(MyProjection, provider=None, cache=None)
```

## Schema options

### schema_name

Controls the table/collection name in the database. Defaults to the underscore-cased class name:

```python
@domain.projection(schema_name="product_inventory_view")
class ProductInventory:
    product_id: Identifier(identifier=True)
    ...
```

Default behavior:
- `ProductInventory` -> `product_inventory`
- `UserProfile` -> `user_profile`
- `OrderSummary` -> `order_summary`

Schema names are **not inherited** by subclasses - each subclass gets its own derived name.

### Custom database models

Protean builds a database model for every projection. To control the mapping
yourself, register your own model with `@domain.database_model`. Declare only
the columns you want to control; Protean fills in the rest of the projection's
fields.

```python
from sqlalchemy import Column, Text
from protean.core.database_model import BaseDatabaseModel

@domain.database_model(part_of=ProductInventory, schema_name="inventory")
class CustomInventoryModel(BaseDatabaseModel):
    name = Column(Text)
```

The `database_model` option on `@domain.projection` is not read by anything, so
passing your model there leaves the auto-generated one in place.

## Query options

### limit

Default query result limit. Set to `100` by default:

```python
@domain.projection(limit=50)          # Limit to 50 results
class UserDirectory:
    ...

@domain.projection(limit=None)        # No limit (unlimited)
class FullReport:
    ...

@domain.projection(limit=-1)          # Negative values treated as None (unlimited)
class AnotherReport:
    ...
```

### order_by

Default ordering for query results:

```python
@domain.projection(order_by=("last_name",))
class UserDirectory:
    user_id: Identifier(identifier=True)
    first_name: String(max_length=50)
    last_name: String(max_length=50)
```

Order_by can be overridden in subclasses.

## Abstract projections

Mark a projection as abstract to create a base class that won't be registered as a concrete projection:

```python
@domain.projection(abstract=True)
class BaseView:
    age: Integer(default=5)
    # No identifier field required for abstract projections

class ConcreteView(BaseView):
    view_id: Identifier(identifier=True)
    name: String()
```

Abstract projections:
- Don't require an identifier field
- Cannot be instantiated (raises `NotSupportedError`)
- Serve as base classes for concrete projections

## Complete example

See [projection_with_options.py](../assets/projection_with_options.py) for a complete, runnable example.

## Related

- [Basic Projection](basic-projection.md) - Defining projections
- [Persistence & Querying](persistence-querying.md) - Persisting and querying
- [Anti-patterns](anti-patterns.md) - Common mistakes
