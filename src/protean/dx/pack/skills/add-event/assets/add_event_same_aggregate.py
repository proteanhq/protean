"""
Complete event flow where the event handler belongs to the same aggregate.

This example demonstrates the full add-event workflow for a same-aggregate reaction:
- Event class with past-tense naming (OrderPlaced)
- Aggregate method that performs state change and raises the event
- Event handler that processes the event and updates the same aggregate
- Synchronous event processing for immediate side effects

Scenario:
    When an order is placed, the system generates a confirmation number
    for the same order. The event handler listens on the Order aggregate's
    own stream and enriches the order with a confirmation number.

Workflow:
    Order.place() → self.raise_(OrderPlaced) → repository.add(order)
    → OrderEventHandler.on_order_placed() → load order → set confirmation → persist

Usage:
    order = Order(order_id="ORD-001", customer_id="CUST-123", total_amount=99.99)
    order.place()
    domain.repository_for(Order).add(order)
    # OrderEventHandler automatically processes the OrderPlaced event
"""

from protean import Domain, handle
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"


# --- Event ---


@domain.event(part_of="Order")
class OrderPlaced:
    """Event raised when an order is successfully placed.

    Named in past-tense (OrderPlaced, not PlaceOrder).
    Associated with Order aggregate via part_of string.
    Carries only the data consumers need.
    """

    order_id: Identifier(required=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)


# --- Aggregate ---


@domain.aggregate
class Order:
    """Order aggregate that raises events on state changes."""

    order_id: Identifier(identifier=True)
    customer_id: String(required=True)
    total_amount: Float(required=True)
    status: String(default="draft")
    confirmation_number: String()

    def place(self):
        """Place the order, transitioning from draft to placed.

        Business logic (guards) live here in the aggregate.
        After the state change succeeds, raise the event.
        """
        if self.status != "draft":
            raise ValueError(f"Cannot place order in '{self.status}' status")
        self.status = "placed"

        # Raise event AFTER state change succeeds
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                total_amount=self.total_amount,
            )
        )


# --- Event Handler (same-aggregate) ---


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    """Handler that processes events from the Order aggregate.

    Since part_of=Order and no stream_category is specified,
    it defaults to listening on the Order aggregate's own stream.

    Event handlers do NOT return values (CQRS fire-and-forget pattern).
    Each @handle method runs within an implicit UnitOfWork.
    """

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        """React to OrderPlaced by generating a confirmation number.

        Side effect: loads the order, assigns a confirmation number,
        and persists the updated order.
        """
        repo = domain.repository_for(Order)
        order = repo.get(event.order_id)
        order.confirmation_number = f"CONF-{event.order_id}"
        repo.add(order)


# Example usage
if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)

    with domain.domain_context():
        order = Order(
            order_id="ORD-12345",
            customer_id="CUST-67890",
            total_amount=149.99,
        )
        order.place()
        domain.repository_for(Order).add(order)

        # Verify event handler ran
        updated = domain.repository_for(Order).get("ORD-12345")
        print(f"Order {updated.order_id} confirmation: {updated.confirmation_number}")
