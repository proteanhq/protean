# Raising Events from Aggregates

Events are raised from within aggregate methods to indicate that a state change has occurred. This document explains how to properly raise events, when to raise them, and best practices for event emission.

## Overview

Events should be raised immediately after a state change occurs in the aggregate. The `self.raise_()` method is used to emit events, which are then automatically associated with the aggregate instance and its stream.

**Key principles:**
- Events are raised AFTER the state change
- Events describe what happened (past-tense)
- One state change can trigger multiple events
- Events are automatically queued and persisted with the aggregate

## Code

The complete implementation is in [assets/raising_events.py](../assets/raising_events.py).

Key highlights:
- Events are raised using `self.raise_(event_instance)`
- Events are automatically associated with the aggregate
- Multiple events can be raised in a single method
- Events are persisted when the aggregate is saved

## Basic Pattern

The standard pattern for raising events:

```python
from datetime import datetime, timezone

@domain.aggregate
class Order:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")

    def place(self):
        # 1. Validate preconditions
        if self.status != "draft":
            raise ValueError("Order already placed")

        # 2. Change state
        self.status = "placed"
        placed_at = datetime.now(timezone.utc)

        # 3. Raise event (AFTER state change)
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            placed_at=placed_at
        ))
```

## When to Raise Events

### Raise Events When:

1. **State transitions occur** - Aggregate moves to a new state
2. **Important domain events happen** - Business-significant changes
3. **Other parts of the system need to know** - Cross-aggregate coordination
4. **Building an audit trail** - Recording what happened
5. **Event sourcing** - Events are the source of truth

### Don't Raise Events When:

1. **Validation fails** - Only raise events after successful changes
2. **Internal calculations** - Not every computation needs an event
3. **Query methods** - Events indicate changes, not reads
4. **Derived data changes** - If computed from other data

## Raising Single Events

Most state changes raise a single event:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 1
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)
    placed_at: DateTime(required=True)

@domain.aggregate
class Order:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")
    total = ValueObject(Money)

    def place(self):
        if not self.total or self.total.amount <= 0:
            raise ValueError("Order must have a positive total")

        self.status = "placed"

        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            total=self.total,
            placed_at=datetime.now(timezone.utc)
        ))
```

## Raising Multiple Events

A single method can raise multiple events:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)

@domain.event(part_of="Order")
class LoyaltyPointsEarned:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    points: Integer(required=True)
    earned_at: DateTime(required=True)

@domain.aggregate
class Order:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")
    total = ValueObject(Money)

    def place(self):
        self.status = "placed"
        now = datetime.now(timezone.utc)

        # Raise multiple events
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            placed_at=now
        ))

        # Additional event for loyalty points
        points = int(self.total.amount)  # 1 point per dollar
        self.raise_(LoyaltyPointsEarned(
            order_id=self.order_id,
            customer_id=self.customer_id,
            points=points,
            earned_at=now
        ))
```

## Events with Value Objects

Pass value objects from aggregate to event:

```python
@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

@domain.value_object
class Address:
    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)

@domain.event(part_of="Order")
class OrderPlaced:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)
    shipping_address = ValueObject(Address, required=True)
    placed_at: DateTime(required=True)

@domain.aggregate
class Order:
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")
    total = ValueObject(Money)
    shipping_address = ValueObject(Address)

    def place(self):
        self.status = "placed"

        # Pass value objects from aggregate to event
        self.raise_(OrderPlaced(
            order_id=self.order_id,
            customer_id=self.customer_id,
            total=self.total,  # Value object
            shipping_address=self.shipping_address,  # Value object
            placed_at=datetime.now(timezone.utc)
        ))
```

## Event Data from Multiple Sources

Event data can come from aggregate state, method parameters, or computed values:

```python
@domain.event(part_of="Account")
class MoneyWithdrawn:
    account_id: String(required=True, identifier=True)
    amount = ValueObject(Money, required=True)
    new_balance = ValueObject(Money, required=True)
    transaction_id: String(required=True)
    withdrawn_at: DateTime(required=True)

@domain.aggregate
class Account:
    account_id: String(required=True, identifier=True)
    balance = ValueObject(Money)

    def withdraw(self, amount: Money, transaction_id: str):
        if amount.amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if self.balance.amount < amount.amount:
            raise ValueError("Insufficient funds")

        # Update state
        new_balance = Money(
            amount=self.balance.amount - amount.amount,
            currency=self.balance.currency
        )
        self.balance = new_balance

        # Raise event with data from multiple sources
        self.raise_(MoneyWithdrawn(
            account_id=self.account_id,  # From aggregate state
            amount=amount,  # From method parameter
            new_balance=new_balance,  # Computed value
            transaction_id=transaction_id,  # From method parameter
            withdrawn_at=datetime.now(timezone.utc)  # Generated value
        ))
```

## Conditional Event Raising

Raise different events based on conditions:

```python
@domain.event(part_of="Inventory")
class StockReserved:
    product_id: String(required=True, identifier=True)
    quantity: Integer(required=True)
    reserved_at: DateTime(required=True)

@domain.event(part_of="Inventory")
class LowStockAlert:
    product_id: String(required=True, identifier=True)
    current_quantity: Integer(required=True)
    threshold: Integer(required=True)
    alerted_at: DateTime(required=True)

@domain.aggregate
class Inventory:
    product_id: String(required=True, identifier=True)
    quantity: Integer(default=0)
    low_stock_threshold: Integer(default=10)

    def reserve(self, quantity: int):
        if quantity > self.quantity:
            raise ValueError("Insufficient stock")

        self.quantity -= quantity
        now = datetime.now(timezone.utc)

        # Always raise stock reserved event
        self.raise_(StockReserved(
            product_id=self.product_id,
            quantity=quantity,
            reserved_at=now
        ))

        # Conditionally raise low stock alert
        if self.quantity <= self.low_stock_threshold:
            self.raise_(LowStockAlert(
                product_id=self.product_id,
                current_quantity=self.quantity,
                threshold=self.low_stock_threshold,
                alerted_at=now
            ))
```

## Events in Different Lifecycle Methods

### Creation

```python
@domain.event(part_of="Customer")
class CustomerRegistered:
    customer_id: String(required=True, identifier=True)
    email: String(required=True)
    registered_at: DateTime(required=True)

@domain.aggregate
class Customer:
    customer_id: String(required=True, identifier=True)
    email: String(required=True)
    status: String(default="active")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Raise event on creation
        self.raise_(CustomerRegistered(
            customer_id=self.customer_id,
            email=self.email,
            registered_at=datetime.now(timezone.utc)
        ))
```

### Updates

```python
@domain.event(part_of="Product")
class PriceChanged:
    product_id: String(required=True, identifier=True)
    old_price = ValueObject(Money, required=True)
    new_price = ValueObject(Money, required=True)
    changed_at: DateTime(required=True)

@domain.aggregate
class Product:
    product_id: String(required=True, identifier=True)
    price = ValueObject(Money)

    def update_price(self, new_price: Money):
        old_price = self.price
        self.price = new_price

        self.raise_(PriceChanged(
            product_id=self.product_id,
            old_price=old_price,
            new_price=new_price,
            changed_at=datetime.now(timezone.utc)
        ))
```

### Deletion/Archival

```python
@domain.event(part_of="Order")
class OrderCancelled:
    order_id: String(required=True, identifier=True)
    cancelled_at: DateTime(required=True)
    reason: String(required=True)

@domain.aggregate
class Order:
    order_id: String(required=True, identifier=True)
    status: String(default="draft")

    def cancel(self, reason: str):
        if self.status == "delivered":
            raise ValueError("Cannot cancel delivered order")

        self.status = "cancelled"

        self.raise_(OrderCancelled(
            order_id=self.order_id,
            cancelled_at=datetime.now(timezone.utc),
            reason=reason
        ))
```

## Best Practices

### 1. Raise Events After State Changes

```python
# Good: State change first, then event
def place(self):
    self.status = "placed"  # State change
    self.raise_(OrderPlaced(...))  # Event

# Bad: Event before state change
def place(self):
    self.raise_(OrderPlaced(...))  # Event first - wrong!
    self.status = "placed"  # State change after
```

### 2. Use Descriptive Event Names

```python
# Good: Clear what happened
self.raise_(OrderPlaced(...))
self.raise_(PaymentConfirmed(...))
self.raise_(ShipmentDelivered(...))

# Bad: Vague names
self.raise_(OrderUpdated(...))
self.raise_(StateChanged(...))
```

### 3. Include Sufficient Context

```python
# Good: Event has all necessary info
self.raise_(OrderPlaced(
    order_id=self.order_id,
    customer_id=self.customer_id,
    total=self.total,
    placed_at=datetime.now(timezone.utc)
))

# Bad: Missing important context
self.raise_(OrderPlaced(
    order_id=self.order_id
    # Missing customer_id, total, timestamp
))
```

### 4. Don't Raise Events on Validation Failures

```python
# Good: Only raise event if operation succeeds
def place(self):
    if self.status != "draft":
        raise ValueError("Order already placed")  # No event raised

    self.status = "placed"
    self.raise_(OrderPlaced(...))  # Event only on success

# Bad: Raising events for failures
def place(self):
    if self.status != "draft":
        self.raise_(OrderPlacementFailed(...))  # Don't do this
        raise ValueError("Order already placed")
```

## Event Persistence

Events are automatically persisted when the aggregate is saved:

```python
from protean.globals import current_domain

# Create and save aggregate
order = Order(
    order_id="ORD-001",
    customer_id="CUST-123",
    total=Money(amount=99.99, currency="USD")
)
order.place()  # Raises OrderPlaced event

# Save aggregate - events are persisted automatically
repo = current_domain.repository_for(Order)
repo.add(order)  # Aggregate and events saved together

# Events are now in the event store and will trigger handlers
```

## Related

- [Delta Events](./delta-events.md) - Types of events to raise
- [With Value Objects](./with-value-objects.md) - Including value objects in events
- `aggregate` - Aggregate methods that raise events
- `event-handler` - How events are consumed
