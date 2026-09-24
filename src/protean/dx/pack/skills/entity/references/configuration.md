# Entity Configuration

Entities can be customized through various configuration options passed to the `@domain.entity` decorator or defined in a `Meta` class. This guide covers all available configuration options and how to use them.

## Overview

Entity configuration controls:
- Identity field generation
- Persistence naming
- Abstract entities for inheritance
- Custom database models
- Schema customization

## Configuration Options

### `part_of` (Required)

Associates the entity with an aggregate. This is the only required configuration option.

**Always use a string reference** to avoid circular dependencies:

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
```

**Why string references?** Aggregates, entities, and value objects are often defined in the same file. The aggregate references entities via `HasMany("LineItem")` (forward reference), and entities reference back via `part_of`. Using string references on both sides breaks this circular dependency and allows elements to be defined in any order.

### `abstract`

Marks an entity as abstract, preventing direct instantiation.

```python
@domain.entity(part_of="Order", abstract=True)
class BaseLineItem:
    """Abstract base entity for line items."""
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.0)

    @property
    def subtotal(self) -> float:
        return self.quantity * self.unit_price


@domain.entity(part_of="Order")
class ProductLineItem(BaseLineItem):
    """Concrete line item for products."""
    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=200)


@domain.entity(part_of="Order")
class ServiceLineItem(BaseLineItem):
    """Concrete line item for services."""
    service_id: String(required=True, max_length=50)
    service_description: Text(required=True)
```

**Use cases:**
- Sharing common fields and behavior across entity types
- Implementing entity type hierarchies
- Creating reusable base entities

**Important notes:**
- Abstract entities cannot be instantiated directly
- They must be subclassed
- Usually combined with `auto_add_id_field=False`

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
- Creating abstract base entities
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
from sqlalchemy import Column, Text
from protean.core.database_model import BaseDatabaseModel

@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True, max_length=50)
    quantity: Integer(required=True)
    unit_price: Float(required=True)

@domain.database_model(part_of=LineItem, schema_name="order_items")
class LineItemModel(BaseDatabaseModel):
    product_id = Column(Text)
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

## Using Meta Class

Configuration can also be specified using a `Meta` inner class:

```python
@domain.entity(part_of="Order")
class LineItem:
    product_id: String(required=True)
    quantity: Integer(required=True)

    class Meta:
        abstract = False
        auto_add_id_field = True
        schema_name = "order_items"
```

**Decorator vs Meta:**
- Decorator: More concise, preferred for simple cases
- Meta class: Better for multiple options, more readable for complex configurations

## Complete Configuration Example

```python
@domain.entity(
    part_of="Order",
    abstract=False,
    auto_add_id_field=True,
    schema_name="order_line_items"
)
class LineItem:
    """
    A line item in an order.

    Configuration:
    - part_of: "Order" (belongs to Order aggregate)
    - abstract: False (can be instantiated)
    - auto_add_id_field: True (gets automatic 'id' field)
    - schema_name: 'order_line_items' (database table name)
    """
    product_id: String(required=True, max_length=50)
    product_name: String(required=True, max_length=200)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.0)

    @property
    def subtotal(self) -> float:
        return self.quantity * self.unit_price
```

## Custom Identifier Fields

### Using Natural Keys

```python
@domain.entity(part_of="Order", auto_add_id_field=False)
class LineItem:
    # Use line number as identifier
    line_number: Integer(required=True, identifier=True)
    product_id: String(required=True)
    quantity: Integer(required=True)
```

### Composite Keys (Not Recommended)

```python
# Protean doesn't support composite keys directly
# If you need this, reconsider your entity design or use auto ID
```

**Recommendation:** Use auto-generated IDs unless you have a strong business reason for natural keys.

## Inheritance Hierarchies

### Base Entity Pattern

```python
@domain.entity(part_of="Order", abstract=True, auto_add_id_field=False)
class BaseItem:
    """Abstract base for all item types."""
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.0)

    @property
    def subtotal(self) -> float:
        return self.quantity * self.unit_price


@domain.entity(part_of="Order")
class ProductItem(BaseItem):
    """Item representing a physical product."""
    product_id: String(required=True)
    product_name: String(required=True)


@domain.entity(part_of="Order")
class ServiceItem(BaseItem):
    """Item representing a service."""
    service_id: String(required=True)
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
    # - abstract=False
    # - schema_name="line_item"
    product_id: String(required=True)
    quantity: Integer(required=True)
```

### Abstract Base Entity

```python
@domain.entity(part_of="Order", abstract=True)
class BaseItem:
    # Common fields and behavior
    quantity: Integer(required=True)
    unit_price: Float(required=True)
```

### Entity with Custom Schema Name

```python
@domain.entity(part_of="Order", schema_name="order_items")
class LineItem:
    # Stored as 'order_items' instead of 'line_item'
    product_id: String(required=True)
```

### Entity with Natural Key

```python
@domain.entity(part_of="Order", auto_add_id_field=False)
class LineItem:
    line_number: Integer(required=True, identifier=True)
    product_id: String(required=True)
```

## Testing Configuration

```python
def test_entity_configuration():
    """Test that entity configuration is applied correctly."""
    # Get entity metadata
    entity_meta = domain.registry.entities["LineItem"]

    # Verify configuration
    assert entity_meta.cls == LineItem
    assert entity_meta.schema_name == "order_items"
    assert entity_meta.abstract == False

    # Verify fields
    assert "id" in entity_meta.attributes
    assert "product_id" in entity_meta.attributes
```

## Best Practices

1. **Use defaults when possible** - Only customize when necessary
2. **Be explicit about abstract** - Clearly mark abstract entities
3. **Document custom configurations** - Explain why you deviated from defaults
4. **Prefer auto IDs** - Use natural keys only when there's a strong business reason
5. **Keep schema names simple** - Use standard snake_case conventions

## Related

- [Aggregates](../../aggregate/SKILL.md) - Aggregate configuration options
- [Value Objects](../../value-object/SKILL.md) - Value object configuration
- [Anti-patterns](./anti-patterns.md) - Common configuration mistakes
