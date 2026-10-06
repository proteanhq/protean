# Entity Configuration

Entities are configured through options passed to the `@domain.entity` decorator. An inner `class Meta:` on an entity is ignored, so put every option in the decorator.

## Overview

Entity configuration controls:
- Identity field generation
- Persistence naming
- Base classes for sharing fields
- Custom database models
- Schema customization

## Configuration Options

### `part_of` (Required)

Associates the entity with an aggregate. This is the only required configuration option.

**Use a string reference to the aggregate** to avoid circular dependencies. A nested entity is the exception: its `part_of` is the parent entity, passed as a class, because a string resolves only to an aggregate (see [Nested Entities](nested-entities.md)).

```python
from decimal import Decimal as D  # stdlib Decimal, aliased so it does not clash with the field

from protean import Domain
from protean.core.entity import BaseEntity
from protean.fields import Decimal, HasMany, Identifier, Integer, String, Text

domain = Domain()

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    line_items = HasMany("LineItem")

@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
```

**Why string references?** Aggregates, entities, and value objects are often defined in the same file. The aggregate references entities via `HasMany("LineItem")` (forward reference), and entities reference back via `part_of`. Using string references on both sides breaks this circular dependency and allows elements to be defined in any order.

### Sharing fields through a base class

`@domain.entity` has no `abstract` option: passing it raises `ConfigurationError`. To share fields and behavior, put them on a plain subclass of `BaseEntity` and leave it undecorated. Decorate only the concrete subclasses. Keep association fields (`HasMany`, `HasOne`) on the concrete entities: the same association inherited by two entities fails `domain.init()` with `ConfigurationError`.

```python
class BaseLineItem(BaseEntity):
    """Shared fields and behavior for line items. Not registered."""
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True, min_value=0)

    @property
    def subtotal(self) -> D:
        return self.quantity * self.unit_price


@domain.entity(part_of="Order")
class ProductLineItem(BaseLineItem):
    """Concrete line item for products."""
    product_id: Identifier(required=True)
    product_name: String(required=True, max_length=200)


@domain.entity(part_of="Order")
class ServiceLineItem(BaseLineItem):
    """Concrete line item for services."""
    service_id: Identifier(required=True)
    service_description: Text(required=True)
```

`ProductLineItem` and `ServiceLineItem` each get `quantity`, `unit_price`, and `subtotal` from the base class, plus their own `id` field.

**Use cases:**
- Sharing common fields and behavior across entity types
- Implementing entity type hierarchies

**Important notes:**
- Do not decorate the base class. A decorated base becomes a real entity with its own table.
- The base class must subclass `BaseEntity`. A plain mixin class does not contribute fields.

### `auto_add_id_field`

Controls automatic ID field generation.

```python
# Default: auto_add_id_field=True
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    # Automatically gets 'id' field

# Disable auto ID generation
@domain.entity(part_of="Order", auto_add_id_field=False)
class LineItem:
    # Must provide your own identifier
    line_number: Integer(required=True, identifier=True)
    product_id: String(required=True)
```

**When to disable:**
- You want to use a custom identifier field
- The entity uses a natural key (e.g., line_number)

**Important:**
- If disabled, you MUST provide a field with `identifier=True`
- Only one field can be marked as the identifier

### `schema_name`

Customizes the name used in persistence storage.

```python
# Default: uses snake_case version of class name
@domain.entity(part_of="Order")
class LineItem:
    # Stored as 'line_item' in database
    pass

# Custom schema name
@domain.entity(part_of="Order", schema_name="order_items")
class LineItem:
    # Stored as 'order_items' in database
    pass
```

**Use cases:**
- Matching existing database schema
- Following specific naming conventions
- Avoiding naming conflicts

### Custom database models

Protean builds a database model for every entity. To control the mapping
yourself, register your own model against the entity with
`@domain.database_model`.

Declare only the columns you want to control. Protean fills in the rest of the
entity's fields, including the foreign key back to the aggregate, and
`schema_name` sets the table name.

```python
import sqlalchemy as sa
from protean.core.database_model import BaseDatabaseModel

@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    unit_price: Decimal(precision=19, scale=4, required=True)

@domain.database_model(part_of=LineItem, schema_name="order_items")
class LineItemModel(BaseDatabaseModel):
    product_id = sa.Column(sa.Text)
```

**Use cases:**
- Special database-specific configurations
- Mapping to legacy database schemas

**Important:**
- Register the model with `@domain.database_model`. The `database_model` option
  on `@domain.entity` is not read by anything, so passing your model there
  leaves the auto-generated one in place.
- Every column must match a field declared on the entity. A column for anything
  else is rejected at registration with `IncorrectUsageError`.
- Custom models are provider-specific (a SQLAlchemy model won't work with
  Elasticsearch).

**Note:** In most cases, Protean's auto-generated model is sufficient.

## Configure through the decorator

Pass every option to `@domain.entity`. Protean does not read an inner `class Meta:`, so options placed there are silently ignored:

```python
# fragment
@domain.entity(part_of="Order")
class LineItem:
    product_id: Identifier(required=True)

    class Meta:  # Ignored: schema_name stays "line_item"
        schema_name = "order_items"
```

Write it as `@domain.entity(part_of="Order", schema_name="order_items")` instead.

## Complete Configuration Example

```python
@domain.entity(
    part_of="Order",
    auto_add_id_field=True,
    schema_name="order_line_items"
)
class LineItem:
    """
    A line item in an order.

    Configuration:
    - part_of: "Order" (belongs to Order aggregate)
    - auto_add_id_field: True (gets automatic 'id' field)
    - schema_name: 'order_line_items' (database table name)
    """
    product_id: Identifier(required=True)
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True, min_value=0)

    @property
    def subtotal(self) -> D:
        return self.quantity * self.unit_price
```

## Custom Identifier Fields

### Using Natural Keys

```python
@domain.entity(part_of="Order", auto_add_id_field=False)
class LineItem:
    # Use line number as identifier
    line_number: Integer(required=True, identifier=True)
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
```

### Composite Keys (Not Recommended)

Protean does not support composite keys. If you need one, reconsider the entity design or use the auto-generated ID.

**Recommendation:** Use auto-generated IDs unless you have a strong business reason for natural keys.

## Inheritance Hierarchies

### Base Entity Pattern

```python
class BaseItem(BaseEntity):
    """Undecorated base for all item types."""
    quantity: Integer(required=True, min_value=1)
    unit_price: Decimal(precision=19, scale=4, required=True, min_value=0)

    @property
    def subtotal(self) -> D:
        return self.quantity * self.unit_price


@domain.entity(part_of="Order")
class ProductItem(BaseItem):
    """Item representing a physical product."""
    product_id: Identifier(required=True)
    product_name: String(required=True)


@domain.entity(part_of="Order")
class ServiceItem(BaseItem):
    """Item representing a service."""
    service_id: Identifier(required=True)
    service_description: Text(required=True)
    billable_hours: Float(required=True)
```

## Field-Level Configuration

While entity-level configuration is defined in the decorator, field-level configuration is defined on individual fields:

```python
@domain.entity(part_of="Order")
class LineItem:
    # Field with constraints
    product_id: String(
        required=True,
        max_length=50,
        identifier=False
    )

    # Field with validation
    quantity: Integer(
        required=True,
        min_value=1,
        max_value=9999
    )

    # Field with default
    discount_percent: Float(
        default=0.0,
        min_value=0.0,
        max_value=100.0
    )

    # Optional field
    notes: Text(required=False)
```

## Common Configuration Patterns

### Standard Entity (Most Common)

```python
@domain.entity(part_of="Order")
class LineItem:
    # Uses all defaults:
    # - auto_add_id_field=True
    # - schema_name="line_item"
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
```

### Shared Base Class

```python
class BaseItem(BaseEntity):
    # Common fields and behavior; leave this class undecorated
    quantity: Integer(required=True)
    unit_price: Decimal(precision=19, scale=4, required=True)
```

### Entity with Custom Schema Name

```python
@domain.entity(part_of="Order", schema_name="order_items")
class LineItem:
    # Stored as 'order_items' instead of 'line_item'
    product_id: Identifier(required=True)
```

### Entity with Natural Key

```python
@domain.entity(part_of="Order", auto_add_id_field=False)
class LineItem:
    line_number: Integer(required=True, identifier=True)
    product_id: Identifier(required=True)
```

## Testing Configuration

Read the applied options from the entity's `meta_`, and its fields with `declared_fields`:

```python
from protean.utils.reflection import declared_fields

@domain.entity(part_of="Order", schema_name="order_items")
class LineItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)


def test_entity_configuration():
    """Test that entity configuration is applied correctly."""
    domain.init(traverse=False)

    # Verify configuration
    assert LineItem.meta_.schema_name == "order_items"
    assert LineItem.meta_.part_of is Order

    # Verify fields
    assert "id" in declared_fields(LineItem)
    assert "product_id" in declared_fields(LineItem)


test_entity_configuration()
```

## Best Practices

1. **Use defaults when possible** - Only customize when necessary
2. **Leave shared base classes undecorated** - Decorate only the concrete entities
3. **Document custom configurations** - Explain why you deviated from defaults
4. **Prefer auto IDs** - Use natural keys only when there's a strong business reason
5. **Keep schema names simple** - Use standard snake_case conventions

## Related

- [Aggregates](../../aggregate/SKILL.md) - Aggregate configuration options
- [Value Objects](../../value-object/SKILL.md) - Value object configuration
- [Anti-patterns](./anti-patterns.md) - Common configuration mistakes
