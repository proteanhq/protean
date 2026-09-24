"""
Complete example of raising events from aggregates.

This example demonstrates:
- Raising events using self.raise_() method
- Events raised AFTER state changes
- Passing data from aggregate to events
- Raising multiple events from one method
- Events with value objects
- Conditional event raising
- Event persistence with aggregates

Usage:
    order = Order(
        order_id="ORD-001",
        customer_id="CUST-123",
        total=Money(amount=99.99, currency="USD")
    )
    order.place()  # Raises OrderPlaced event

    repo.add(order)  # Persists aggregate and events
"""

from datetime import UTC, datetime

from protean import Domain
from protean.fields import (
    DateTime,
    Float,
    HasMany,
    Integer,
    String,
    ValueObject,
)

# Domain setup
domain = Domain()


# Value Objects
@domain.value_object
class Money:
    """Value object for monetary amounts."""

    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError("Cannot add different currencies")
        return Money(amount=self.amount + other.amount, currency=self.currency)


@domain.value_object
class Address:
    """Value object for addresses."""

    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    state: String(max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)


# Events
@domain.event(part_of="Order")
class OrderPlaced:
    """Event raised when an order is placed."""

    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    total = ValueObject(Money, required=True)
    placed_at: DateTime(required=True)


@domain.event(part_of="Order")
class OrderShipped:
    """Event raised when an order is shipped."""

    __version__ = 1

    order_id: String(required=True, identifier=True)
    shipped_at: DateTime(required=True)
    shipping_address = ValueObject(Address, required=True)
    tracking_number: String(required=True)


@domain.event(part_of="Order")
class OrderCancelled:
    """Event raised when an order is cancelled."""

    __version__ = 1

    order_id: String(required=True, identifier=True)
    cancelled_at: DateTime(required=True)
    reason: String(required=True)


@domain.event(part_of="Inventory")
class LowInventoryAlert:
    """Event raised when inventory falls below threshold."""

    __version__ = 1

    product_id: String(required=True, identifier=True)
    order_id: String(required=True)
    remaining_quantity: Integer(required=True)
    alerted_at: DateTime(required=True)


@domain.entity(part_of="Order")
class OrderItem:
    """Entity representing an order line item."""

    product_id: String(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price = ValueObject(Money, required=True)

    @property
    def subtotal(self) -> Money:
        return Money(
            amount=self.unit_price.amount * self.quantity,
            currency=self.unit_price.currency,
        )


# Aggregate
@domain.aggregate
class Order:
    """Order aggregate that raises events on state changes."""

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")

    items = HasMany(OrderItem)
    total = ValueObject(Money)
    shipping_address = ValueObject(Address)

    def place(self):
        """Place the order, raising OrderPlaced event."""
        # 1. Validate preconditions
        if self.status != "draft":
            raise ValueError("Order already placed")
        if not self.items:
            raise ValueError("Cannot place empty order")
        if not self.total or self.total.amount <= 0:
            raise ValueError("Order must have a positive total")

        # 2. Change state
        self.status = "placed"
        placed_at = datetime.now(UTC)

        # 3. Raise event AFTER state change
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                total=self.total,
                placed_at=placed_at,
            )
        )

    def ship(self, tracking_number: str):
        """Ship the order, raising OrderShipped event."""
        # Validate
        if self.status != "placed":
            raise ValueError("Order must be placed before shipping")
        if not self.shipping_address:
            raise ValueError("Shipping address required")

        # Change state
        self.status = "shipped"
        shipped_at = datetime.now(UTC)

        # Raise event with value object from aggregate
        self.raise_(
            OrderShipped(
                order_id=self.order_id,
                shipped_at=shipped_at,
                shipping_address=self.shipping_address,
                tracking_number=tracking_number,
            )
        )

    def cancel(self, reason: str):
        """Cancel the order, raising OrderCancelled event."""
        # Validate
        if self.status == "shipped":
            raise ValueError("Cannot cancel shipped order")
        if self.status == "delivered":
            raise ValueError("Cannot cancel delivered order")

        # Change state
        self.status = "cancelled"
        cancelled_at = datetime.now(UTC)

        # Raise event with data from parameter
        self.raise_(
            OrderCancelled(
                order_id=self.order_id,
                cancelled_at=cancelled_at,
                reason=reason,
            )
        )


@domain.aggregate
class Inventory:
    """Inventory aggregate demonstrating conditional event raising."""

    product_id: String(required=True, identifier=True)
    quantity: Integer(default=0, min_value=0)
    low_stock_threshold: Integer(default=10)

    def reserve(self, quantity: int, order_id: str):
        """Reserve inventory, conditionally raising low stock alert."""
        if quantity > self.quantity:
            raise ValueError("Insufficient stock")

        # Change state
        self.quantity -= quantity

        # Conditionally raise low stock alert
        if self.quantity <= self.low_stock_threshold:
            self.raise_(
                LowInventoryAlert(
                    order_id=order_id,
                    product_id=self.product_id,
                    remaining_quantity=self.quantity,
                    alerted_at=datetime.now(UTC),
                )
            )


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create order
        order = Order(
            order_id="ORD-12345",
            customer_id="CUST-67890",
            total=Money(amount=149.99, currency="USD"),
            shipping_address=Address(
                street="456 Market Street",
                city="San Francisco",
                state="CA",
                postal_code="94102",
                country="USA",
            ),
        )

        # Add items
        order.add_items(
            OrderItem(
                product_id="PROD-001",
                quantity=2,
                unit_price=Money(amount=49.99, currency="USD"),
            )
        )
        order.add_items(
            OrderItem(
                product_id="PROD-002",
                quantity=1,
                unit_price=Money(amount=50.01, currency="USD"),
            )
        )

        print(f"Order created: {order.order_id}")
        print(f"Status: {order.status}")
        print(f"Events raised: {len(order._events)}")

        # Place order - raises OrderPlaced event
        order.place()

        print("\nAfter placing order:")
        print(f"Status: {order.status}")
        print(f"Events raised: {len(order._events)}")
        print(f"Event types: {[e.__class__.__name__ for e in order._events]}")

        # Get the event
        order_placed_event = order._events[0]
        print("\nOrderPlaced event details:")
        print(f"  Order ID: {order_placed_event.order_id}")
        print(f"  Customer ID: {order_placed_event.customer_id}")
        print(
            f"  Total: {order_placed_event.total.amount} {order_placed_event.total.currency}"
        )
        print(f"  Placed At: {order_placed_event.placed_at}")

        # Ship order - raises OrderShipped event
        order.ship(tracking_number="TRK-999888777")

        print("\nAfter shipping order:")
        print(f"Status: {order.status}")
        print(f"Events raised: {len(order._events)}")
        print(f"Latest event: {order._events[-1].__class__.__name__}")

        # Create another order and cancel it
        order2 = Order(
            order_id="ORD-99999",
            customer_id="CUST-11111",
            total=Money(amount=50.00, currency="USD"),
        )
        order2.add_items(
            OrderItem(
                product_id="PROD-003",
                quantity=1,
                unit_price=Money(amount=50.00, currency="USD"),
            )
        )
        order2.place()
        order2.cancel(reason="Customer requested cancellation")

        print("\nCancelled order:")
        print(f"Order ID: {order2.order_id}")
        print(f"Status: {order2.status}")
        print(f"Events: {[e.__class__.__name__ for e in order2._events]}")

        # Inventory with conditional event
        inventory = Inventory(
            product_id="PROD-001", quantity=15, low_stock_threshold=10
        )

        print("\nInventory before reservation:")
        print(f"Product: {inventory.product_id}")
        print(f"Quantity: {inventory.quantity}")
        print(f"Events: {len(inventory._events)}")

        # Reserve stock (crosses low stock threshold)
        inventory.reserve(quantity=8, order_id="ORD-12345")

        print("\nInventory after reservation:")
        print(f"Quantity: {inventory.quantity}")
        print(f"Events raised: {len(inventory._events)}")
        if inventory._events:
            print(f"Event: {inventory._events[0].__class__.__name__}")
            alert = inventory._events[0]
            print(f"  Remaining: {alert.remaining_quantity}")
