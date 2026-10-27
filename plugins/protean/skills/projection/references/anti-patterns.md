# Projection Anti-Patterns

## 1. Missing identifier field

```python
# fragment
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

```python
# fragment
# Wrong! Nothing populates this projection
@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    status: String()
```

**Fix**: Add a projector that handles the aggregate's events and writes the projection:

```python
from protean.core.projector import on


@domain.aggregate
class Order:
    customer_email: String()


@domain.event(part_of=Order)
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_email: String()


@domain.projection
class OrderSummary:
    order_id: Identifier(identifier=True)
    status: String()


@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    @on(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        repo = current_domain.repository_for(OrderSummary)
        repo.add(OrderSummary(order_id=event.order_id, status="PLACED"))
```

When a subscriber fills the projection from an external stream, mark it `externally_populated=True` instead of adding a projector:

```python
@domain.projection(externally_populated=True)
class PartnerOrderSummary:
    order_id: Identifier(identifier=True)
    status: String()
```

`check` reports `PROJECTION_WITHOUT_PROJECTOR` for a projection no projector writes and that is not marked `externally_populated`.

## 3. Putting business logic in projections

```python
# fragment
# Wrong! Projections are read-only data containers
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    total: Decimal(precision=19, scale=4)

    def apply_discount(self, percentage):
        self.total *= (1 - percentage / 100)
```

**Fix**: Keep the logic in the aggregate. A projection holds data fields and an optional `defaults()`:

```python
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    total: Decimal(precision=19, scale=4)  # Already includes discount, applied by aggregate
    discount_applied: Decimal(precision=19, scale=4)  # Track the discount for display purposes
```

## 4. Treating projections as aggregates

```python
# fragment
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

**Fix**: Change state through the aggregate, and let a projector update the projection:

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

## 5. Modifying identifier values

```python
# fragment
inventory = ProductInventory(product_id="PROD-001", name="Laptop")
inventory.product_id = "PROD-002"  # Wrong! Raises InvalidOperationError
```

**Fix**: Create a new projection record. The error message is "Identifiers cannot be changed once set".

## 6. Projection field no projector writes

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
# fragment
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

## 7. Reading a projection with the wrong accessor

Read a projection through `view_for(Projection)`, which returns a read-only view with `get()`, `query`, `find_by()`, `count()`, and `exists()`. Use `connection_for(Projection)` for the raw store connection. Both require a projection; passing an element of another type raises `IncorrectUsageError`.

```python
# fragment
# Wrong! Order is an aggregate, so view_for rejects it
view = current_domain.view_for(Order)
```

**Fix**: Call the accessor with a projection, or use the accessor that matches the element's type:

```python
domain.init(traverse=False)

with domain.domain_context():
    current_domain.repository_for(OrderSummary).add(
        OrderSummary(order_id="order-123", status="shipped")
    )

    view = current_domain.view_for(OrderSummary)
    order = view.get("order-123")
    shipped = view.query.filter(status="shipped").all()
```

Giving `view_for` or `connection_for` a non-projection raises `IncorrectUsageError` with the code `USAGE_NOT_A_PROJECTION` when the call runs. `check` does not report it.

## Related

- [Basic Projection](basic-projection.md): Correct basic pattern
- [Field Type Restrictions](field-type-restrictions.md): Detailed field type rules
- [Configuration Options](configuration-options.md): Correct configuration
