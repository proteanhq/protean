# Callable Class Pattern

A callable domain service implements `__call__` for a single business operation. This is the most concise pattern when a domain service has exactly one responsibility.

## Overview

Use this pattern when:
- The domain service performs a single business operation
- You want concise, elegant invocation syntax: `service(order, inventories)()`
- You have `pre` invariants that should apply to the operation

## Code

The complete implementation is in [assets/domain_service_callable.py](../assets/domain_service_callable.py).

Key highlights:
- The class name is lowercase (convention for callable services, e.g., `place_order`)
- `__init__` stores the aggregates and calls `super().__init__()`
- `__call__` contains the business logic
- `@invariant.pre` validates preconditions before `__call__` runs

## Walkthrough

### The `__init__` method

The constructor accepts the aggregates this service will operate on. It **must** call `super().__init__()` passing all aggregates to the base class:

```python
def __init__(self, order, inventories):
    super().__init__(*(order, inventories))
    self.order = order
    self.inventories = inventories
```

The `super().__init__()` call registers the aggregates with the base `BaseDomainService` class. The `*()` unpacking is required because the base class accepts `*aggregates`.

### The `__call__` method

This is where the business logic lives. It mutates the aggregates:

```python
def __call__(self):
    for item in self.order.items:
        inventory = next(
            (i for i in self.inventories if i.product_id == item.product_id), None
        )
        inventory.reserve_stock(item.quantity)
    self.order.confirm()
```

### Invocation

```python
place_order(order, [inventory1, inventory2])()
```

This is equivalent to:
```python
service = place_order(order, [inventory1, inventory2])
service()  # triggers pre invariants, runs __call__, triggers post invariants
```

## When to choose this over other patterns

| Factor | Callable | Instance Methods | Class Methods |
|--------|----------|------------------|---------------|
| Number of operations | One | Multiple | Any |
| Invariant support | Yes | Yes | No |
| Invocation style | `svc()` | `svc.method()` | `Cls.method(aggs)` |

## Related
- [Instance methods pattern](./instance-methods.md) - For multiple operations
- [Invariants](./invariants.md) - Pre/post validation details
