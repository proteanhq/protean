"""
Simple command handler with a single @handle method.

This example demonstrates:
- Basic command handler definition with @domain.command_handler decorator
- Required part_of parameter associating handler with an aggregate
- Single @handle method processing one command type
- The workflow: receive command -> create aggregate -> invoke method -> persist
- Synchronous command processing via domain.process()

Usage:
    command = PlaceOrder(
        order_id="ORD-001",
        customer_id="CUST-123",
        total_amount=99.99,
    )
    domain.process(command, asynchronous=False)
"""

from datetime import UTC, datetime

from protean import Domain, handle
from protean.fields import DateTime, Float, Identifier, String

# Domain setup
domain = Domain()


@domain.aggregate
class Order:
    """Order aggregate."""

    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    total_amount: Float()
    status: String(default="draft")
    placed_at: DateTime()

    def place(self, total_amount: float):
        """Place the order with the given total amount."""
        self.total_amount = total_amount
        self.status = "placed"
        self.placed_at = datetime.now(UTC)


@domain.command(part_of="Order")
class PlaceOrder:
    """Command to place a new order."""

    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    """Handler that processes the PlaceOrder command.

    This handler demonstrates the fundamental command handler pattern:
    1. Receive command
    2. Create (or load) the aggregate
    3. Invoke the aggregate method with data from the command
    4. Persist the aggregate via the repository
    """

    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        """Handle the PlaceOrder command.

        Creates a new Order aggregate, places it with the given amount,
        and persists it to the repository.
        """
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
        )
        order.place(total_amount=command.total_amount)

        # Persist the aggregate
        domain.repository_for(Order).add(order)

        return order.order_id


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Construct a command
        place_order_cmd = PlaceOrder(
            order_id="ORD-12345",
            customer_id="CUST-67890",
            total_amount=149.99,
        )

        print(f"Command: {place_order_cmd.__class__.__name__}")
        print(f"Order ID: {place_order_cmd.order_id}")
        print(f"Payload: {place_order_cmd.payload}")

        # Submit to domain for synchronous processing
        result = domain.process(place_order_cmd, asynchronous=False)
        print(f"\nPlaceOrder command processed. Result: {result}")
