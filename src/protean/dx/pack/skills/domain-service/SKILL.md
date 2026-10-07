---
name: domain-service
description: "Define a Protean domain service - a stateless orchestrator that encapsulates complex business logic spanning multiple aggregates. Domain services centralize cross-aggregate operations that don't naturally fit within any single aggregate, while keeping aggregates focused on their core state and behavior. Use when you need to coordinate logic across two or more aggregates, implement a cross-aggregate business rule, orchestrate a domain operation that validates and changes two or more aggregates together, define invariants that span aggregate boundaries, or implement the DDD Domain Service pattern. Domain services are always associated with at least two aggregates via part_of. Supports three flavors: callable class (__call__), class with instance methods, and class with class methods. Supports pre and post invariants for cross-aggregate validation."
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

- **Stateless**: No internal state between method calls; operate on state provided through parameters
- **Cross-aggregate**: Must be associated with at least two aggregates via `part_of`
- **Pure domain logic**: Focus on domain rules only; no persistence, messaging, or technical concerns
- **Aggregate mutation**: Mutate aggregates to the desired state; persistence is handled by the calling layer (command handlers, application services)

### Typical workflow

1. Application layer loads aggregates via repositories
2. Application layer invokes the domain service, passing aggregates
3. Domain service executes business logic, mutating aggregates
4. Application layer persists one aggregate, the primary one. The other aggregates change through events (see rule 9)

## Basic structure

The examples on this page use these aggregates:

```python
from protean.exceptions import ValidationError

@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: Identifier(required=True)

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    payment_id: Identifier()
    items = HasMany("OrderItem")
    status: String(default="PENDING")

    def confirm(self):
        self.status = "CONFIRMED"
        self.raise_(OrderConfirmed(order_id=self.id))

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

A domain service is registered with the aggregate classes it works on:

```python
@domain.domain_service(part_of=[Order, Inventory])
class OrderPlacementService:
    def __init__(self, order, inventories):
        super().__init__(order, inventories)
        self.order = order
        self.inventories = inventories

    def place_order(self):
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            inventory.reserve_stock(item.quantity)
        self.order.confirm()
```

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

    def __call__(self):
        for item in self.order.items:
            inventory = next(
                i for i in self.inventories if i.product_id == item.product_id
            )
            inventory.reserve_stock(item.quantity)
        self.order.confirm()

# Usage: place_order(order, [inventory])()
```

### 2. Class with instance methods

Best for multiple related operations on the same aggregates:

```python
@domain.domain_service(part_of=[Order, Inventory])
class OrderFulfillmentService:
    def __init__(self, order, inventories):
        super().__init__(order, inventories)
        self.order = order
        self.inventories = inventories

    def place_order(self):
        for item in self.order.items:
            self._inventory_for(item).reserve_stock(item.quantity)
        self.order.confirm()

    def cancel_order(self):
        for item in self.order.items:
            self._inventory_for(item).release_stock(item.quantity)
        self.order.cancel()

    def _inventory_for(self, item):
        return next(i for i in self.inventories if i.product_id == item.product_id)

# Usage:
#   service = OrderFulfillmentService(order, [inventory])
#   service.place_order()
```

### 3. Class with class methods

Best when no invariants are needed; stateless functional style:

```python
@domain.domain_service(part_of=[Order, Inventory])
class StockReservationService:
    @classmethod
    def place_order(cls, order, inventories):
        for item in order.items:
            inventory = next(
                (i for i in inventories if i.product_id == item.product_id), None
            )
            if inventory is None or inventory.quantity < item.quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})
            inventory.reserve_stock(item.quantity)
        order.confirm()
        return order, inventories

# Usage:
#   order, inventories = StockReservationService.place_order(order, [inventory])
```

## Key rules

1. **Must associate with 2+ aggregates**: `part_of=[Agg1, Agg2]` is required. A domain service with fewer than two aggregates raises `IncorrectUsageError`. Pass the aggregate classes, not their names as strings.
2. **Use `@domain.domain_service` decorator**: Or register with `domain.register(MyService, part_of=[Agg1, Agg2])`.
3. **`super().__init__()` stores the aggregates**: `BaseDomainService.__init__` saves the aggregates it receives on `self._aggregates`, and does nothing else. Call it when your code reads `self._aggregates`. Protean wires invariants when it registers the service, so a service whose `__init__` leaves the call out still runs its invariants.
4. **Stateless between calls**: Domain services hold no state between invocations. State comes from aggregates passed in.
5. **Don't persist**: Domain services mutate aggregates but never call repositories. The calling layer handles persistence.
6. **Invariants span aggregates**: Use `@invariant.pre` and `@invariant.post` for validations that involve multiple aggregates.
7. **Prefix helper methods with `_`**: Protean wraps every public method and `__call__` with the invariant checks. A public helper called from another public method runs the invariants again: extra checks, not an error. An invariant that calls a public helper recurses without end, because the helper's wrapper runs the invariant again. A method whose name starts with `_` is not wrapped.
8. **Choose flavor based on needs**: Callable class for single operation, instance methods for multiple operations, class methods when no invariants needed.
9. **Don't propagate state changes in more than one aggregate**: Even though domain services can access multiple aggregates, use events and eventual consistency for cross-aggregate state synchronization. The command handler should only persist the primary aggregate. The other aggregate changes through an event handler in the cluster that owns the event, which issues a command to the other aggregate. See the `event-handler` skill's cross-aggregate reference.
10. **Review regularly**: As the domain model matures, revisit whether logic in a domain service should be moved to an aggregate or vice versa.

## Domain service options

| Option | Purpose | Required | Default |
|--------|---------|----------|---------|
| `part_of` | List of 2+ aggregate classes this service orchestrates | Yes | None |

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
        for item in self.order.items:
            inventory = next(
                (i for i in self.inventories if i.product_id == item.product_id), None
            )
            if inventory is None or inventory.quantity < item.quantity:
                raise ValidationError({"_service": ["Product is out of stock"]})

    @invariant.post
    def order_should_be_confirmed(self):
        if self.order.status != "CONFIRMED":
            raise ValidationError({"_service": ["Order was not confirmed"]})

    def __call__(self):
        for item in self.order.items:
            inventory = next(
                i for i in self.inventories if i.product_id == item.product_id
            )
            inventory.reserve_stock(item.quantity)
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
    assert order.status == "PENDING"

    inventory = Inventory(product_id="PROD-1", quantity=5)
    PlaceOrderService(order, [inventory])()
    assert order.status == "CONFIRMED"
    assert inventory.quantity == 3
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

```python
# Correct - needs 2+ aggregates
@domain.domain_service(part_of=[Order, Inventory])
class OrderInventoryService:
    @classmethod
    def can_fulfil(cls, order, inventories):
        stock = {i.product_id: i.quantity for i in inventories}
        return all(stock.get(item.product_id, 0) >= item.quantity for item in order.items)
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

```python
# fragment
# Correct - mutate the aggregates, let the caller persist
def place_order(self):
    self.order.confirm()
    # The calling command handler persists the order
```

### Calling a public helper from an invariant

```python
# fragment
# Wrong - calculate_total is public, so it is wrapped with the invariant
# checks. The invariant calls it, its wrapper runs the invariant again, and
# the calls never end.
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

A public helper called from another public method does not loop, but it runs every invariant again around the helper. Prefix it with `_` too.

## Detailed references

### Core concepts
- [Callable class pattern](references/callable-class.md) - Single-operation domain service
- [Instance methods pattern](references/instance-methods.md) - Multi-operation domain service
- [Class methods pattern](references/class-methods.md) - Stateless functional domain service
- [Invariants](references/invariants.md) - Pre/post validation across aggregates

### Complete examples
- [Callable class example](assets/domain_service_callable.py) - Order placement as callable
- [Instance methods example](assets/domain_service_instance_methods.py) - Order placement with named methods
- [Class methods example](assets/domain_service_class_methods.py) - Order placement with class methods
- [With invariants example](assets/domain_service_with_invariants.py) - Full pre/post invariant validation

### Related skills
- `aggregate` - Domain aggregates that domain services orchestrate
- `command-handler` - Where domain services are typically invoked from
- `event` - Events raised by aggregates during domain service operations
- `value-object` - Value objects used within aggregates passed to domain services

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
