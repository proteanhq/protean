---
name: projector
description: Define a Protean projector - a specialized event handler that maintains read-optimized projections (read models) by listening to domain events from one or more aggregates. Projectors are always associated with a projection via projector_for and use the @on decorator (alias for @handle) to process specific event types. Unlike generic event handlers, projectors explicitly target a projection and can listen to multiple stream categories or aggregates. Use when you need to build a read model, maintain a projection, create a denormalized view, sync query-side data from domain events, build cross-aggregate views, or when the user asks to "create a projector", "add a projection handler", "build a read model", "maintain a query view", "project events into a read model", "create a CQRS read side", or "populate a projection".
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
  diagnostic_codes:
    - PROJECTOR_HANDLES_ORPHANED_EVENT
---

# Projector

## How projectors differ from event handlers

| Aspect | Event Handler | Projector |
|--------|--------------|-----------|
| **Purpose** | Orchestrate side effects (notifications, syncing) | Maintain read-optimized projections |
| **Association** | `part_of=Aggregate` | `projector_for=Projection` |
| **Decorator** | `@handle(EventClass)` | `@on(EventClass)` (alias for `@handle`) |
| **Target** | Updates aggregates | Updates projections (read models) |
| **Event source** | `stream_category` | `aggregates` or `stream_categories` |
| **Import** | `from protean import handle` | `from protean.core.projector import on` |

## Basic structure

```python
from protean import Domain
from protean.core.projector import on
from protean.fields import Identifier, Integer, String

domain = Domain()
domain.config["event_processing"] = "sync"

@domain.event(part_of="Product")
class ProductAdded:
    product_id: Identifier(required=True)
    name: String(required=True)
    stock_quantity: Integer(required=True)

@domain.aggregate
class Product:
    name: String(required=True)
    stock_quantity: Integer(default=0)

    @classmethod
    def create(cls, name, stock_quantity=0):
        product = cls(name=name, stock_quantity=stock_quantity)
        product.raise_(ProductAdded(
            product_id=product.id, name=name, stock_quantity=stock_quantity
        ))
        return product

@domain.projection
class ProductInventory:
    product_id: Identifier(identifier=True, required=True)
    name: String(required=True)
    stock_quantity: Integer(default=0)

@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        repo = domain.repository_for(ProductInventory)
        inventory = ProductInventory(
            product_id=event.product_id,
            name=event.name,
            stock_quantity=event.stock_quantity,
        )
        repo.add(inventory)
```

## Key rules

1. **projector_for required** - Projector must be associated with a projection: `@domain.projector(projector_for=MyProjection, ...)`
2. **aggregates or stream_categories required** - Must specify event source: `aggregates=[Product]` or `stream_categories=["product"]`
3. **Use @on decorator** - Each handler method is decorated with `@on(EventClass)` (imported from `protean.core.projector`)
4. **Handler methods take self and event** - Signature: `def method_name(self, event: EventClass)`
5. **No return values** - Projector methods do NOT return values (CQRS pattern)
6. **Implicit UnitOfWork** - Each handler method runs within a UnitOfWork context automatically
7. **Multiple projectors per event** - Different projectors can process the same event into different projections
8. **Import on from protean.core.projector** - `from protean.core.projector import on` (not from protean directly)
9. **Projections reject References and Associations** - `Reference` and Associations (`HasOne`/`HasMany`) are not allowed; basic field types and `ValueObject` fields are allowed (a `ValueObject` is stored as flattened shadow fields)
10. **Idempotency** - Design projector methods to handle duplicate events gracefully

## Projector options

| Option | Purpose | Required |
|--------|---------|----------|
| `projector_for` | The projection class this projector maintains | Yes |
| `aggregates` | List of aggregate classes whose events to listen to | Yes (unless stream_categories provided) |
| `stream_categories` | List of stream category names to listen to | Yes (unless aggregates provided) |

## Quick example: Multiple events in one projector

```python
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        repo = domain.repository_for(ProductInventory)
        inventory = ProductInventory(
            product_id=event.product_id, name=event.name,
            stock_quantity=event.stock_quantity,
        )
        repo.add(inventory)

    @on(StockAdjusted)
    def on_stock_adjusted(self, event: StockAdjusted):
        repo = domain.repository_for(ProductInventory)
        inventory = repo.get(event.product_id)
        inventory.stock_quantity = event.new_stock_quantity
        repo.add(inventory)
```

## Quick example: Cross-aggregate projector

```python
@domain.projector(
    projector_for=Balances,
    aggregates=[User, Transaction],
)
class TransactionProjector:
    @on(Registered)
    def on_registered(self, event: Registered):
        balance = Balances(user_id=event.user_id, name=event.name, balance=0)
        domain.repository_for(Balances).add(balance)

    @on(Transacted)
    def on_transacted(self, event: Transacted):
        balance = domain.repository_for(Balances).get(event.user_id)
        balance.balance += event.amount
        domain.repository_for(Balances).add(balance)
```

## Quick example: Multiple projectors for same event

```python
@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class ProductInventoryProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        # Populate detailed inventory projection
        ...

@domain.projector(projector_for=ProductCatalog, aggregates=[Product])
class ProductCatalogProjector:
    @on(ProductAdded)
    def on_product_added(self, event: ProductAdded):
        # Populate simplified catalog projection
        ...
```

## Quick example: Using stream_categories

```python
@domain.projector(
    projector_for=SystemMetrics,
    stream_categories=["user", "order", "payment"],
)
class SystemMetricsProjector:
    @on(UserRegistered)
    def on_user_registered(self, event):
        ...
```

## Common mistakes

### Missing projector_for

```python
@domain.projector(aggregates=[Product])  # Wrong! Missing projector_for
class MyProjector:
    pass
```

Instead: Always specify projector_for

```python
@domain.projector(projector_for=ProductInventory, aggregates=[Product])  # Correct!
class MyProjector:
    pass
```

### Missing aggregates and stream_categories

```python
@domain.projector(projector_for=ProductInventory)  # Wrong! No event source
class MyProjector:
    pass
```

Instead: Always specify at least aggregates or stream_categories

### Using @handle instead of @on

```python
from protean import handle  # Wrong import for projectors

@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class MyProjector:
    @handle(ProductAdded)  # Works but not idiomatic
    def on_product_added(self, event):
        ...
```

Instead: Use @on from protean.core.projector (it's an alias for @handle but reads better in projector context)

```python
from protean.core.projector import on  # Correct!

@domain.projector(projector_for=ProductInventory, aggregates=[Product])
class MyProjector:
    @on(ProductAdded)  # Idiomatic for projectors
    def on_product_added(self, event):
        ...
```

### Using references or associations in projections

```python
@domain.projection
class OrderView:
    customer = Reference(Customer)  # Wrong! No references in projections
    items = HasMany(OrderItem)      # Wrong! No associations
```

Instead: Flatten references and associations into basic field types (String, Integer, Float, Identifier, DateTime, etc.). ValueObject fields are allowed. They persist as flattened shadow fields.

### Projection not registered with domain

```python
class MyProjection:  # Wrong! Not registered with domain
    product_id: Identifier(identifier=True)

@domain.projector(projector_for=MyProjection, aggregates=[Product])
class MyProjector:
    pass
```

Instead: Register projection with `@domain.projection` decorator

## Detailed references

### Core Concepts
- [Single-Aggregate Projector](references/single-aggregate.md) - Projector that listens to one aggregate's events
- [Cross-Aggregate Projector](references/cross-aggregate.md) - Projector combining events from multiple aggregates
- [Multiple Projectors](references/multiple-projectors.md) - Multiple projectors handling the same events
- [Error Handling](references/error-handling.md) - Error handling patterns for projectors
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Single-Aggregate Projector](assets/projector_single_aggregate.py) - Basic projector with one aggregate
- [Multiple Events Projector](assets/projector_multiple_events.py) - Projector handling create and update events
- [Cross-Aggregate Projector](assets/projector_cross_aggregate.py) - Projector combining data from multiple aggregates
- [Multiple Projectors](assets/projector_multiple_projectors.py) - Two projectors maintaining different projections
- [Error Handling](assets/projector_error_handling.py) - Error handling with handle_error classmethod

### Related Skills
- `event` - Events are the input to projectors
- `aggregate` - Aggregates produce the events that projectors consume
- `event-handler` - Generic event handlers (compare/contrast with projectors)
- `projection` - Projections are the output that projectors maintain
- `patterns/cqrs` - Projectors implement the query side of CQRS

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
