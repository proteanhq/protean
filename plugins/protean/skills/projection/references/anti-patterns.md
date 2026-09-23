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

Error: `` "Projection `UserView` needs to have at least one identifier" ``

## 2. Projection with no projector

A projection needs a projector to populate it. With no projector, nothing writes to the projection, so queries against it always come back empty.

```python
# Wrong! Nothing populates this projection
@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    status: String()
```

**Fix**: Add a projector that handles the aggregate's events and writes the projection. When a subscriber fills the projection from outside the domain, mark it `externally_populated=True` instead:

```python
@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    @on(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        repo = current_domain.repository_for(OrderSummary)
        repo.add(OrderSummary(order_id=event.order_id, status="PLACED"))

# OR, when a subscriber fills it from an external stream:
@domain.projection(externally_populated=True)
class OrderSummary:
    order_id: Identifier(identifier=True)
    status: String()
```

`check` reports `PROJECTION_WITHOUT_PROJECTOR` for a projection no projector writes and that is not marked `externally_populated`.

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

## 9. Projection field no projector writes

Every projection field should be written by a projector method. A field no projector fills is a dead column: it shows in the read model and carries a type, but nothing ever sets it.

```python
@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    status: String()
    customer_email: String()   # No projector method ever writes this

@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    @on(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        repo = current_domain.repository_for(OrderSummary)
        repo.add(OrderSummary(order_id=event.order_id, status="PLACED"))
```

**Fix**: Write the field from the projector method that handles the event carrying it, or drop the field when nothing sources it:

```python
    @on(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        repo = current_domain.repository_for(OrderSummary)
        repo.add(
            OrderSummary(
                order_id=event.order_id,
                status="PLACED",
                customer_email=event.customer_email,
            )
        )
```

`check` reports `UNSOURCED_PROJECTION_FIELD` for such a field. It reads what projector methods write, so it is advisory: a field filled only through a helper or a dict splat the check cannot follow can still be flagged.

## 10. Reading a projection with the wrong accessor

Read a projection through `view_for(Projection)`, which returns a read-only view with `get()`, `query`, `find_by()`, `count()`, and `exists()`. Use `connection_for(Projection)` for the raw store connection. Both require a projection; passing an element of another type raises `IncorrectUsageError`.

```python
# Wrong! Order is an aggregate, so view_for rejects it
view = current_domain.view_for(Order)
```

**Fix**: Call the accessor with a projection, or use the accessor that matches the element's type:

```python
view = current_domain.view_for(OrderSummary)
order = view.get("order-123")
shipped = view.query.filter(status="shipped").all()
```

`check` reports `USAGE_NOT_A_PROJECTION` when `view_for` or `connection_for` is given a non-projection.

## Related

- [Basic Projection](basic-projection.md) - Correct basic pattern
- [Field Type Restrictions](field-type-restrictions.md) - Detailed field type rules
- [Configuration Options](configuration-options.md) - Correct configuration
