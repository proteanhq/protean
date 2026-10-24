# Entity Configuration

Entities are configured through options passed to the `@domain.entity` decorator.

## Configuration Options

### `part_of` (Required)

Associates the entity with an aggregate. This is the only required configuration option.

**Use a string reference to the aggregate** to avoid circular dependencies. A nested entity's `part_of` is its parent entity, as a class or a string (see [Nested Entities](nested-entities.md)).

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

**Important:**
- If disabled, you MUST provide a field with `identifier=True`
- Only one field can be marked as the identifier. Protean does not support composite keys.
- Use the auto-generated `id` unless you have a strong business reason for a natural key such as `line_number`.

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

**Important:**
- Register the model with `@domain.database_model(part_of=<Entity>)`.
- Every column must match a field declared on the entity. A column for anything
  else is rejected at registration with `IncorrectUsageError`.
- Custom models are provider-specific (a SQLAlchemy model won't work with
  Elasticsearch).

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

## Related

- [Aggregates](../../aggregate/SKILL.md): Aggregate configuration options
- [Value Objects](../../value-object/SKILL.md): Value object configuration
- [Anti-patterns](./anti-patterns.md): Common configuration mistakes
