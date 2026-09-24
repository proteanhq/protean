"""
Simple delta event with minimal fields.

This example demonstrates:
- Basic event definition with @domain.event decorator
- Past-tense naming convention (OrderPlaced, not PlaceOrder)
- Required part_of parameter associating event with aggregate
- Event versioning with __version__ attribute
- Simple field types (String, DateTime)
- Event immutability

Usage:
    from protean import Domain
    domain = Domain()

    event = OrderPlaced(
        order_id="ORD-001",
        customer_id="CUST-123",
        placed_at=datetime.now(timezone.utc)
    )
"""

from datetime import UTC, datetime

from protean import Domain
from protean.fields import DateTime, String

# Domain setup (required for runnable examples)
domain = Domain()


# Aggregates (required for events to reference)
@domain.aggregate
class Order:
    """Order aggregate."""

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    status: String(default="draft")


@domain.aggregate
class Product:
    """Product aggregate."""

    product_id: String(required=True, identifier=True)
    name: String(required=True, max_length=200)


@domain.event(part_of="Order")
class OrderPlaced:
    """Event raised when an order is placed.

    This is a delta event - it captures the incremental state change
    (order transitioning from draft to placed status).
    """

    __version__ = 1

    order_id: String(required=True, identifier=True)
    customer_id: String(required=True)
    placed_at: DateTime(required=True)


@domain.event(part_of="Product")
class ProductCreated:
    """Event raised when a new product is created."""

    __version__ = 1

    product_id: String(required=True, identifier=True)
    name: String(required=True, max_length=200)
    created_at: DateTime(required=True)


@domain.event(part_of="Order")
class OrderCancelled:
    """Event raised when an order is cancelled."""

    __version__ = 1

    order_id: String(required=True, identifier=True)
    cancelled_at: DateTime(required=True)
    reason: String(required=True, max_length=500)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create event instances
        order_placed = OrderPlaced(
            order_id="ORD-12345",
            customer_id="CUST-67890",
            placed_at=datetime.now(UTC),
        )

        print(f"Event: {order_placed.__class__.__name__}")
        print(f"Order ID: {order_placed.order_id}")
        print(f"Customer ID: {order_placed.customer_id}")
        print(f"Placed At: {order_placed.placed_at}")
        print(f"Version: {order_placed.__version__}")

        # Events are immutable
        try:
            order_placed.order_id = "CHANGED"
        except Exception as e:
            print(f"\nEvents are immutable: {type(e).__name__}")

        # Create product created event
        product_created = ProductCreated(
            product_id="PROD-001",
            name="Wireless Mouse",
            created_at=datetime.now(UTC),
        )

        print(f"\nEvent: {product_created.__class__.__name__}")
        print(f"Product ID: {product_created.product_id}")
        print(f"Name: {product_created.name}")
