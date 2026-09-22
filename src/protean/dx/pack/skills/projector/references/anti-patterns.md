# Projector Anti-Patterns

## 1. Missing projector_for

```python
# Wrong! Projector must be associated with a projection
@domain.projector(aggregates=[Product])
class MyProjector:
    pass
```

**Fix**: Always specify `projector_for`:

```python
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class MyProjector:
    pass
```

Protean raises `IncorrectUsageError: Projector 'MyProjector' needs to be associated with a Projection`.

## 2. Missing aggregates and stream_categories

```python
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

Protean raises `IncorrectUsageError: Projector 'MyProjector' needs to be associated with at least one Aggregate or Stream Category`.

## 3. Projection not registered with domain

```python
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
class ProductInventory:
    product_id: Identifier(identifier=True)
```

Protean raises `IncorrectUsageError: 'UnregisteredProjection' is not a Projection, or is not registered in domain`.

## 4. Using References or Associations in projections

```python
# Wrong! Projections reject References and Associations (HasOne/HasMany)
@domain.projection
class OrderView:
    customer = Reference(Customer)
    items = HasMany(OrderItem)
```

Basic field types and `ValueObject` fields are allowed; a `ValueObject` is
stored as flattened shadow fields.

**Fix**: Flatten related data into basic field types:

```python
@domain.projection
class OrderView:
    order_id: Identifier(identifier=True)
    customer_name: String()
    customer_email: String()
    item_count: Integer()
    total_amount: Float()
    shipping_city: String()
    shipping_zip: String()
```

## 5. Business logic in projector methods

```python
# Wrong! Projectors should not contain business logic
@on(OrderPlaced)
def on_order_placed(self, event):
    if event.total > 1000:
        # Business rule: apply discount for large orders
        event.total *= 0.9
    ...
```

**Fix**: Keep business logic in aggregates. Projectors only transform and store data:

```python
@on(OrderPlaced)
def on_order_placed(self, event):
    # Just project the data as-is
    summary = OrderSummary(
        order_id=event.order_id,
        total=event.total,  # Discount already applied by aggregate
    )
    domain.repository_for(OrderSummary).add(summary)
```

## 6. Using @handle instead of @on

```python
# Works but not idiomatic for projectors
from protean import handle

@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class MyProjector:
    @handle(ProductAdded)  # Use @on instead
    def on_product_added(self, event):
        ...
```

**Fix**: Use `@on` from `protean.core.projector`:

```python
from protean.core.projector import on

@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class MyProjector:
    @on(ProductAdded)  # Idiomatic for projectors
    def on_product_added(self, event):
        ...
```

`@on` is an alias for `@handle` but is the conventional decorator for projectors.

## 7. Decorating with non-Event classes

```python
from protean.core.projector import on

@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class MyProjector:
    @on(SomeCommand)  # Wrong! Projectors handle events, not commands
    def on_some_command(self, event):
        ...
```

**Fix**: Only use `@on` with Event classes. Projectors respond to domain events.

Protean raises `IncorrectUsageError: Projector method 'on_some_command' in 'MyProjector' is not associated with an event`.

## 8. Manually wrapping in UnitOfWork

```python
@on(ProductAdded)
def on_product_added(self, event):
    with UnitOfWork():  # Unnecessary! Already implicit
        inventory = ProductInventory(...)
        domain.repository_for(ProductInventory).add(inventory)
```

**Fix**: Let the implicit UnitOfWork handle persistence:

```python
@on(ProductAdded)
def on_product_added(self, event):
    inventory = ProductInventory(...)
    domain.repository_for(ProductInventory).add(inventory)
```

## 9. Handling an event the domain does not register

A projector may only handle events the domain registers. A handler keyed on an event that no longer exists is wired to a type that can never be dispatched, usually a stale reference left after the event was renamed or removed.

```python
# Wrong! ProductRenamed was removed from the domain, but the handler stays
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class InventoryProjector:
    @on(ProductAdded)
    def on_added(self, event):
        ...

    @on(ProductRenamed)   # Orphaned: ProductRenamed is not registered
    def on_renamed(self, event):
        ...
```

**Fix**: Register the event with the domain, or remove the handler for the orphaned type from the projector:

```python
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class InventoryProjector:
    @on(ProductAdded)
    def on_added(self, event):
        ...
```

`check` reports `PROJECTOR_HANDLES_ORPHANED_EVENT` for a projector whose handler keys on an event the domain does not register.

## Related

- [Single-Aggregate Projector](single-aggregate.md) - Correct basic pattern
- [Cross-Aggregate Projector](cross-aggregate.md) - Correct cross-aggregate pattern
- [Error Handling](error-handling.md) - Proper error handling patterns
