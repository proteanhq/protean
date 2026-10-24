# Raising Events from Aggregates

An aggregate raises an event from one of its methods with `self.raise_()`, right after the state change the event records. The event is queued on the aggregate and stored when the repository saves it.

That order is for an aggregate that stores its state. An event-sourced aggregate works the other way: the method raises the event, and its `@apply` handler changes the state. See the `event-sourced-aggregate` skill.

The complete implementation is in [assets/raising_events.py](../assets/raising_events.py).

## Raising Single Events

The examples on this page use a `Money` value object:

```python
from datetime import datetime, timezone

@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, default="USD")
```

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

    @classmethod
    def register(cls, customer_id: str, email: str) -> "Customer":
        customer = cls(customer_id=customer_id, email=email)
        # Raise event on creation
        customer.raise_(CustomerRegistered(
            customer_id=customer.customer_id,
            email=customer.email,
            registered_at=datetime.now(timezone.utc)
        ))
        return customer
```

Raise the creation event from a factory classmethod, not from `__init__`. The framework also calls `__init__` when it loads an aggregate that stores its state from the repository, so an event raised there would fire again on every load. An event-sourced aggregate is rebuilt from its events without calling `__init__`, but its creation event still belongs in a factory method.

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

## Event Persistence

Events are automatically persisted when the aggregate is saved:

```python
from protean import current_domain

domain.init(traverse=False)

with domain.domain_context():
    # Create the aggregate and change its state
    order = Order(order_id="ORD-001")
    order.cancel(reason="Customer request")  # Raises OrderCancelled

    # Save aggregate - events are persisted automatically
    repo = current_domain.repository_for(Order)
    repo.add(order)  # Aggregate and events saved together

    # Events are now in the event store and will trigger handlers
```

## Related

- [Delta Events](./delta-events.md): Types of events to raise
- [With Value Objects](./with-value-objects.md): Including value objects in events
- `aggregate`: Aggregate methods that raise events
- `event-handler`: How events are consumed
