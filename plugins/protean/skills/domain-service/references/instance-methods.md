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

The service works on these aggregates:

```python
@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    items = HasMany("OrderItem")
    status: String(default="PENDING")

    def confirm(self):
        self.status = "CONFIRMED"

    def cancel(self):
        self.status = "CANCELLED"

@domain.entity(part_of=Order)
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True)
    price: Float(default=0.0)

@domain.aggregate
class Inventory:
    product_id: Identifier(required=True)
    quantity: Integer(default=0)

    def reserve_stock(self, quantity):
        self.quantity -= quantity

    def release_stock(self, quantity):
        self.quantity += quantity
```

Each method represents a distinct business operation:

```python
@domain.domain_service(part_of=[Order, Inventory])
class OrderPlacementService:
    def __init__(self, order, inventories):
        super().__init__(order, inventories)
        self.order = order
        self.inventories = inventories

    def place_order(self):
        # Place the order and reserve stock
        for item in self.order.items:
            self._inventory_for(item).reserve_stock(item.quantity)
        self.order.confirm()

    def cancel_order(self):
        # Cancel the order and release the reserved stock
        for item in self.order.items:
            self._inventory_for(item).release_stock(item.quantity)
        self.order.cancel()

    def _inventory_for(self, item):
        return next(i for i in self.inventories if i.product_id == item.product_id)
```

### Method wrapping

Protean automatically wraps all public methods (those not starting with `_`) with invariant checks. This means:
- `@invariant.pre` methods run before any public method
- `@invariant.post` methods run after any public method
- Private methods (prefixed with `_`) are NOT wrapped

### Invocation

```python
domain.init(traverse=False)

with domain.domain_context():
    order = Order(
        customer_id="CUST-1",
        items=[OrderItem(product_id="PROD-1", quantity=2, price=10.0)],
    )
    inventory = Inventory(product_id="PROD-1", quantity=10)

    service = OrderPlacementService(order, [inventory])
    service.place_order()
```

## Choosing between callable and instance methods

If your domain service starts with one operation (callable) and grows to need more, refactor to instance methods:

```python
# fragment
# Before: single callable
class place_order:
    def __call__(self): ...

# After: multiple methods
class OrderPlacementService:
    def place_order(self): ...
    def cancel_order(self): ...
```

## Important: Private methods

Helper methods used internally should be prefixed with `_` so they are not wrapped with the invariant checks:

```python
# fragment
class OrderPlacementService:
    def place_order(self):
        total = self._calculate_total()  # private helper
        ...

    def _calculate_total(self):  # underscore prevents invariant wrapping
        return sum(item.quantity * item.price for item in self.order.items)
```

Without the underscore prefix, `calculate_total` is wrapped like any public method. Calling it from `place_order` runs every invariant again around the helper, against the state `place_order` has reached so far. If that half-finished state breaks an invariant, the helper raises `ValidationError` and `place_order` stops there. An invariant that calls a public helper is different: the helper's wrapper runs the invariant again, which calls the helper again, and the calls never end.

## Related
- [Callable class pattern](./callable-class.md) - Single-operation alternative
- [Class methods pattern](./class-methods.md) - Stateless alternative
- [Invariants](./invariants.md) - Pre/post validation details
