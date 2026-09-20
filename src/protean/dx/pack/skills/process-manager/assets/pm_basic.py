"""
Order fulfillment process manager with string correlation and full lifecycle.

This example demonstrates:
- Basic process manager definition with @domain.process_manager decorator
- stream_categories parameter subscribing to multiple aggregate streams
- String correlation routing events to the correct PM instance
- start=True to create new PM instances on the entry event
- end=True to auto-complete PM on failure path
- mark_as_complete() for explicit completion on success path
- PM fields persisted as transition events (event-sourced state)
- Multiple handler methods, each processing one event type

Domain: Order fulfillment across Order, Payment, and Shipping aggregates
    - OrderPlaced (start) -> awaiting_payment
    - PaymentConfirmed -> awaiting_shipment
    - PaymentFailed (end) -> cancelled
    - ShipmentDelivered (mark_as_complete) -> completed

Usage:
    from pm_basic import OrderFulfillmentPM, domain

    domain.init(traverse=False)
    with domain.domain_context():
        pm = OrderFulfillmentPM(order_id="ORD-001", status="new")
"""

from protean import Domain, handle
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain(__file__, "ecommerce")


# --- Events ---


@domain.event(part_of="Order")
class OrderPlaced:
    """Raised when a new order is placed by a customer."""

    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.event(part_of="Payment")
class PaymentConfirmed:
    """Raised when payment for an order is confirmed."""

    payment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    amount: Float(required=True)


@domain.event(part_of="Payment")
class PaymentFailed:
    """Raised when payment for an order fails."""

    payment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    reason: String(required=True)


@domain.event(part_of="Shipping")
class ShipmentDelivered:
    """Raised when a shipment is delivered to the customer."""

    order_id: Identifier(required=True)


# --- Aggregates ---


@domain.aggregate
class Order:
    """Order aggregate representing a customer's purchase."""

    customer_id: Identifier(required=True)
    total: Float(required=True)
    status: String(default="new")


@domain.aggregate
class Payment:
    """Payment aggregate representing a financial transaction."""

    order_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate
class Shipping:
    """Shipping aggregate representing a shipment."""

    order_id: Identifier(required=True)


# --- Process Manager ---


@domain.process_manager(
    stream_categories=[
        "ecommerce::order",
        "ecommerce::payment",
        "ecommerce::shipping",
    ]
)
class OrderFulfillmentPM:
    """Coordinates order fulfillment across Order, Payment, and Shipping.

    Lifecycle:
    1. OrderPlaced (start) -> status: awaiting_payment
    2. PaymentConfirmed -> status: awaiting_shipment
    3. PaymentFailed (end) -> status: cancelled (auto-completes PM)
    4. ShipmentDelivered -> status: completed (explicit mark_as_complete)
    """

    order_id: Identifier()
    payment_id: Identifier()
    status: String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        """Start the fulfillment process when an order is placed."""
        self.order_id = event.order_id
        self.status = "awaiting_payment"

    @handle(PaymentConfirmed, correlate="order_id")
    def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
        """Advance to shipment phase when payment is confirmed."""
        self.payment_id = event.payment_id
        self.status = "awaiting_shipment"

    @handle(PaymentFailed, correlate="order_id", end=True)
    def on_payment_failed(self, event: PaymentFailed) -> None:
        """Cancel the process when payment fails (auto-completes PM)."""
        self.status = "cancelled"

    @handle(ShipmentDelivered, correlate="order_id")
    def on_shipment_delivered(self, event: ShipmentDelivered) -> None:
        """Complete the process when shipment is delivered."""
        self.status = "completed"
        self.mark_as_complete()
