"""
Event with value objects for complex immutable data.

This example demonstrates:
- Events containing value objects (Money, Address)
- Using ValueObject() field to reference value objects
- Type safety and validation through value objects
- Multiple value objects in a single event
- Value object reusability across events

Usage:
    from protean import Domain
    domain = Domain()

    event = OrderPlaced(
        order_id="ORD-001",
        customer_id="CUST-123",
        total=Money(amount=99.99, currency="USD"),
        shipping_address=Address(street="123 Main St", city="SF", ...),
        placed_at=datetime.now(timezone.utc)
    )
"""

from datetime import UTC, datetime

from protean import Domain
from protean.fields import DateTime, Float, String, ValueObject

# Domain setup
domain = Domain()


@domain.value_object
class Money:
    """Value object representing monetary amounts with currency."""

    amount: Float(required=True)
    currency: String(max_length=3, default="USD")

    def add(self, other: "Money") -> "Money":
        """Add two money values (must be same currency)."""
        if self.currency != other.currency:
            raise ValueError(f"Cannot add {self.currency} and {other.currency}")
        return Money(amount=self.amount + other.amount, currency=self.currency)


@domain.value_object
class Address:
    """Value object representing a physical address."""

    street: String(required=True, max_length=200)
    city: String(required=True, max_length=100)
    state: String(max_length=50)
    postal_code: String(required=True, max_length=20)
    country: String(required=True, max_length=50)


# Aggregates (required for events to reference)
@domain.aggregate
class Order:
    """Order aggregate."""

    order_id: String(required=True, identifier=True)


@domain.aggregate
class Payment:
    """Payment aggregate."""

    payment_id: String(required=True, identifier=True)


@domain.event(part_of="Order")
class OrderPlaced:
    """Event raised when an order is placed, including value objects."""

    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)

    # Value objects for complex data
    total = ValueObject(Money, required=True)
    shipping_address = ValueObject(Address, required=True)
    billing_address = ValueObject(Address)

    placed_at: DateTime(required=True)


@domain.event(part_of="Payment")
class PaymentProcessed:
    """Event raised when a payment is processed."""

    __version__ = 1

    payment_id: String(required=True, identifier=True)
    order_id: String(required=True)

    # Money value object for payment amount
    amount = ValueObject(Money, required=True)

    processed_at: DateTime(required=True)
    payment_method: String(required=True, max_length=50)


@domain.event(part_of="Order")
class OrderShipped:
    """Event raised when an order is shipped."""

    __version__ = 1

    order_id: String(required=True, identifier=True)
    shipped_at: DateTime(required=True)

    # Address value object for shipping destination
    shipping_address = ValueObject(Address, required=True)

    tracking_number: String(required=True, max_length=100)
    carrier: String(required=True, max_length=50)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create value objects
        total = Money(amount=149.99, currency="USD")

        shipping_addr = Address(
            street="456 Market Street",
            city="San Francisco",
            state="CA",
            postal_code="94102",
            country="USA",
        )

        billing_addr = Address(
            street="789 Mission Street",
            city="San Francisco",
            state="CA",
            postal_code="94103",
            country="USA",
        )

        # Create event with value objects
        order_placed = OrderPlaced(
            order_id="ORD-98765",
            customer_id="CUST-12345",
            total=total,
            shipping_address=shipping_addr,
            billing_address=billing_addr,
            placed_at=datetime.now(UTC),
        )

        print(f"Event: {order_placed.__class__.__name__}")
        print(f"Order ID: {order_placed.order_id}")
        print(f"Total: {order_placed.total.amount} {order_placed.total.currency}")
        print(
            f"Shipping: {order_placed.shipping_address.street}, "
            f"{order_placed.shipping_address.city}, "
            f"{order_placed.shipping_address.state}"
        )

        # Create payment processed event
        payment = PaymentProcessed(
            payment_id="PAY-001",
            order_id="ORD-98765",
            amount=Money(amount=149.99, currency="USD"),
            processed_at=datetime.now(UTC),
            payment_method="credit_card",
        )

        print(f"\nEvent: {payment.__class__.__name__}")
        print(f"Payment Amount: {payment.amount.amount} {payment.amount.currency}")
        print(f"Payment Method: {payment.payment_method}")

        # Value objects are immutable
        try:
            total.amount = 999.99
        except Exception as e:
            print(f"\nValue objects are immutable: {type(e).__name__}")
