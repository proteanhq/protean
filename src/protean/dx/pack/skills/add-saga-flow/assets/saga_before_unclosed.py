"""
Order fulfillment saga, left unclosed. This is the anti-pattern.

The same flow as saga_after_closed.py, but no handler is marked end=True and
there is no compensating failure path. The saga starts, advances through stock
reservation, payment, and shipment, and sets a "fulfilled" status, but it never
signals completion. Its instances stay open forever and keep accepting events.

Because no handler is marked end=True, `check` reports PROCESS_MANAGER_UNCLOSED
for OrderFulfillmentPM. saga_after_closed.py fixes it by marking a terminating
handler on each path.

The domain still initializes: PROCESS_MANAGER_UNCLOSED is an info-level
diagnostic, not an initialization error.

Usage:
    from saga_before_unclosed import OrderFulfillmentPM, domain

    domain.init(traverse=False)
    with domain.domain_context():
        pm = OrderFulfillmentPM(order_id="ORD-001", status="new")
"""

from protean import Domain, current_domain, handle
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain(__file__, "ecommerce")


# --- Commands (the saga issues these to drive each aggregate forward) ---


@domain.command(part_of="Inventory")
class ReserveStock:
    """Reserve stock for an order."""

    order_id: Identifier(required=True)


@domain.command(part_of="Payment")
class RequestPayment:
    """Request payment once stock is reserved."""

    order_id: Identifier(required=True)
    amount: Float(required=True)


@domain.command(part_of="Shipping")
class DispatchShipment:
    """Dispatch the shipment once payment is confirmed."""

    order_id: Identifier(required=True)


# --- Events (the saga reacts to these) ---


@domain.event(part_of="Order")
class OrderPlaced:
    """Raised when a customer places an order."""

    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.event(part_of="Inventory")
class StockReserved:
    """Raised when stock is reserved for an order."""

    order_id: Identifier(required=True)
    reservation_id: Identifier(required=True)


@domain.event(part_of="Payment")
class PaymentConfirmed:
    """Raised when payment for an order is confirmed."""

    order_id: Identifier(required=True)
    payment_id: Identifier(required=True)


@domain.event(part_of="Shipping")
class ShipmentDispatched:
    """Raised when the shipment for an order is dispatched."""

    order_id: Identifier(required=True)
    tracking_id: Identifier(required=True)


# --- Aggregates ---


@domain.aggregate
class Order:
    """Order aggregate representing a customer's purchase."""

    customer_id: Identifier(required=True)
    total: Float(required=True)
    status: String(default="new")


@domain.aggregate
class Inventory:
    """Inventory aggregate holding stock for a product."""

    order_id: Identifier(required=True)


@domain.aggregate
class Payment:
    """Payment aggregate representing a financial transaction."""

    order_id: Identifier(required=True)


@domain.aggregate
class Shipping:
    """Shipping aggregate representing a shipment."""

    order_id: Identifier(required=True)


# --- Process Manager (the saga, left open) ---


@domain.process_manager(
    stream_categories=[
        "ecommerce::order",
        "ecommerce::inventory",
        "ecommerce::payment",
        "ecommerce::shipping",
    ]
)
class OrderFulfillmentPM:
    """Coordinate order fulfillment, but never close the saga.

    Every handler advances the flow, yet none is marked end=True and none calls
    mark_as_complete(). The saga never retires an instance, so `check` reports
    PROCESS_MANAGER_UNCLOSED.
    """

    order_id: Identifier()
    total: Float()
    status: String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        """Start the saga and reserve stock."""
        self.order_id = event.order_id
        self.total = event.total
        self.status = "reserving_stock"
        current_domain.process(ReserveStock(order_id=event.order_id))

    @handle(StockReserved, correlate="order_id")
    def on_stock_reserved(self, event: StockReserved) -> None:
        """Request payment once stock is reserved."""
        self.status = "awaiting_payment"
        current_domain.process(
            RequestPayment(order_id=self.order_id, amount=self.total)
        )

    @handle(PaymentConfirmed, correlate="order_id")
    def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
        """Dispatch the shipment once payment is confirmed."""
        self.status = "shipping"
        current_domain.process(DispatchShipment(order_id=self.order_id))

    @handle(ShipmentDispatched, correlate="order_id")
    def on_shipment_dispatched(self, event: ShipmentDispatched) -> None:
        """Set a terminal status, but never close the saga (no end=True)."""
        self.status = "fulfilled"
