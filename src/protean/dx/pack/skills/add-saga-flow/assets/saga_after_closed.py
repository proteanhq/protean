"""
Order fulfillment saga, closed correctly.

One process manager coordinates the flow across Order, Inventory, Payment, and
Shipping. It issues a command at each step and drives the next aggregate forward
when that step's event arrives. The saga closes on two paths:

- Success: ShipmentDispatched ends the saga (end=True).
- Failure: PaymentFailed ends the saga (end=True) and issues compensating
  commands to release the stock reservation and cancel the order.

Because a handler is marked end=True on each terminal path, `check` reports no
PROCESS_MANAGER_UNCLOSED for this domain. Contrast with saga_before_unclosed.py,
which drops the end=True handlers and leaves the saga open.

This flow is broker-free: it defines the events, commands, aggregates, and the
process manager, so it initializes without any external broker.

Usage:
    from saga_after_closed import OrderFulfillmentPM, domain

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


@domain.command(part_of="Inventory")
class ReleaseReservation:
    """Compensating command: release a stock reservation."""

    order_id: Identifier(required=True)


@domain.command(part_of="Order")
class CancelOrder:
    """Compensating command: cancel the order."""

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


@domain.event(part_of="Payment")
class PaymentFailed:
    """Raised when payment for an order fails."""

    order_id: Identifier(required=True)
    reason: String(required=True)


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


# --- Process Manager (the saga) ---


@domain.process_manager(
    stream_categories=[
        "ecommerce::order",
        "ecommerce::inventory",
        "ecommerce::payment",
        "ecommerce::shipping",
    ]
)
class OrderFulfillmentPM:
    """Coordinate order fulfillment across four aggregates.

    Each handler advances the saga's state and issues the command for the next
    step. Two handlers close the saga:

    - on_shipment_dispatched (end=True): the success terminal.
    - on_payment_failed (end=True): the failure terminal, which also issues the
      compensating commands to undo the stock reservation and cancel the order.
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

    @handle(ShipmentDispatched, correlate="order_id", end=True)
    def on_shipment_dispatched(self, event: ShipmentDispatched) -> None:
        """Close the saga on the success path."""
        self.status = "fulfilled"

    @handle(PaymentFailed, correlate="order_id", end=True)
    def on_payment_failed(self, event: PaymentFailed) -> None:
        """Close the saga on the failure path and compensate earlier steps."""
        self.status = "cancelled"
        current_domain.process(ReleaseReservation(order_id=self.order_id))
        current_domain.process(CancelOrder(order_id=self.order_id))
