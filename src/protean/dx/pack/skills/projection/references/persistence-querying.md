# Projection Persistence & Querying

## Overview

Projections are designed to be persisted and queried efficiently. They use the repository pattern for CRUD operations, just like aggregates. However, projections are typically populated by projectors (event handlers) rather than directly by application code.

## Persisting projections

The examples below use this projection:

```python
@domain.projection
class ProductInventory:
    product_id: Identifier(identifier=True, required=True)
    name: String(max_length=100, required=True)
    price: Float(required=True)
    stock_quantity: Integer(default=0)

domain.init(traverse=False)
```

### Creating a projection record

```python
with domain.domain_context():
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
with domain.domain_context():
    inventory = domain.repository_for(ProductInventory).get("PROD-001")
    inventory.stock_quantity = 45
    domain.repository_for(ProductInventory).add(inventory)
```

### Deleting a projection record

Repositories have no `remove()` method. Delete projection records with a query. `delete()` returns the number of records it deleted:

```python
with domain.domain_context():
    repo = domain.repository_for(ProductInventory)
    deleted = repo.query.filter(product_id="PROD-001").delete()
    assert deleted == 1
```

## Querying projections

### Get by identifier

```python
with domain.domain_context():
    domain.repository_for(ProductInventory).add(
        ProductInventory(product_id="PROD-001", name="Laptop", price=999.99)
    )
    inventory = domain.repository_for(ProductInventory).get("PROD-001")
```

### Query with the repository

```python
with domain.domain_context():
    # Find by a specific field
    inventory = domain.repository_for(ProductInventory).find_by(name="Laptop")

    # Query all records
    all_items = domain.repository_for(ProductInventory).query.all()
```

## Projection state tracking

Projections track their persistence state via the `state_` attribute:

```python
with domain.domain_context():
    # New projection (not yet persisted)
    inventory = ProductInventory(product_id="PROD-002", name="Mouse", price=19.99)
    assert inventory.state_.is_new is True

    # After persisting
    domain.repository_for(ProductInventory).add(inventory)
    assert inventory.state_.is_persisted is True
```

## Typical workflow: Projectors populate projections

In practice, projections are populated by projectors in response to domain events:

```python
from protean.core.projector import on


@domain.aggregate
class Product:
    name: String(max_length=100, required=True)
    price: Float(required=True)
    stock_quantity: Integer(default=0)


@domain.event(part_of=Product)
class ProductAdded:
    product_id: Identifier(required=True)
    name: String(required=True)
    price: Float(required=True)
    stock_quantity: Integer()


@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        repo = current_domain.repository_for(ProductInventory)
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
