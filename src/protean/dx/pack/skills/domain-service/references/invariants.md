# Domain Service Invariants

Domain service invariants enforce cross-aggregate business rules that span multiple aggregates. Unlike aggregate invariants (which validate a single aggregate's state), domain service invariants validate the combined state of all aggregates involved in the operation.

## Code

The complete implementation is in [assets/domain_service_with_invariants.py](../assets/domain_service_with_invariants.py).

A condensed version, with two pre invariants, and the aggregates it works on. The service reads the inventory and changes only the order. The inventory reserves stock later, when an event handler reacts to `OrderConfirmed` and issues it a command:

```python
from protean.exceptions import ValidationError

@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: Identifier(required=True)
    items = List(content_type=Dict)

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    payment_id: Identifier()
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
    price: Decimal(precision=19, scale=4, default=0)

@domain.aggregate
class Inventory:
    product_id: Identifier(required=True)
    quantity: Integer(default=0)

@domain.domain_service(part_of=[Order, Inventory])
class OrderPlacementService:
    def __init__(self, order, inventories):
        super().__init__(order, inventories)
        self.order = order
        self.inventories = inventories

    @invariant.pre
    def inventory_should_have_sufficient_stock(self):
        # Lines for the same product draw on the same stock, so add them up.
        ordered: dict[str, int] = {}
        for item in self.order.items:
            ordered[item.product_id] = ordered.get(item.product_id, 0) + item.quantity
        for product_id, quantity in ordered.items():
            inventory = next(
                (i for i in self.inventories if i.product_id == product_id), None
            )
            if inventory is None or inventory.quantity < quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})

    @invariant.pre
    def order_payment_method_should_be_valid(self):
        if not self.order.payment_id:
            raise ValidationError(
                {"_service": ["Order must have a valid payment method"]}
            )

    def __call__(self):
        self.order.confirm()
```

## How invariants work

### Pre invariants

Pre invariants run **before** the service method executes. If any pre invariant fails, the service method is **not executed**. Both invariants in the service above are pre invariants.

### Post invariants

Post invariants run **after** the service method completes. They validate the resulting state:

```python
# fragment
@invariant.post
def order_should_be_confirmed(self):
    if self.order.status != "CONFIRMED":
        raise ValidationError({"_service": ["Order was not confirmed"]})
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
    else:
        raise AssertionError("expected both pre invariants to fail")
    assert order.status == "PENDING"
```

## Invariant method wrapping

Protean automatically wraps public methods with invariant calls during domain registration:

1. All methods marked with `@invariant.pre` are recorded
2. All methods marked with `@invariant.post` are recorded
3. Public instance methods (not starting with `_`, not dunder methods except `__call__`) are wrapped. Protean does not run the service's invariants around a class method
4. The wrapper runs pre invariants → original method → post invariants

Registration does this, not `__init__`, so a service whose `__init__` does not call `super().__init__()` still runs its invariants.

### Important: Private methods

Methods prefixed with `_` are **not** wrapped. Use this for helper methods, such as a `_calculate_total()` that `place_order()` calls.

If you forget the underscore, `calculate_total` is wrapped like any public method. Calling it from a public method runs every invariant again around the helper, against the state the outer method has reached so far. If that half-finished state breaks an invariant, the helper raises `ValidationError` before the outer method completes. Calling it from an invariant fails: the helper's wrapper runs the invariant, which calls the helper again, until Python's recursion limit stops the call.

## Best practices

1. **Name invariants descriptively**: Use full sentences like `inventory_should_have_sufficient_stock`
2. **Raise `ValidationError`**: Pass a dict mapping field names to lists of error messages
3. **Use `_service` key**: Convention for domain service errors: `{"_service": ["error message"]}`
4. **Review placement**: An invariant that reads only one aggregate belongs in that aggregate

## Related
- [Callable class pattern](./callable-class.md): Callable class with invariants
- [Instance methods pattern](./instance-methods.md): Instance methods with invariants
