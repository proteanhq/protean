# Multiple Projectors

Several projectors can handle the same events, each populating its own projection. One event stream can feed many read models, each shaped for one kind of query.

## The pattern

### Same events, different projections

Each projector listens to the same aggregate's events but updates a different projection. The example uses this aggregate, event, and two projections:

```python
from protean.core.projector import on

@domain.event(part_of="Product")
class ProductAdded:
    product_id: Identifier(required=True)
    name: String(required=True)
    stock_quantity: Integer(required=True)

@domain.aggregate
class Product:
    name: String(required=True)
    stock_quantity: Integer(default=0)

@domain.projection
class ProductInventory:
    product_id: Identifier(identifier=True, required=True)
    name: String(required=True)
    stock_quantity: Integer(default=0)

@domain.projection
class ProductCatalog:
    product_id: Identifier(identifier=True, required=True)
    name: String(required=True)
    in_stock: String(choices=["YES", "NO"])
```

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

`ProductInventory` stores exact quantities for stock management. `ProductCatalog` stores an in-stock flag for browsing.

## Key principles

1. **Independence**: Projectors do not communicate with each other
2. **Failure isolation**: One projector failing doesn't affect others
3. **One projection per projector**: Each projector is associated with exactly one projection via `projector_for`

## When both projectors handle the same event

The event store delivers each event to every projector that listens to its stream. Each projector processes it on its own and updates its own projection. The order in which the projectors run is not guaranteed.

## Complete example

See [projector_multiple_projectors.py](../assets/projector_multiple_projectors.py) for a complete, runnable example showing two projectors maintaining different projections from the same events.

## Related

- [Single-Aggregate Projector](single-aggregate.md): Basic single projector pattern
- [Cross-Aggregate Projector](cross-aggregate.md): Combining data from multiple aggregates
- [Anti-patterns](anti-patterns.md): Common mistakes to avoid
- `projection`: Defining the projections that projectors maintain
