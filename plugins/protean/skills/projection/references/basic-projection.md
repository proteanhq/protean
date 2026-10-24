# Basic Projection

## Defining a projection

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

Changing an identifier once set raises `InvalidOperationError`. A `String` identifier used as a business key (such as `ssn` above) gets no generated value, so omitting it fails validation with "is required". SKILL.md rule 10 covers which identifier types generate a value.

## Projection properties

```python
inventory = ProductInventory(
    product_id="123", name="Laptop", price=999.99, stock_quantity=50
)
inventory1 = ProductInventory(product_id="123", name="Laptop", price=999.99)
inventory2 = ProductInventory(product_id="123", name="Laptop Pro", price=1299.99)

# Convert to dictionary
inventory.to_dict()
# {'product_id': '123', 'name': 'Laptop', 'price': 999.99, 'stock_quantity': 50, 'last_updated': None}

# String representation
str(inventory)
# "ProductInventory object ({'product_id': '123', ...})"

# Equality (based on identity)
inventory1 == inventory2  # True if same identifier value

# Hashing (based on identity)
hash(inventory)  # Based on identifier field value
```

## Complete example

See [projection_simple.py](../assets/projection_simple.py) for a complete, runnable example.

## Related

- [Configuration Options](configuration-options.md): Provider, cache, and other options
- [Persistence & Querying](persistence-querying.md): How to persist and query projections, and the `state_` flags
- [Field Type Restrictions](field-type-restrictions.md): Why only basic types
- `projector`: Projectors populate projections from domain events
