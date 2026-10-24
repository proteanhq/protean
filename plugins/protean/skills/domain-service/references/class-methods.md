# Class Methods Pattern

A domain service with class methods provides a stateless, functional approach. No instantiation needed - call methods directly on the class.

## Overview

Use this pattern when:
- No invariants are needed. Protean does not run the service's `@invariant.pre` or `@invariant.post` methods around a class method, so a class-method service should not declare any. Protean still wraps a public class method, and treats its first argument as the service instance. It runs the first argument's own invariants around the call, so that argument must be an aggregate: a list there raises `AttributeError`. A call on an instance raises `TypeError`, because the instance is passed as one argument too many.
- You prefer a functional style
- Each method receives all input as parameters
- Validation is done inline within the method

## Code

The complete implementation is in [assets/domain_service_class_methods.py](../assets/domain_service_class_methods.py).

Key highlights:
- Methods decorated with `@classmethod`
- No `__init__` needed
- Aggregates passed as method parameters, not stored on instance
- Validation done inline, with no invariant decorators on the service
- Changes only the order, and returns it
- Called on the class, never on an instance

## Walkthrough

### Class method structure

The service works on these aggregates. `Order.confirm()` raises `OrderConfirmed` with the items, so the inventory can reserve stock later, when an event handler issues it a command:

```python
from protean.exceptions import ValidationError

@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: Identifier(required=True)
    items = List(content_type=Dict)

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")
    status: String(default="PENDING")

    def confirm(self):
        self.status = "CONFIRMED"
        self.raise_(
            OrderConfirmed(
                order_id=self.id,
                items=[
                    {"product_id": item.product_id, "quantity": item.quantity}
                    for item in self.items
                ],
            )
        )

@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)

@domain.aggregate
class Inventory:
    product_id: Identifier(required=True)
    quantity: Integer(default=0)
```

```python
@domain.domain_service(part_of=[Order, Inventory])
class OrderPlacementService:
    @classmethod
    def place_order(cls, order, inventories):
        # Inline validation: read the inventory, change only the order
        # Lines for the same product draw on the same stock, so add them up.
        ordered: dict[str, int] = {}
        for item in order.items:
            ordered[item.product_id] = ordered.get(item.product_id, 0) + item.quantity
        for product_id, quantity in ordered.items():
            inventory = next(
                (i for i in inventories if i.product_id == product_id), None
            )
            if inventory is None or inventory.quantity < quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})

        order.confirm()
        return order
```

### Return values

Class methods commonly return the changed aggregate, since there's no instance state to inspect:

```python
domain.init(traverse=False)

with domain.domain_context():
    order = Order(
        customer_id="CUST-1",
        items=[OrderItem(product_id="PROD-1", quantity=2)],
    )
    inventory = Inventory(product_id="PROD-1", quantity=10)

    order = OrderPlacementService.place_order(order, [inventory])

    assert order.status == "CONFIRMED"
    assert inventory.quantity == 10  # read by the service, not changed
```

### Invocation

Direct class method call - no instantiation:

```python
with domain.domain_context():
    OrderPlacementService.place_order(order, [inventory])
```

## Trade-offs

| Aspect | Class Methods | Instance Methods |
|--------|--------------|------------------|
| Invariant support | No | Yes |
| Instantiation | Not needed | Required |
| State management | Stateless | Instance attributes |
| Validation | Inline in method | Via `@invariant` decorators |
| Return pattern | Explicit return | Changes the order in place |

## When NOT to use class methods

- When you need `@invariant.pre` or `@invariant.post` validation
- When you have multiple methods sharing common validation logic
- When operations need shared state between steps

## Related
- [Callable class pattern](./callable-class.md): For single-operation with invariants
- [Instance methods pattern](./instance-methods.md): For multiple operations with invariants
