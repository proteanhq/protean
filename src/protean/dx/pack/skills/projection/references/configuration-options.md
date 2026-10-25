# Projection Configuration Options

## Overview

Pass options to the `@domain.projection` decorator or to `domain.register()`.

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
# fragment
@domain.projection(provider="postgres")
class ProductInventory:
    product_id: Identifier(identifier=True)
    name: String(required=True)
```

### Cache provider

Use a cache instead of a database:

```python
# fragment
@domain.projection(cache="redis")
class ActiveSession:
    session_id: Identifier(identifier=True)
    user_id: Identifier(required=True)
```

**Important**: When both `cache` and `provider` are specified, `cache` takes precedence and `provider` is set to `None`. A projection connects to only one data source.

### No provider or cache

Registering with both set to `None` raises `NotSupportedError`, message "MyProjection projection needs to have either a database or a cache provider":

```python
# fragment
domain.register(MyProjection, provider=None, cache=None)
```

## Schema options

### schema_name

Sets the table or collection name. It defaults to the underscore-cased class name (`ProductInventory` becomes `product_inventory`):

```python
@domain.projection(schema_name="product_inventory_view")
class ProductCatalog:
    product_id: Identifier(identifier=True)
    ...
```

Schema names are **not inherited** by subclasses: each subclass gets its own derived name.

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

## Query options

### limit

Default query result limit, `100` unless set:

```python
@domain.projection(limit=50)          # Limit to 50 results
class UserSummary:
    user_id: Identifier(identifier=True)

@domain.projection(limit=None)        # No limit (unlimited)
class FullReport:
    report_id: Identifier(identifier=True)

@domain.projection(limit=-1)          # Negative values treated as None (unlimited)
class AnotherReport:
    report_id: Identifier(identifier=True)
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

## Check options

### externally_populated

Set it to `True` when a subscriber or event handler fills the projection, for example from another domain's messages. `check` then skips `PROJECTION_WITHOUT_PROJECTOR` and `UNSOURCED_PROJECTION_FIELD` for the projection.

```python
@domain.projection(externally_populated=True)
class ExchangeRate:
    currency_code: Identifier(identifier=True)
    rate: Float()
```

The option changes only what `check` reports. Storage and querying work the same.

## Abstract projections

An abstract projection is a base class that is not registered as a concrete projection:

```python
@domain.projection(abstract=True)
class BaseView:
    age: Integer(default=5)
    # No identifier field required for abstract projections

@domain.projection
class ConcreteView(BaseView):
    view_id: Identifier(identifier=True)
    name: String()
```

A subclass of an abstract projection needs its own `@domain.projection` decorator (or `domain.register()` call). Registration turns it into a concrete projection. It inherits the base's fields, so `ConcreteView` has `age`, `view_id` and `name`.

Instantiating an abstract projection raises `NotSupportedError` ("BaseView class has been marked abstract and cannot be instantiated").

## Complete example

See [projection_with_options.py](../assets/projection_with_options.py) for a complete, runnable example.

## Related

- [Basic Projection](basic-projection.md): Defining projections
- [Persistence & Querying](persistence-querying.md): Persisting and querying
- [Anti-patterns](anti-patterns.md): Common mistakes
