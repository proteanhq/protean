# Projector Anti-Patterns

The examples on this page use this aggregate, event, and projection:

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
```

## 1. Missing projector_for

```python
# fragment
# Wrong! Projector must be associated with a projection
@domain.projector(aggregates=[Product])
class MyProjector:
    pass
```

**Fix**: Specify `projector_for`:

```python
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class MyProjector:
    pass
```

Protean raises ``IncorrectUsageError: Projector `MyProjector` needs to be associated with a Projection``.

## 2. Missing aggregates and stream_categories

```python
# fragment
# Wrong! No event source specified
@domain.projector(projector_for=ProductInventory)
class MyProjector:
    pass
```

**Fix**: Specify at least `aggregates` or `stream_categories`:

```python
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class MyProjector:
    pass
```

Protean raises ``IncorrectUsageError: Projector `MyProjector` needs to be associated with at least one Aggregate or Stream Category``.

## 3. Projection not registered with domain

```python
# fragment
# Wrong! Projection class not decorated with @domain.projection
class UnregisteredProjection:
    product_id: Identifier(identifier=True)

@domain.projector(projector_for=UnregisteredProjection, aggregates=[Product])
class MyProjector:
    pass
```

**Fix**: Register the projection with the domain:

```python
@domain.projection
class UnregisteredProjection:
    product_id: Identifier(identifier=True)
```

Protean raises ``IncorrectUsageError: `UnregisteredProjection` is not a Projection, or is not registered in domain <name>``.

## 4. Using References or Associations in projections

```python
# fragment
# Wrong! Projections reject References and Associations (HasOne/HasMany)
@domain.projection
class OrderView:
    customer = Reference(Customer)
    items = HasMany(OrderItem)
```

**Fix**: Flatten related data into basic field types:

```python
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    customer_name: String()
    customer_email: String()
    item_count: Integer()
    total_amount: Decimal(precision=19, scale=4)
    shipping_city: String()
    shipping_zip: String()
```

## 5. Business logic in projector methods

```python
# fragment
from decimal import Decimal as D

# Wrong! Projectors should not contain business logic
@on(OrderPlaced)
def on_order_placed(self, event):
    if event.total > 1000:
        # Business rule: apply discount for large orders
        event.total *= D("0.9")
    ...
```

**Fix**: Keep business logic in aggregates. Projectors only transform and store data:

```python
# fragment
@on(OrderPlaced)
def on_order_placed(self, event):
    # Just project the data as-is
    summary = OrderSummary(
        order_id=event.order_id,
        total=event.total,  # Discount already applied by aggregate
    )
    domain.repository_for(OrderSummary).add(summary)
```

## 6. Decorating with non-Event classes

```python
# fragment
from protean.core.projector import on

@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class MyProjector:
    @on(SomeCommand)  # Wrong! Projectors handle events, not commands
    def on_some_command(self, event):
        ...
```

**Fix**: Only use `@on` with Event classes. Projectors respond to domain events.

Protean raises ``IncorrectUsageError: Projector method `on_some_command` in `MyProjector` is not associated with an event``.

## 7. Manually wrapping in UnitOfWork

```python
# fragment
@on(ProductAdded)
def on_product_added(self, event):
    with UnitOfWork():  # Unnecessary! Already implicit
        inventory = ProductInventory(...)
        domain.repository_for(ProductInventory).add(inventory)
```

**Fix**: Let the implicit UnitOfWork handle persistence:

```python
# fragment
@on(ProductAdded)
def on_product_added(self, event):
    inventory = ProductInventory(...)
    domain.repository_for(ProductInventory).add(inventory)
```

## Related

- [Single-Aggregate Projector](single-aggregate.md): Correct basic pattern
- [Cross-Aggregate Projector](cross-aggregate.md): Correct cross-aggregate pattern
- [Error Handling](error-handling.md): Error handling patterns
