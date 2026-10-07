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

A condensed version, with the aggregates it works on:

```python
from protean.exceptions import ValidationError

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")
    status: String(default="PENDING")

    def confirm(self):
        self.status = "CONFIRMED"

@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)

@domain.aggregate
class Inventory:
    product_id: Identifier(required=True)
    quantity: Integer(default=0)

    def reserve_stock(self, quantity):
        self.quantity -= quantity

@domain.domain_service(part_of=[Order, Inventory])
class place_order:
    def __init__(self, order, inventories):
        super().__init__(order, inventories)
        self.order = order
        self.inventories = inventories

    @invariant.pre
    def inventory_should_have_sufficient_stock(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            if inventory is None or inventory.quantity < item.quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})

    def __call__(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            inventory.reserve_stock(item.quantity)
        self.order.confirm()
```

## Walkthrough

### The `__init__` method

The constructor accepts the aggregates this service will operate on and stores them on the instance:

```python
# fragment
def __init__(self, order, inventories):
    super().__init__(order, inventories)
    self.order = order
    self.inventories = inventories
```

`BaseDomainService.__init__` saves the aggregates it receives on `self._aggregates` and does nothing else. The call is needed only when your code reads `self._aggregates`. Protean wires the invariants when it registers the service, so they run whether or not `__init__` makes this call.

### The `__call__` method

This is where the business logic lives. It mutates the aggregates:

```python
# fragment
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
domain.init(traverse=False)

with domain.domain_context():
    order = Order(
        customer_id="CUST-1",
        items=[
            OrderItem(product_id="PROD-1", quantity=2),
            OrderItem(product_id="PROD-2", quantity=1),
        ],
    )
    inventory1 = Inventory(product_id="PROD-1", quantity=10)
    inventory2 = Inventory(product_id="PROD-2", quantity=10)

    place_order(order, [inventory1, inventory2])()
```

This is equivalent to:
```python
with domain.domain_context():
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
