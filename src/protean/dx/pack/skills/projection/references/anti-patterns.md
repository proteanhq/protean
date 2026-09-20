# Projection Anti-Patterns

## 1. Missing identifier field

```python
# Wrong! No identifier field
@domain.projection
class UserView:
    name: String()
    email: String()
```

**Fix**: Add at least one field with `identifier=True`:

```python
@domain.projection
class UserView:
    user_id: Identifier(identifier=True)
    name: String()
    email: String()
```

Error: `"Projection 'UserView' needs to have at least one identifier"`

## 2. Using ValueObject fields

```python
# Wrong! ValueObject not allowed in projections
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    amount = ValueObject(Money)
```

**Fix**: Flatten ValueObject fields:

```python
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    amount_value: Float()
    amount_currency: String()
```

Error: `"Projections can only contain basic field types. Remove amount (ValueObject) from class OrderView"`

## 3. Using Reference fields

```python
# Wrong! References not allowed
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    customer = Reference(Customer)
```

**Fix**: Store the referenced entity's relevant data as basic fields:

```python
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    customer_id: Identifier()
    customer_name: String()
```

## 4. Using Association fields

```python
# Wrong! Associations not allowed
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    items = HasMany(OrderItem)
```

**Fix**: Denormalize collection data:

```python
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    item_count: Integer()
    total_amount: Float()
```

## 5. No storage backend

```python
# Wrong! Must have either provider or cache
domain.register(MyProjection, provider=None, cache=None)
```

**Fix**: Always have at least one storage backend:

```python
@domain.projection  # Uses default provider
class MyProjection:
    ...

# OR explicitly set cache
@domain.projection(cache="redis")
class MyProjection:
    ...
```

Error: `"MyProjection projection needs to have either a database or a cache provider"`

## 6. Putting business logic in projections

```python
# Wrong! Projections are read-only data containers
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    total: Float()

    def apply_discount(self, percentage):
        self.total *= (1 - percentage / 100)
```

**Fix**: Business logic belongs in aggregates. Projections should only have data fields and optional `defaults()`:

```python
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    total: Float()           # Already includes discount, applied by aggregate
    discount_applied: Float()  # Track the discount for display purposes
```

## 7. Treating projections as aggregates

```python
# Wrong! Don't use projections as write models
@domain.projection
class Product:
    product_id: Identifier(identifier=True)
    name: String()
    stock: Integer()

# Don't write business logic that operates on projections
def place_order(product_id, quantity):
    product = domain.repository_for(Product).get(product_id)
    product.stock -= quantity  # Don't do this!
    domain.repository_for(Product).add(product)
```

**Fix**: Use aggregates for write operations. Projections are for reading only:

```python
# Write side: use aggregate
@domain.aggregate
class Product:
    name: String()
    stock: Integer()

    def reduce_stock(self, quantity):
        self.stock -= quantity
        self.raise_(StockReduced(...))

# Read side: projection populated by projector
@domain.projection
class ProductView:
    product_id: Identifier(identifier=True)
    name: String()
    stock: Integer()
```

## 8. Modifying identifier values

```python
inventory = ProductInventory(product_id="PROD-001", name="Laptop")
inventory.product_id = "PROD-002"  # Wrong! Raises InvalidOperationError
```

**Fix**: Identifiers are immutable once set. Create a new projection record instead.

## Related

- [Basic Projection](basic-projection.md) - Correct basic pattern
- [Field Type Restrictions](field-type-restrictions.md) - Detailed field type rules
- [Configuration Options](configuration-options.md) - Correct configuration
