# Instance Methods Pattern

A domain service with instance methods supports multiple named business operations on the same set of aggregates.

## Overview

Use this pattern when:
- The domain service has multiple related business operations
- Operations share the same aggregates
- You want descriptive method names (e.g., `place_order()`, `cancel_order()`)
- You have invariants that apply to all or specific methods

## Code

The complete implementation is in [assets/domain_service_instance_methods.py](../assets/domain_service_instance_methods.py).

Key highlights:
- Named methods instead of `__call__`
- Same `__init__` pattern with `super().__init__()`
- `@invariant.pre` checks run before **every** public method
- Public methods are wrapped with invariant calls automatically

## Walkthrough

### Multiple methods

Each method represents a distinct business operation:

```python
class OrderPlacementService:
    def __init__(self, order, inventories):
        super().__init__(*(order, inventories))
        self.order = order
        self.inventories = inventories

    def place_order(self):
        # Place the order and reserve stock
        ...
```

### Method wrapping

Protean automatically wraps all public methods (those not starting with `_`) with invariant checks. This means:
- `@invariant.pre` methods run before any public method
- `@invariant.post` methods run after any public method
- Private methods (prefixed with `_`) are NOT wrapped

### Invocation

```python
service = OrderPlacementService(order, [inventory])
service.place_order()
```

## Choosing between callable and instance methods

If your domain service starts with one operation (callable) and grows to need more, refactor to instance methods:

```python
# Before: single callable
class place_order:
    def __call__(self): ...

# After: multiple methods
class OrderPlacementService:
    def place_order(self): ...
    def validate_order(self): ...
```

## Important: Private methods

Helper methods used internally must be prefixed with `_` to prevent invariant wrapping:

```python
class OrderPlacementService:
    def place_order(self):
        total = self._calculate_total()  # private helper
        ...

    def _calculate_total(self):  # underscore prevents invariant wrapping
        return sum(item.quantity * item.price for item in self.order.items)
```

Without the underscore prefix, calling `calculate_total` would trigger invariant checks recursively, causing a `RecursionError`.

## Related
- [Callable class pattern](./callable-class.md) - Single-operation alternative
- [Class methods pattern](./class-methods.md) - Stateless alternative
- [Invariants](./invariants.md) - Pre/post validation details
