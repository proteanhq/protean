# Single-Aggregate Projector

## Overview

A single-aggregate projector listens to events from one aggregate and maintains a projection (read model) that represents a query-optimized view of that aggregate's data. This is the most common projector pattern and the foundation of CQRS read-side implementation in Protean.

## When to use

- Building a read-optimized view of a single aggregate's data
- Creating denormalized query models for specific UI views
- Separating read and write models for an aggregate
- Maintaining search indexes or reporting views
- Any scenario where the projection data comes from a single aggregate's events

## Code walkthrough

### The Aggregate and Events

The aggregate defines the write model and raises events when state changes:

```python
@domain.event(part_of="Product")
class ProductAdded:
    product_id: Identifier(required=True)
    name: String(required=True)
    stock_quantity: Integer(required=True)

@domain.aggregate
class Product:
    name: String(required=True)
    stock_quantity: Integer(default=0)

    @classmethod
    def create(cls, name, stock_quantity=0):
        product = cls(name=name, stock_quantity=stock_quantity)
        product.raise_(ProductAdded(
            product_id=product.id, name=name, stock_quantity=stock_quantity
        ))
        return product
```

### The Projection

The projection defines the read-optimized data structure. Projections:
- Must have at least one `identifier` field
- Can only use basic field types (String, Integer, Float, Identifier, DateTime, etc.)
- Cannot use References, Associations, or ValueObjects

```python
@domain.projection
class ProductInventory:
    product_id: Identifier(identifier=True, required=True)
    name: String(required=True)
    stock_quantity: Integer(default=0)
```

### The Projector

The projector bridges events to projections. It:
- Must specify `projector_for` pointing to a registered projection
- Must specify `aggregates` (list of aggregate classes) or `stream_categories`
- Uses `@on(EventClass)` decorator for handler methods

```python
from protean.core.projector import on

@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        repo = domain.repository_for(ProductInventory)
        inventory = ProductInventory(
            product_id=event.product_id,
            name=event.name,
            stock_quantity=event.stock_quantity,
        )
        repo.add(inventory)
```

## How aggregates derive stream categories

When you specify `aggregates=[Product]`, Protean automatically derives the stream category from `Product.meta_.stream_category`. This is equivalent to:

```python
@domain.projector(
    projector_for=ProductInventory,
    stream_categories=[Product.meta_.stream_category],
)
```

Using `aggregates` is preferred for clarity unless you need fine-grained stream control.

## Complete example

See [projector_single_aggregate.py](../assets/projector_single_aggregate.py) for a complete, runnable example.

## Related

- [Cross-Aggregate Projector](cross-aggregate.md) - Projector listening to multiple aggregates
- [Multiple Projectors](multiple-projectors.md) - Multiple projectors for the same events
- [Anti-patterns](anti-patterns.md) - Common mistakes to avoid
- `projection` - Defining projections
- `event` - Events that projectors consume
