# Projection Persistence & Querying

## Overview

Projections are designed to be persisted and queried efficiently. They use the repository pattern for CRUD operations, just like aggregates. However, projections are typically populated by projectors (event handlers) rather than directly by application code.

## Persisting projections

### Creating a projection record

```python
inventory = ProductInventory(
    product_id="PROD-001",
    name="Laptop",
    price=999.99,
    stock_quantity=50,
)
domain.repository_for(ProductInventory).add(inventory)
```

### Updating a projection record

```python
inventory = domain.repository_for(ProductInventory).get("PROD-001")
inventory.stock_quantity = 45
domain.repository_for(ProductInventory).add(inventory)
```

### Deleting a projection record

```python
inventory = domain.repository_for(ProductInventory).get("PROD-001")
domain.repository_for(ProductInventory).remove(inventory)
```

## Querying projections

### Get by identifier

```python
inventory = domain.repository_for(ProductInventory).get("PROD-001")
```

### Query with DAO

```python
# Find by a specific field
inventory = domain.repository_for(ProductInventory)._dao.find_by(product_id="PROD-001")

# Query all records
all_items = domain.repository_for(ProductInventory)._dao.query.all()
```

## Projection state tracking

Projections track their persistence state via the `state_` attribute:

```python
# New projection (not yet persisted)
inventory = ProductInventory(product_id="PROD-001", name="Laptop", price=999.99)
assert inventory.state_.is_new is True

# After persisting
domain.repository_for(ProductInventory).add(inventory)
# State transitions to persisted
```

## Typical workflow: Projectors populate projections

In practice, projections are populated by projectors in response to domain events:

```python
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        repo = domain.repository_for(ProductInventory)
        inventory = ProductInventory(
            product_id=event.product_id,
            name=event.name,
            price=event.price,
            stock_quantity=event.stock_quantity,
        )
        repo.add(inventory)
```

See `projector` skill for full projector documentation.

## Complete example

See [projection_persistence.py](../assets/projection_persistence.py) for a complete, runnable example.

## Related

- [Basic Projection](basic-projection.md) - Defining projections
- [Configuration Options](configuration-options.md) - Storage and query configuration
- `projector` - Projectors that populate projections
