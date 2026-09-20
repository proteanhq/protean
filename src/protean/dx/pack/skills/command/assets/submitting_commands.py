"""
Submitting commands for processing via domain.process().

This example demonstrates:
- Creating commands and submitting them to the domain
- Command handler association and dispatching
- Synchronous command processing (asynchronous=False)
- Command metadata (timestamps, unique IDs)
- Complete command workflow: construct -> submit -> handle

Usage:
    command = PlaceOrder(
        order_id="ORD-001",
        customer_id="CUST-123",
        total_amount=99.99
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

    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float()
    status: String(default="draft")
    placed_at: DateTime()

    def place(self, total_amount: float):
        """Place the order with the given total."""
        self.total_amount = total_amount
        self.status = "placed"
        self.placed_at = datetime.now(UTC)


@domain.aggregate
class Shipment:
    """Shipment aggregate."""

    shipment_id: Identifier(required=True)
    order_id: String(required=True)
    status: String(default="pending")


@domain.command(part_of="Order")
class PlaceOrder:
    """Command to place an order."""

    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)


@domain.command(part_of="Shipment")
class CreateShipment:
    """Command to create a shipment for an order."""

    shipment_id: Identifier(required=True)
    order_id: String(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    """Handler that processes order-related commands."""

    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder):
        """Handle the PlaceOrder command by creating and placing an order.

        In a full application, you would persist the aggregate using:
            self.repository.add(order)
        This requires a configured persistence provider (database).
        """
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
        )
        order.place(total_amount=command.total_amount)


@domain.command_handler(part_of=Shipment)
class ShipmentCommandHandler:
    """Handler that processes shipment-related commands."""

    @handle(CreateShipment)
    def handle_create_shipment(self, command: CreateShipment):
        """Handle the CreateShipment command."""
        shipment = Shipment(
            shipment_id=command.shipment_id,
            order_id=command.order_id,
        )
        domain.repository_for(Shipment).add(shipment)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Step 1: Construct a command
        place_order_cmd = PlaceOrder(
            order_id="ORD-12345",
            customer_id="CUST-67890",
            total_amount=149.99,
        )

        print(f"Command: {place_order_cmd.__class__.__name__}")
        print(f"Order ID: {place_order_cmd.order_id}")
        print(f"Payload: {place_order_cmd.payload}")

        # Step 2: Submit to domain for synchronous processing
        domain.process(place_order_cmd, asynchronous=False)
        print("\nPlaceOrder command processed synchronously")

        # Step 3: Another command
        create_shipment_cmd = CreateShipment(
            shipment_id="SHIP-001",
            order_id="ORD-12345",
        )

        domain.process(create_shipment_cmd, asynchronous=False)
        print("CreateShipment command processed synchronously")
