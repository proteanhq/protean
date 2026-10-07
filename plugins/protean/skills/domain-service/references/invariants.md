# Domain Service Invariants

Domain service invariants enforce cross-aggregate business rules that span multiple aggregates. Unlike aggregate invariants (which validate a single aggregate's state), domain service invariants validate the combined state of all aggregates involved in the operation.

## Overview

Invariants in domain services serve two purposes:
1. **Pre invariants** (`@invariant.pre`): Validate preconditions before the operation runs
2. **Post invariants** (`@invariant.post`): Validate postconditions after the operation completes

## Code

The complete implementation is in [assets/domain_service_with_invariants.py](../assets/domain_service_with_invariants.py).

A condensed version, with two pre invariants, and the aggregates it works on:

```python
from protean.exceptions import ValidationError

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    payment_id: Identifier()
    items = HasMany("OrderItem")
    status: String(default="PENDING")

    def confirm(self):
        self.status = "CONFIRMED"

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

@domain.domain_service(part_of=[Order, Inventory])
class OrderPlacementService:
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

    @invariant.pre
    def order_payment_method_should_be_valid(self):
        if not self.order.payment_id:
            raise ValidationError(
                {"_service": ["Order must have a valid payment method"]}
            )

    def __call__(self):
        for item in self.order.items:
            inventory = next(
                i for i in self.inventories if i.product_id == item.product_id
            )
            inventory.reserve_stock(item.quantity)
        self.order.confirm()
```

## How invariants work

### Pre invariants

Pre invariants run **before** the service method executes. If any pre invariant fails, the service method is **not executed**:

```python
# fragment
@invariant.pre
def inventory_should_have_sufficient_stock(self):
    for item in self.order.items:
        inventory = next(
            (i for i in self.inventories if i.product_id == item.product_id), None
        )
        if inventory is None or inventory.quantity < item.quantity:
            raise ValidationError({"_service": ["Product is out of stock"]})
```

### Post invariants

Post invariants run **after** the service method completes. They validate the resulting state:

```python
# fragment
@invariant.post
def total_reserved_value_should_match_order_value(self):
    order_total = sum(item.quantity * item.price for item in self.order.items)
    reserved_total = sum(
        inventory._events[0].quantity * item.price
        for item, inventory in zip(self.order.items, self.inventories)
        if inventory._events
    )
    if order_total != reserved_total:
        raise ValidationError(
            {"_service": ["Total reserved value does not match order value"]}
        )
```

### Error collection

Multiple invariant failures are collected and raised as a single `ValidationError`:

```python
domain.init(traverse=False)

with domain.domain_context():
    # No payment method, and not enough stock: both pre invariants fail
    order = Order(
        customer_id="CUST-1",
        items=[OrderItem(product_id="PROD-1", quantity=5, price=10.0)],
    )
    inventory = Inventory(product_id="PROD-1", quantity=1)

    try:
        OrderPlacementService(order, [inventory])()
    except ValidationError as exc:
        # Both errors are reported together
        assert exc.messages == {
            "_service": [
                "Product is out of stock",
                "Order must have a valid payment method",
            ]
        }
```

## Invariant method wrapping

Protean automatically wraps public methods with invariant calls during domain registration:

1. All methods marked with `@invariant.pre` are recorded
2. All methods marked with `@invariant.post` are recorded
3. Public methods (not starting with `_`, not dunder methods except `__call__`) are wrapped
4. The wrapper runs pre invariants → original method → post invariants

Registration does this, not `__init__`, so a service whose `__init__` does not call `super().__init__()` still runs its invariants.

### Important: Private methods

Methods prefixed with `_` are **not** wrapped. Use this for helper methods:

```python
# fragment
class OrderPlacementService:
    def place_order(self):
        total = self._calculate_total()  # Not wrapped with invariants
        ...

    def _calculate_total(self):  # Private - no invariant checks
        return sum(item.quantity * item.price for item in self.order.items)
```

If you forget the underscore, `calculate_total` is wrapped like any public method. Calling it from a public method runs every invariant again around the helper: extra checks, not an error. Calling it from an invariant never ends: the helper's wrapper runs the invariant, which calls the helper again.

## Best practices

1. **Name invariants descriptively**: Use full sentences like `inventory_should_have_sufficient_stock`
2. **Raise `ValidationError`**: Always raise `ValidationError` with a dict mapping field names to error message lists
3. **Use `_service` key**: Convention for domain service errors: `{"_service": ["error message"]}`
4. **Keep invariants focused**: Each invariant should check one logical condition
5. **Review placement**: If an invariant doesn't use multiple aggregates, it likely belongs in an aggregate, not the service

## Related
- [Callable class pattern](./callable-class.md) - Callable class with invariants
- [Instance methods pattern](./instance-methods.md) - Instance methods with invariants
