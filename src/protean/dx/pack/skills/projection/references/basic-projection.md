# Basic Projection

## Overview

A projection (a.k.a. read model) is a denormalized, query-optimized data structure that lives on the read side of CQRS. Unlike aggregates, which enforce business rules and maintain consistency boundaries, projections are designed purely for efficient querying. They are closer to the database than domain logic and represent flattened, tailored views of data.

## When to use

- Defining a read-optimized schema for a specific UI view or API response
- Creating a flattened representation of data that spans aggregate boundaries
- Building query models that avoid complex joins
- Separating the read model from the write model for scalability

## Defining a projection

Use the `@domain.projection` decorator:

```python
from protean import Domain
from protean.fields import DateTime, Float, Identifier, Integer, String

domain = Domain()

@domain.projection
class ProductInventory:
    product_id: Identifier(identifier=True, required=True)
    name: String(max_length=100, required=True)
    price: Float(required=True)
    stock_quantity: Integer(default=0)
    last_updated: DateTime()
```

### Key requirements

1. **Identifier field**: Every non-abstract projection must have at least one field with `identifier=True`
2. **Basic field types only**: String, Integer, Float, Identifier, DateTime, Date, Text, Boolean, Auto
3. **No complex types**: References, Associations (HasOne, HasMany), and ValueObjects are not allowed

## Identifier field

The identifier field serves as the primary key for the projection. It can be:

- **Identifier type** (most common):
  ```python
  product_id: Identifier(identifier=True, required=True)
  ```

- **Auto type** (auto-generated):
  ```python
  id: Auto(identifier=True)
  ```

- **String type** (explicit business key):
  ```python
  ssn: String(max_length=36, identifier=True)
  ```

Important properties:
- Identifier values are **immutable** once set (raises `InvalidOperationError` on change)
- Identifier values are **mandatory** for non-abstract projections (raises `ValidationError` if missing)

## Projection properties

Projections support several useful properties:

```python
# Convert to dictionary
inventory.to_dict()
# {'product_id': '123', 'name': 'Laptop', 'price': 999.99, 'stock_quantity': 50}

# String representation
str(inventory)
# "ProductInventory object ({'product_id': '123', ...})"

# Equality (based on identity)
inventory1 == inventory2  # True if same identifier value

# Hashing (based on identity)
hash(inventory)  # Based on identifier field value
```

## Projection state

Projections track their persistence state:

```python
inventory = ProductInventory(product_id="123", name="Laptop", price=999.99)
inventory.state_.is_new  # True - not yet persisted
```

## Complete example

See [projection_simple.py](../assets/projection_simple.py) for a complete, runnable example.

## Related

- [Configuration Options](configuration-options.md) - Provider, cache, and other options
- [Persistence & Querying](persistence-querying.md) - How to persist and query projections
- [Field Type Restrictions](field-type-restrictions.md) - Why only basic types
- `projector` - Projectors populate projections from domain events
