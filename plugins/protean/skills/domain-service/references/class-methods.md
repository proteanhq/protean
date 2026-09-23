# Class Methods Pattern

A domain service with class methods provides a stateless, functional approach. No instantiation needed - call methods directly on the class.

## Overview

Use this pattern when:
- No invariants are needed (class methods don't support `@invariant.pre`/`@invariant.post`)
- You prefer a functional style
- Each method receives all input as parameters
- Validation is done inline within the method

## Code

The complete implementation is in [assets/domain_service_class_methods.py](../assets/domain_service_class_methods.py).

Key highlights:
- Methods decorated with `@classmethod`
- No `__init__` needed
- Aggregates passed as method parameters, not stored on instance
- Validation done inline (no invariant decorators)
- Typically returns the modified aggregates

## Walkthrough

### Class method structure

```python
@domain.domain_service(part_of=[Order, Inventory])
class OrderPlacementService:
    @classmethod
    def place_order(cls, order, inventories):
        # Inline validation
        for item in order.items:
            inventory = next(
                (i for i in inventories if i.product_id == item.product_id), None
            )
            if inventory is None or inventory.quantity < item.quantity:
                raise Exception("Product is out of stock")
            inventory.reserve_stock(item.quantity)

        order.confirm()
        return order, inventories
```

### Return values

Class methods commonly return the modified aggregates, since there's no instance state to inspect:

```python
order, inventories = OrderPlacementService.place_order(order, [inventory])
```

### Invocation

Direct class method call - no instantiation:

```python
OrderPlacementService.place_order(order, inventories)
```

## Trade-offs

| Aspect | Class Methods | Instance Methods |
|--------|--------------|------------------|
| Invariant support | No | Yes |
| Instantiation | Not needed | Required |
| State management | Stateless | Instance attributes |
| Validation | Inline in method | Via `@invariant` decorators |
| Return pattern | Explicit return | Mutation in place |

## When NOT to use class methods

- When you need `@invariant.pre` or `@invariant.post` validation
- When you have multiple methods sharing common validation logic
- When operations need shared state between steps

## Related
- [Callable class pattern](./callable-class.md) - For single-operation with invariants
- [Instance methods pattern](./instance-methods.md) - For multiple operations with invariants
