# Multiple Projectors

## Overview

Multiple projectors can handle the same events and populate their own independent projections. This is a fundamental CQRS pattern: a single domain event stream can feed multiple read models, each optimized for a specific query use case.

## When to use

- Building multiple views of the same data (e.g., inventory detail + catalog browse)
- Creating specialized read models for different consumers (API, UI, reporting)
- Maintaining both a detailed and a summarized view from the same events
- Separating concerns: each projector focuses on one projection's needs

## The pattern

### Same events, different projections

Each projector listens to the same aggregate's events but updates a different projection:

```python
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        # Creates detailed inventory record
        inventory = ProductInventory(
            product_id=event.product_id,
            name=event.name,
            stock_quantity=event.stock_quantity,
        )
        domain.repository_for(ProductInventory).add(inventory)

@domain.projector(projector_for=ProductCatalog, aggregates=[Product])
class ProductCatalogProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        # Creates simplified catalog entry
        entry = ProductCatalog(
            product_id=event.product_id,
            name=event.name,
            in_stock="YES" if event.stock_quantity > 0 else "NO",
        )
        domain.repository_for(ProductCatalog).add(entry)
```

### Different data transformations

Each projector transforms the event data differently to suit its projection's purpose:
- **ProductInventory**: Stores exact quantities for stock management
- **ProductCatalog**: Stores simplified in-stock flag for browsing

## Key principles

1. **Independence**: Each projector is completely independent - they don't communicate with each other
2. **Different schemas**: Each projection can have different fields and structures
3. **Different update logic**: Each projector can transform the same event data differently
4. **Failure isolation**: One projector failing doesn't affect others
5. **One projection per projector**: Each projector is associated with exactly one projection via `projector_for`

## When both projectors handle the same event

When a domain event is published:
1. The event store delivers it to ALL registered projectors that listen to that stream
2. Each projector processes the event independently
3. Each projector updates its own projection
4. The order of projector execution is not guaranteed

## Complete example

See [projector_multiple_projectors.py](../assets/projector_multiple_projectors.py) for a complete, runnable example showing two projectors maintaining different projections from the same events.

## Related

- [Single-Aggregate Projector](single-aggregate.md) - Basic single projector pattern
- [Cross-Aggregate Projector](cross-aggregate.md) - Combining data from multiple aggregates
- [Anti-patterns](anti-patterns.md) - Common mistakes to avoid
- `projection` - Defining the projections that projectors maintain
