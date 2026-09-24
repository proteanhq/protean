"""
Fact event containing complete aggregate state.

This example demonstrates:
- Fact events (complete state snapshots)
- Event-carried State Transfer pattern
- Comprehensive data for external consumers
- Difference between delta events and fact events
- When to use fact events vs delta events

Usage:
    from protean import Domain
    domain = Domain()

    # Fact event with complete order state
    snapshot = OrderSnapshot(
        order_id="ORD-001",
        customer_id="CUST-123",
        status="shipped",
        items=[...],  # All order items
        total=Money(amount=199.99, currency="USD"),
        ...
    )
"""

from datetime import UTC, datetime

from protean import Domain
from protean.fields import DateTime, Dict, Float, List, String, ValueObject

# Domain setup
domain = Domain()


@domain.value_object
class Money:
    """Value object for monetary amounts."""

    amount: Float(required=True)
    currency: String(max_length=3, default="USD")


@domain.value_object
class Address:
    """Value object for addresses."""

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
class Customer:
    """Customer aggregate."""

    customer_id: String(required=True, identifier=True)


# Delta events (incremental changes)
@domain.event(part_of="Order")
class OrderPlaced:
    """Delta event - captures just the placement action."""

    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)


@domain.event(part_of="Order")
class OrderShipped:
    """Delta event - captures just the shipping action."""

    __version__ = 1

    order_id: String(required=True, identifier=True)
    shipped_at: DateTime(required=True)
    tracking_number: String(required=True)


# Fact event (complete state snapshot)
@domain.event(part_of="Order")
class OrderSnapshot:
    """Fact event containing complete order state.

    This event enables Event-carried State Transfer pattern.
    External consumers receive all necessary information without
    needing to track history or query back to the order service.
    """

    __version__ = 1

    # Identity
    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)

    # Current state
    status: String(required=True)

    # Complete order data
    items: List()  # All order items with full details
    total = ValueObject(Money, required=True)
    subtotal = ValueObject(Money)
    tax = ValueObject(Money)
    shipping_cost = ValueObject(Money)

    # Addresses
    shipping_address = ValueObject(Address, required=True)
    billing_address = ValueObject(Address)

    # Complete timeline
    placed_at: DateTime()
    shipped_at: DateTime()
    delivered_at: DateTime()
    cancelled_at: DateTime()

    # Additional context
    notes: String(max_length=1000)
    metadata: Dict()


@domain.event(part_of="Customer")
class CustomerProfileSnapshot:
    """Fact event with complete customer profile.

    Published to CRM systems and external services that need
    the full customer profile without querying back.
    """

    __version__ = 1

    # Identity
    customer_id: String(required=True, identifier=True)
    email: String(required=True, max_length=255)

    # Profile
    full_name: String(required=True, max_length=200)
    phone: String(max_length=20)
    primary_address = ValueObject(Address)

    # Account details
    status: String(required=True)
    account_type: String(required=True)
    loyalty_tier: String(max_length=50)

    # Statistics
    total_orders: Float(default=0)
    lifetime_value = ValueObject(Money)

    # Metadata
    created_at: DateTime(required=True)
    last_login_at: DateTime()
    preferences: Dict()


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Delta events - lightweight, incremental changes
        order_placed = OrderPlaced(
            order_id="ORD-12345",
            customer_id="CUST-67890",
            placed_at=datetime.now(UTC),
        )

        order_shipped = OrderShipped(
            order_id="ORD-12345",
            shipped_at=datetime.now(UTC),
            tracking_number="TRK-999888",
        )

        print("Delta Events (Incremental Changes):")
        print(f"  {order_placed.__class__.__name__}: {order_placed.order_id}")
        print(f"  {order_shipped.__class__.__name__}: {order_shipped.tracking_number}")

        # Fact event - complete state snapshot
        order_snapshot = OrderSnapshot(
            order_id="ORD-12345",
            customer_id="CUST-67890",
            status="shipped",
            items=[
                {
                    "product_id": "PROD-001",
                    "name": "Wireless Mouse",
                    "quantity": 2,
                    "unit_price": 29.99,
                },
                {
                    "product_id": "PROD-002",
                    "name": "USB Keyboard",
                    "quantity": 1,
                    "unit_price": 49.99,
                },
            ],
            total=Money(amount=119.97, currency="USD"),
            subtotal=Money(amount=109.97, currency="USD"),
            tax=Money(amount=10.00, currency="USD"),
            shipping_cost=Money(amount=0.00, currency="USD"),
            shipping_address=Address(
                street="456 Market St",
                city="San Francisco",
                state="CA",
                postal_code="94102",
                country="USA",
            ),
            billing_address=Address(
                street="456 Market St",
                city="San Francisco",
                state="CA",
                postal_code="94102",
                country="USA",
            ),
            placed_at=datetime(2024, 2, 1, 10, 0, 0, tzinfo=UTC),
            shipped_at=datetime(2024, 2, 2, 14, 30, 0, tzinfo=UTC),
            notes="Gift wrap requested",
        )

        print("\nFact Event (Complete State Snapshot):")
        print(f"  Event: {order_snapshot.__class__.__name__}")
        print(f"  Order ID: {order_snapshot.order_id}")
        print(f"  Status: {order_snapshot.status}")
        print(f"  Items: {len(order_snapshot.items)} items")
        print(f"  Total: {order_snapshot.total.amount} {order_snapshot.total.currency}")
        print(
            f"  Shipping: {order_snapshot.shipping_address.city}, "
            f"{order_snapshot.shipping_address.state}"
        )
        print(f"  Placed: {order_snapshot.placed_at}")
        print(f"  Shipped: {order_snapshot.shipped_at}")

        # Customer profile snapshot
        customer_snapshot = CustomerProfileSnapshot(
            customer_id="CUST-67890",
            email="john.doe@example.com",
            full_name="John Doe",
            phone="+1-555-0123",
            primary_address=Address(
                street="456 Market St",
                city="San Francisco",
                state="CA",
                postal_code="94102",
                country="USA",
            ),
            status="active",
            account_type="premium",
            loyalty_tier="gold",
            total_orders=15,
            lifetime_value=Money(amount=2499.85, currency="USD"),
            created_at=datetime(2023, 1, 15, 9, 0, 0, tzinfo=UTC),
            last_login_at=datetime.now(UTC),
            preferences={"newsletter": True, "sms_notifications": False},
        )

        print("\nCustomer Snapshot:")
        print(f"  Name: {customer_snapshot.full_name}")
        print(f"  Email: {customer_snapshot.email}")
        print(f"  Tier: {customer_snapshot.loyalty_tier}")
        print(f"  Total Orders: {customer_snapshot.total_orders}")
        print(
            f"  Lifetime Value: {customer_snapshot.lifetime_value.amount} "
            f"{customer_snapshot.lifetime_value.currency}"
        )
