"""
Event handler that belongs to and handles events from the same aggregate.

This example demonstrates:
- Basic event handler definition with @domain.event_handler decorator
- Required part_of parameter associating handler with an aggregate
- Single @handle method processing one event type
- Event handler reacting to events raised by its own aggregate
- Synchronous event processing via domain.config["event_processing"] = "sync"
- Event handlers do NOT return values (CQRS pattern)

Usage:
    order = Order(order_id="ORD-001", customer_id="CUST-123", total_amount=99.99)
    order.place()
    domain.repository_for(Order).add(order)
    # OrderEventHandler automatically processes OrderPlaced event
"""

from protean import Domain, handle
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"


@domain.event(part_of="Order")
class OrderPlaced:
    """Event raised when an order is placed."""

    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)


@domain.aggregate
class Order:
    """Order aggregate that raises events on state changes."""

    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    total_amount: Float()
    status: String(default="draft")
    confirmation_number: String()

    def place(self):
        """Place the order, raising OrderPlaced event."""
        if self.status != "draft":
            raise ValueError(f"Cannot place order in '{self.status}' status")
        self.status = "placed"
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                total_amount=self.total_amount,
            )
        )


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    """Handler that processes events from the Order aggregate.

    This event handler belongs to the Order aggregate and listens to
    events on the Order aggregate's own stream. It generates a
    confirmation number when an order is placed.

    Since part_of=Order and no stream_category is specified,
    the handler defaults to listening on the Order stream.
    """

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        """Handle OrderPlaced event by generating a confirmation number.

        Loads the order from the repository, assigns a confirmation number,
        and persists the updated order.
        """
        repo = domain.repository_for(Order)
        order = repo.get(event.order_id)
        order.confirmation_number = f"CONF-{event.order_id}"
        repo.add(order)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create and place an order
        order = Order(
            order_id="ORD-12345",
            customer_id="CUST-67890",
            total_amount=149.99,
        )
        order.place()
        domain.repository_for(Order).add(order)

        # Verify event handler ran
        updated_order = domain.repository_for(Order).get("ORD-12345")
        print(
            f"Order {updated_order.order_id} confirmation: {updated_order.confirmation_number}"
        )
