---
name: domain-service
description: "Define a Protean domain service - a stateless orchestrator that encapsulates complex business logic spanning multiple aggregates. Domain services centralize cross-aggregate operations that don't naturally fit within any single aggregate, while keeping aggregates focused on their core state and behavior. Use when you need to coordinate logic across two or more aggregates, implement a cross-aggregate business rule, orchestrate a domain operation that validates two or more aggregates together and changes one of them, define invariants that span aggregate boundaries, or implement the DDD Domain Service pattern. Domain services are always associated with at least two aggregates via part_of. Supports three flavors: callable class (__call__), class with instance methods, and class with class methods. Supports pre and post invariants for cross-aggregate validation."
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# Domain Service

## Key concepts

Domain services are **stateless orchestrators** for complex business logic that spans multiple aggregates. They exist because some domain operations naturally involve more than one aggregate and shouldn't be forced into either.

- **Stateless**: Holds no state between calls. The caller passes the aggregates in for each operation
- **Cross-aggregate**: Must be associated with at least two aggregates via `part_of`
- **Pure domain logic**: Focus on domain rules only; no persistence, messaging, or technical concerns
- **Reads many, changes one**: Validate against every aggregate passed in, then change only the primary aggregate (see Key rule 9)

## Basic structure

The examples on this page use these aggregates. `Order.confirm()` raises `OrderConfirmed` with the items, so the inventory side can reserve stock when it handles the event. `Order.cancel()` does the same with `OrderCancelled`, so the inventory side can release the stock.

```python
from protean.exceptions import ValidationError

@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: Identifier(required=True)
    items = List(content_type=Dict)

@domain.event(part_of="Order")
class OrderCancelled:
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
        self.raise_(OrderConfirmed(order_id=self.id, items=self._item_quantities()))

    def cancel(self):
        self.status = "CANCELLED"
        self.raise_(OrderCancelled(order_id=self.id, items=self._item_quantities()))

    def _item_quantities(self):
        return [
            {"product_id": item.product_id, "quantity": item.quantity}
            for item in self.items
        ]

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

`Inventory.reserve_stock()` and `release_stock()` are called by the inventory's own command handler, never by the domain service. An event handler in the order's cluster reacts to `OrderConfirmed` or `OrderCancelled` and issues a command to the inventory. The `add-domain-service-flow` skill builds that whole flow, and the `event-handler` skill's cross-aggregate reference shows the event handler.

A domain service is registered with the aggregate classes it works on, `@domain.domain_service(part_of=[Order, Inventory])`. The three flavors below differ in how you call it.

## Three flavors

### 1. Callable class (`__call__`)

Best for a single business operation. Instantiate and call:

```python
@domain.domain_service(part_of=[Order, Inventory])
class place_order:
    def __init__(self, order, inventories):
        super().__init__(order, inventories)
        self.order = order
        self.inventories = inventories

    @invariant.pre
    def inventory_should_have_sufficient_stock(self):
        stock = {i.product_id: i.quantity for i in self.inventories}
        # Lines for the same product draw on the same stock, so add them up.
        ordered: dict[str, int] = {}
        for item in self.order.items:
            ordered[item.product_id] = ordered.get(item.product_id, 0) + item.quantity
        for product_id, quantity in ordered.items():
            if stock.get(product_id, 0) < quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})

    def __call__(self):
        self.order.confirm()

# Usage: place_order(order, [inventory])()
```

### 2. Class with instance methods

Best for multiple related operations on the same aggregates. A pre invariant runs before every public method, so a check that applies to one operation only goes in a `_` helper that the operation calls:

```python
@domain.domain_service(part_of=[Order, Inventory])
class OrderFulfillmentService:
    def __init__(self, order, inventories):
        super().__init__(order, inventories)
        self.order = order
        self.inventories = inventories

    def place_order(self):
        self._check_stock()
        self.order.confirm()

    def cancel_order(self):
        self.order.cancel()

    def _check_stock(self):
        stock = {i.product_id: i.quantity for i in self.inventories}
        # Lines for the same product draw on the same stock, so add them up.
        ordered: dict[str, int] = {}
        for item in self.order.items:
            ordered[item.product_id] = ordered.get(item.product_id, 0) + item.quantity
        for product_id, quantity in ordered.items():
            if stock.get(product_id, 0) < quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})

# Usage:
#   service = OrderFulfillmentService(order, [inventory])
#   service.place_order()
```

### 3. Class with class methods

Best for a stateless, functional style with no invariants. Protean does not run the service's `@invariant.pre` or `@invariant.post` methods around a class method, so a class-method service should not declare any. Protean still wraps a public class method, and treats its first argument as the service instance. It runs the first argument's own invariants around the call, so that argument must be an aggregate: a list there raises `AttributeError`. A call on an instance raises `TypeError`, because the instance is passed as one argument too many. Validate inside the method, and call it on the class:

```python
@domain.domain_service(part_of=[Order, Inventory])
class StockReservationService:
    @classmethod
    def place_order(cls, order, inventories):
        stock = {i.product_id: i.quantity for i in inventories}
        # Lines for the same product draw on the same stock, so add them up.
        ordered: dict[str, int] = {}
        for item in order.items:
            ordered[item.product_id] = ordered.get(item.product_id, 0) + item.quantity
        for product_id, quantity in ordered.items():
            if stock.get(product_id, 0) < quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})
        order.confirm()
        return order

# Usage:
#   order = StockReservationService.place_order(order, [inventory])
```

## Key rules

1. **Must associate with 2+ aggregates**: `part_of=[Agg1, Agg2]` is required. A domain service with fewer than two aggregates raises `IncorrectUsageError`. Pass the aggregate classes, not their names as strings.
2. **Use `@domain.domain_service` decorator**: Or register with `domain.register(MyService, part_of=[Agg1, Agg2])`.
3. **`super().__init__()` stores the aggregates**: `BaseDomainService.__init__` saves the aggregates it receives on `self._aggregates`, and does nothing else. Call it when your code reads `self._aggregates`. Protean wires invariants when it registers the service, so a service whose `__init__` leaves the call out still runs its invariants.
4. **Stateless between calls**: Domain services hold no state between invocations. State comes from aggregates passed in.
5. **Don't persist**: Domain services change the primary aggregate but never call repositories. The calling layer handles persistence.
6. **Invariants span aggregates**: Use `@invariant.pre` and `@invariant.post` for validations that involve multiple aggregates.
7. **Prefix helper methods with `_`**: Protean wraps every public instance method and `__call__` with the invariant checks. A public helper called from another public method runs the pre and post invariants again, against the state the outer method has reached so far. If that half-finished state breaks an invariant, the helper raises `ValidationError` before the outer method completes. An invariant that calls a public helper fails: the helper's wrapper runs the invariant again, which calls the helper again, until Python's recursion limit stops the call. A method whose name starts with `_` is not wrapped.
8. **Choose flavor based on needs**: Callable class for a single operation, instance methods for multiple operations, class methods for a service with no invariants (see flavor 3 for how Protean wraps a class method).
9. **Change only the primary aggregate**: A domain service reads several aggregates but changes one, the aggregate the command belongs to. The command handler persists only that aggregate. The other aggregate changes through an event handler in the cluster that owns the event, which issues a command to the other aggregate. See the `event-handler` skill's cross-aggregate reference and the `add-domain-service-flow` skill.

## Domain service options

| Option | Purpose | Required | Default |
|--------|---------|----------|---------|
| `part_of` | List of 2+ aggregate classes this service orchestrates | Yes | `None` |
| `suppress_checks` | Diagnostic codes `protean check` should not report for this service | No | `()` |

## Invariants

Domain services support `@invariant.pre` and `@invariant.post` decorators for cross-aggregate validation:

```python
@domain.domain_service(part_of=[Order, Inventory])
class PlaceOrderService:
    def __init__(self, order, inventories):
        super().__init__(order, inventories)
        self.order = order
        self.inventories = inventories

    @invariant.pre
    def inventory_should_have_sufficient_stock(self):
        stock = {i.product_id: i.quantity for i in self.inventories}
        # Lines for the same product draw on the same stock, so add them up.
        ordered: dict[str, int] = {}
        for item in self.order.items:
            ordered[item.product_id] = ordered.get(item.product_id, 0) + item.quantity
        for product_id, quantity in ordered.items():
            if stock.get(product_id, 0) < quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})

    @invariant.post
    def order_should_be_confirmed(self):
        if self.order.status != "CONFIRMED":
            raise ValidationError({"_service": ["Order was not confirmed"]})

    def __call__(self):
        self.order.confirm()
```

- **Pre invariants**: Run before the service method executes; validate preconditions
- **Post invariants**: Run after the service method executes; validate postconditions
- Multiple invariant violations are collected and raised together as a single `ValidationError`
- If a pre invariant fails, the service method is **not executed**

Calling the services:

```python
domain.init(traverse=False)

with domain.domain_context():
    order = Order(
        customer_id="CUST-1",
        items=[OrderItem(product_id="PROD-1", quantity=2, price=10.0)],
    )
    inventory = Inventory(product_id="PROD-1", quantity=1)

    # The pre invariant fails, so __call__ does not run
    try:
        PlaceOrderService(order, [inventory])()
    except ValidationError as exc:
        assert exc.messages == {"_service": ["Product is out of stock"]}
    else:
        raise AssertionError("expected the pre invariant to fail")
    assert order.status == "PENDING"

    inventory = Inventory(product_id="PROD-1", quantity=5)
    PlaceOrderService(order, [inventory])()
    assert order.status == "CONFIRMED"
    # The service reads the inventory but does not change it
    assert inventory.quantity == 5
    # The event carries what the inventory side needs to reserve stock
    assert order._events[-1].items == [{"product_id": "PROD-1", "quantity": 2}]

    # The class-method flavor validates inline
    order = Order(
        customer_id="CUST-1",
        items=[OrderItem(product_id="PROD-1", quantity=9)],
    )
    try:
        StockReservationService.place_order(order, [inventory])
    except ValidationError as exc:
        assert exc.messages == {"_service": ["Product is out of stock"]}
    else:
        raise AssertionError("expected the inline check to fail")
    assert order.status == "PENDING"
```

## Common mistakes

### Associating with only one aggregate

```python
# fragment
# Wrong - raises IncorrectUsageError
@domain.domain_service(part_of=[Order])
class OrderService:
    ...
```

If your logic only involves one aggregate, it belongs **in the aggregate itself**.

### Persisting inside the domain service

```python
# fragment
# Wrong - domain services don't handle persistence
def place_order(self):
    self.order.confirm()
    domain.repository_for(Order).add(self.order)  # Don't do this!
```

### Calling a public helper from an invariant

```python
# fragment
# Wrong - calculate_total is public, so it is wrapped with the invariant
# checks. The invariant calls it, its wrapper runs the invariant again, and
# so on until Python's recursion limit stops the calls.
@invariant.post
def total_should_be_positive(self):
    if self.calculate_total() <= 0:
        raise ValidationError({"_service": ["Order total must be positive"]})

def calculate_total(self):
    return sum(item.quantity * item.price for item in self.order.items)
```

```python
# fragment
# Correct - the underscore prefix keeps the helper unwrapped
@invariant.post
def total_should_be_positive(self):
    if self._calculate_total() <= 0:
        raise ValidationError({"_service": ["Order total must be positive"]})

def _calculate_total(self):
    return sum(item.quantity * item.price for item in self.order.items)
```

## Detailed references

### Core concepts
- [Callable class pattern](references/callable-class.md): Single-operation domain service
- [Instance methods pattern](references/instance-methods.md): Multi-operation domain service
- [Class methods pattern](references/class-methods.md): Stateless functional domain service
- [Invariants](references/invariants.md): Pre/post validation across aggregates

### Complete examples
- [Callable class example](assets/domain_service_callable.py): Order placement as callable
- [Instance methods example](assets/domain_service_instance_methods.py): Order placement with named methods
- [Class methods example](assets/domain_service_class_methods.py): Order placement with class methods
- [With invariants example](assets/domain_service_with_invariants.py): Full pre/post invariant validation

### Related skills
- `aggregate`: Domain aggregates that domain services orchestrate
- `command-handler`: Where domain services are typically invoked from
- `add-domain-service-flow`: The whole flow: the service, the command handler that persists the primary aggregate, and the event handler and command that change the other aggregate
- `event-handler`: Its cross-aggregate reference shows the event handler that issues a command to the other aggregate
- `event`: Events raised by aggregates during domain service operations
- `value-object`: Value objects used within aggregates passed to domain services

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
