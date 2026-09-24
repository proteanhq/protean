# Unit of Work

Each command handler method in Protean automatically runs within a UnitOfWork context, providing transactional safety for aggregate persistence.

## Overview

The `@handle` decorator wraps every handler method call in a UnitOfWork. This means:

- All changes within a handler method are treated as a single atomic transaction
- If an error occurs, all changes are rolled back
- You do NOT need to manually wrap handler logic in `with UnitOfWork():`

## How It Works

The `@handle` decorator in Protean's source automatically wraps the handler method:

```python
# This is what Protean does internally (simplified)
class handle:
    def __call__(self, fn):
        @functools.wraps(fn)
        def wrapper(instance, target_obj):
            with UnitOfWork():
                return fn(instance, target_obj)
        return wrapper
```

So when you write:

```python
@handle(PlaceOrder)
def handle_place_order(self, command: PlaceOrder):
    order = Order(order_id=command.order_id)
    order.place()
    domain.repository_for(Order).add(order)
```

Protean effectively executes:

```python
with UnitOfWork():
    order = Order(order_id=command.order_id)
    order.place()
    domain.repository_for(Order).add(order)
```

## Scope

The UnitOfWork applies to the **aggregate cluster** -- the aggregate root and all its enclosed entities and value objects. It does NOT span multiple aggregate roots.

This means:
- Persisting one aggregate root and its children is atomic
- You should NOT try to persist multiple different aggregate roots in a single handler
- Cross-aggregate coordination should use domain events

## Do NOT Wrap Manually

Since the UnitOfWork is implicit, wrapping manually is redundant:

```python
# Unnecessary - already wrapped by @handle
@handle(PlaceOrder)
def handle_place_order(self, command):
    with UnitOfWork():  # Redundant!
        order = Order(...)
        domain.repository_for(Order).add(order)
```

Simply write:

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(...)
    domain.repository_for(Order).add(order)
```

## Error Rollback

If an exception occurs within the handler method, the UnitOfWork ensures no partial changes are persisted:

```python
@handle(PlaceOrder)
def handle_place_order(self, command):
    order = Order(order_id=command.order_id)
    order.place()
    domain.repository_for(Order).add(order)
    # If this line raises, the order addition above is rolled back
    validate_inventory(command.product_id)
```

## Related

- [Loading Aggregates](./loading-aggregates.md) - How to load aggregates in handlers
- [Error Handling](./error-handling.md) - Custom error handling with handle_error
- [Anti-patterns](./anti-patterns.md) - Common UnitOfWork mistakes
