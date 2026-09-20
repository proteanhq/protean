"""
Event upcasters with event handlers and projectors.

This example demonstrates:
- Upcasting works transparently for event handlers and projectors
- Handlers always receive current-schema events, even when processing old events
- Event handler with @handle decorator receiving upcast events
- Projector with @handle decorator targeting a projection

Domain: Order analytics
    - OrderPlaced event evolved from v1 to v2 (renamed amount -> total, added currency)
    - OrderAnalyticsHandler processes order events for analytics
    - OrderSummaryProjector maintains an OrderSummary read model

Usage:
    from upcaster_with_event_handler import domain, Order, OrderPlaced

    domain.init(traverse=False)
    with domain.domain_context():
        order = Order.place(order_id="ORD-1", total=99.99, currency="USD")
"""

from protean import Domain, handle
from protean.core.aggregate import apply
from protean.core.upcaster import BaseUpcaster
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()

# Enable synchronous event processing so handlers run immediately
domain.config["event_processing"] = "sync"


# --- Events (current versions) ---


@domain.event(part_of="Order")
class OrderPlaced:
    """Order was placed. Current version: v2.

    Evolution history:
        v1: order_id, amount
        v2: order_id, total, currency (renamed amount -> total, added currency)
    """

    __version__ = 2

    order_id = Identifier(required=True)
    total = Float(required=True)
    currency = String(required=True)


@domain.event(part_of="Order")
class OrderShipped:
    """Order was shipped. Unchanged since v1."""

    order_id = Identifier(required=True)
    tracking_number = String(required=True)


# --- Upcaster ---


@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    """v1 -> v2: Rename 'amount' to 'total', add 'currency' = 'USD'."""

    def upcast(self, data: dict) -> dict:
        data["total"] = data.pop("amount")
        data["currency"] = "USD"
        return data


# --- Aggregate ---


@domain.aggregate(is_event_sourced=True)
class Order:
    """Event-sourced order aggregate."""

    order_id = Identifier(identifier=True)
    total = Float(default=0.0)
    currency = String(default="USD")
    status = String(default="DRAFT")
    tracking_number = String()

    @classmethod
    def place(cls, order_id, total, currency="USD"):
        """Factory: place a new order."""
        order = cls(order_id=order_id, total=total, currency=currency)
        order.raise_(OrderPlaced(order_id=order_id, total=total, currency=currency))
        return order

    def ship(self, tracking_number):
        """Ship the order."""
        if self.status == "SHIPPED":
            raise ValueError("Order is already shipped")
        self.raise_(
            OrderShipped(order_id=self.order_id, tracking_number=tracking_number)
        )

    @apply
    def on_placed(self, event: OrderPlaced):
        self.order_id = event.order_id
        self.total = event.total
        self.currency = event.currency
        self.status = "PLACED"

    @apply
    def on_shipped(self, event: OrderShipped):
        self.status = "SHIPPED"
        self.tracking_number = event.tracking_number


# --- Event Handler ---


@domain.event_handler(part_of=Order)
class OrderAnalyticsHandler:
    """Handles order events for analytics tracking.

    All handlers receive current-schema events. Old events stored as v1
    are automatically upcast to v2 before reaching @handle methods.
    """

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # Always receives current schema with total and currency
        print(
            f"Analytics: Order {event.order_id} placed for {event.total} {event.currency}"
        )

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        print(f"Analytics: Order {event.order_id} shipped with {event.tracking_number}")


# --- Projection + Projector ---


@domain.projection
class OrderSummary:
    """Read model for order summaries."""

    order_id = Identifier(identifier=True)
    total = Float()
    currency = String()
    status = String()
    tracking_number = String()


@domain.projector(projector_for=OrderSummary, aggregates=[Order])
class OrderSummaryProjector:
    """Maintains the OrderSummary read model from order events.

    Projectors also receive upcast events. When replaying historical events
    to rebuild projections, old events are automatically transformed.
    """

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # Always receives current schema
        return OrderSummary(
            order_id=event.order_id,
            total=event.total,
            currency=event.currency,
            status="PLACED",
        )

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        return OrderSummary(
            order_id=event.order_id,
            tracking_number=event.tracking_number,
            status="SHIPPED",
        )


# Example usage
if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)

    with domain.domain_context():
        # Place an order (handlers receive current v2 schema)
        order = Order.place(order_id="ORD-1", total=149.99, currency="EUR")
        print(f"\nOrder placed: {order.order_id}, status={order.status}")

        # Ship the order
        order.ship(tracking_number="TRACK-12345")
        print(f"Order shipped: tracking={order.tracking_number}")
