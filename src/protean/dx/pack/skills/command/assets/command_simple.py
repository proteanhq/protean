"""
Simple commands with basic fields.

This example demonstrates:
- Basic command definition with @domain.command decorator
- Imperative naming convention (PlaceOrder, not OrderPlaced)
- Required part_of parameter associating command with aggregate
- Simple field types (String, Integer, Float, DateTime, Identifier)
- Command immutability
- Command payload as dict

Usage:
    from protean import Domain
    domain = Domain()

    command = PlaceOrder(
        order_id="ORD-001",
        customer_id="CUST-123",
        product_id="PROD-001",
        quantity=2
    )
"""

from datetime import UTC, datetime

from protean import Domain
from protean.fields import DateTime, Float, Identifier, Integer, String

# Domain setup (required for runnable examples)
domain = Domain()


# Aggregates (required for commands to reference)
@domain.aggregate
class Order:
    """Order aggregate."""

    order_id: Identifier(required=True)
    customer_id: String(required=True)
    status: String(default="draft")


@domain.aggregate
class User:
    """User aggregate."""

    user_id: Identifier(required=True)
    email: String(required=True)


@domain.aggregate
class Reservation:
    """Reservation aggregate."""

    reservation_id: Identifier(required=True)
    status: String(default="pending")


@domain.command(part_of="Order")
class PlaceOrder:
    """Command to place a new order.

    This is a simple command with basic fields that carries
    the intent to create and place a new order.
    """

    order_id: Identifier(required=True)
    customer_id: String(required=True)
    product_id: String(required=True)
    quantity: Integer(required=True)
    total_amount: Float(required=True)


@domain.command(part_of="User")
class RegisterUser:
    """Command to register a new user."""

    user_id: Identifier(required=True)
    email: String(required=True, max_length=250)
    username: String(required=True, max_length=50)
    registered_at: DateTime()


@domain.command(part_of="Reservation")
class CancelReservation:
    """Command to cancel an existing reservation."""

    reservation_id: Identifier(required=True)
    cancelled_at: DateTime(required=True)
    reason: String(required=True, max_length=500)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create command instances
        place_order = PlaceOrder(
            order_id="ORD-12345",
            customer_id="CUST-67890",
            product_id="PROD-001",
            quantity=2,
            total_amount=99.98,
        )

        print(f"Command: {place_order.__class__.__name__}")
        print(f"Order ID: {place_order.order_id}")
        print(f"Customer ID: {place_order.customer_id}")
        print(f"Product ID: {place_order.product_id}")
        print(f"Quantity: {place_order.quantity}")
        print(f"Total Amount: {place_order.total_amount}")
        print(f"Payload: {place_order.payload}")

        # Commands are immutable
        try:
            place_order.order_id = "CHANGED"
        except Exception as e:
            print(f"\nCommands are immutable: {type(e).__name__}")

        # Create register user command
        register_user = RegisterUser(
            user_id="USER-001",
            email="alice@example.com",
            username="alice_smith",
            registered_at=datetime.now(UTC),
        )

        print(f"\nCommand: {register_user.__class__.__name__}")
        print(f"User ID: {register_user.user_id}")
        print(f"Email: {register_user.email}")

        # Create cancel reservation command
        cancel = CancelReservation(
            reservation_id="RES-999",
            cancelled_at=datetime.now(UTC),
            reason="Customer requested cancellation",
        )

        print(f"\nCommand: {cancel.__class__.__name__}")
        print(f"Reservation ID: {cancel.reservation_id}")
        print(f"Reason: {cancel.reason}")
