"""
Order fulfillment saga, closed correctly.

One process manager coordinates the flow across Order, Inventory, Payment, and
Shipping. It issues a command at each step and drives the next aggregate forward
when that step's event arrives. The saga closes on each terminal path:

- Success: ShipmentDispatched ends the saga (end=True).
- Failure: PaymentFailed ends the saga (end=True) and issues compensating
  commands to release the stock reservation and cancel the order.

Because a handler is marked end=True on each terminal path, `check` reports no
PROCESS_MANAGER_UNCLOSED for this domain. Contrast with saga_before_unclosed.py,
which drops the end=True handlers and leaves the saga open.

The flow runs end to end: each command has a handler, and each aggregate raises
the event that drives the next step. Processing is synchronous, so one
PlaceOrder command runs the whole saga in-process, with no broker and no server.

Payment is the branch point. It confirms an amount up to PAYMENT_LIMIT and fails
anything above it, so the same flow reaches either terminal path.

Usage:
    from saga_after_closed import PlaceOrder, domain

    domain.init(traverse=False)
    with domain.domain_context():
        # Runs the saga through to "fulfilled"
        domain.process(
            PlaceOrder(order_id="ORD-001", customer_id="CUST-1", total=100.0)
        )
        # Over the limit: payment fails and the saga compensates
        domain.process(
            PlaceOrder(order_id="ORD-002", customer_id="CUST-1", total=900.0)
        )
"""

from protean import Domain, current_domain, handle
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain(__file__, "ecommerce")

# Run the saga in-process: events reach the process manager as soon as an
# aggregate is saved, and commands reach their handlers as soon as they are
# issued. A deployed domain leaves both asynchronous and lets the server drive
# each step.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"

# The amount Payment confirms up to. Above it, payment fails and the saga
# compensates.
PAYMENT_LIMIT = 500.0


# --- Commands (the saga issues these to drive each aggregate forward) ---


@domain.command(part_of="Order")
class PlaceOrder:
    """Place an order. This command starts the flow.

    The caller chooses the order id: it is the saga's correlation key, so every
    later step carries it.
    """

    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.command(part_of="Inventory")
class CreateReservation:
    """Create a stock reservation for an order."""

    order_id: Identifier(required=True)


@domain.command(part_of="Payment")
class RequestPayment:
    """Request payment once stock is reserved."""

    order_id: Identifier(required=True)
    amount: Float(required=True)


@domain.command(part_of="Shipping")
class CreateShipment:
    """Create the shipment once payment is confirmed."""

    order_id: Identifier(required=True)


@domain.command(part_of="Inventory")
class CancelReservation:
    """Compensating command: release a stock reservation."""

    reservation_id: Identifier(required=True)


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


# --- Aggregates (each step's work, and the event that reports it) ---


@domain.aggregate
class Order:
    """Order aggregate representing a customer's purchase."""

    customer_id: Identifier(required=True)
    total: Float(required=True)
    status: String(default="new")

    @classmethod
    def place(cls, order_id: str, customer_id: str, total: float) -> "Order":
        """Place an order. OrderPlaced starts the saga."""
        order = cls(id=order_id, customer_id=customer_id, total=total, status="placed")
        order.raise_(
            OrderPlaced(order_id=order.id, customer_id=customer_id, total=total)
        )
        return order

    def cancel(self) -> None:
        """Cancel the order. This is the compensating step for CancelOrder."""
        self.status = "cancelled"


@domain.aggregate
class Inventory:
    """Inventory aggregate holding a stock reservation for an order."""

    order_id: Identifier(required=True)
    status: String(default="reserved")

    @classmethod
    def reserve(cls, order_id: str) -> "Inventory":
        """Reserve stock for an order and report it with StockReserved."""
        reservation = cls(order_id=order_id)
        reservation.raise_(
            StockReserved(order_id=order_id, reservation_id=reservation.id)
        )
        return reservation

    def release(self) -> None:
        """Release the reservation. The compensating step for CancelReservation."""
        self.status = "released"


@domain.aggregate
class Payment:
    """Payment aggregate representing a financial transaction."""

    order_id: Identifier(required=True)
    amount: Float(required=True)
    status: String(default="pending")

    @classmethod
    def charge(cls, order_id: str, amount: float) -> "Payment":
        """Charge the order, and report the outcome as an event.

        This is the saga's branch point: the confirmed path goes on to shipping,
        the failed path compensates.
        """
        payment = cls(order_id=order_id, amount=amount)
        if amount > PAYMENT_LIMIT:
            payment.status = "failed"
            payment.raise_(
                PaymentFailed(order_id=order_id, reason="amount over the limit")
            )
        else:
            payment.status = "confirmed"
            payment.raise_(PaymentConfirmed(order_id=order_id, payment_id=payment.id))
        return payment


@domain.aggregate
class Shipping:
    """Shipping aggregate representing a shipment."""

    order_id: Identifier(required=True)
    status: String(default="dispatched")

    @classmethod
    def dispatch(cls, order_id: str) -> "Shipping":
        """Dispatch the shipment. ShipmentDispatched ends the saga."""
        shipment = cls(order_id=order_id)
        shipment.raise_(ShipmentDispatched(order_id=order_id, tracking_id=shipment.id))
        return shipment


# --- Command handlers (each does the work the saga asks for) ---


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    """Handle the commands that drive Order: the one that starts the flow, and
    the one the saga issues to compensate."""

    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder) -> None:
        order = Order.place(command.order_id, command.customer_id, command.total)
        current_domain.repository_for(Order).add(order)

    @handle(CancelOrder)
    def cancel_order(self, command: CancelOrder) -> None:
        repository = current_domain.repository_for(Order)
        order = repository.get(command.order_id)
        order.cancel()
        repository.add(order)


@domain.command_handler(part_of=Inventory)
class InventoryCommandHandler:
    """Handle the commands the saga issues to Inventory."""

    @handle(CreateReservation)
    def create_reservation(self, command: CreateReservation) -> None:
        reservation = Inventory.reserve(command.order_id)
        current_domain.repository_for(Inventory).add(reservation)

    @handle(CancelReservation)
    def cancel_reservation(self, command: CancelReservation) -> None:
        repository = current_domain.repository_for(Inventory)
        reservation = repository.get(command.reservation_id)
        reservation.release()
        repository.add(reservation)


@domain.command_handler(part_of=Payment)
class PaymentCommandHandler:
    """Handle the commands the saga issues to Payment."""

    @handle(RequestPayment)
    def request_payment(self, command: RequestPayment) -> None:
        payment = Payment.charge(command.order_id, command.amount)
        current_domain.repository_for(Payment).add(payment)


@domain.command_handler(part_of=Shipping)
class ShippingCommandHandler:
    """Handle the commands the saga issues to Shipping."""

    @handle(CreateShipment)
    def create_shipment(self, command: CreateShipment) -> None:
        shipment = Shipping.dispatch(command.order_id)
        current_domain.repository_for(Shipping).add(shipment)


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
    """Coordinate order fulfillment across the Order, Inventory, Payment, and
    Shipping aggregates.

    Each handler advances the saga's state and issues the command for the next
    step. Terminal handlers close the saga:

    - on_shipment_dispatched (end=True): the success terminal.
    - on_payment_failed (end=True): the failure terminal, which also issues the
      compensating commands to release the stock reservation and cancel the
      order.
    """

    order_id: Identifier()
    reservation_id: Identifier()
    total: Float()
    status: String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        """Start the saga and reserve stock."""
        self.order_id = event.order_id
        self.total = event.total
        self.status = "reserving_stock"
        current_domain.process(CreateReservation(order_id=event.order_id))

    @handle(StockReserved, correlate="order_id")
    def on_stock_reserved(self, event: StockReserved) -> None:
        """Request payment once stock is reserved."""
        # Remember the reservation: the failure path needs it to compensate.
        self.reservation_id = event.reservation_id
        self.status = "awaiting_payment"
        current_domain.process(
            RequestPayment(order_id=self.order_id, amount=self.total)
        )

    @handle(PaymentConfirmed, correlate="order_id")
    def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
        """Dispatch the shipment once payment is confirmed."""
        self.status = "shipping"
        current_domain.process(CreateShipment(order_id=self.order_id))

    @handle(ShipmentDispatched, correlate="order_id", end=True)
    def on_shipment_dispatched(self, event: ShipmentDispatched) -> None:
        """Close the saga on the success path."""
        self.status = "fulfilled"

    @handle(PaymentFailed, correlate="order_id", end=True)
    def on_payment_failed(self, event: PaymentFailed) -> None:
        """Close the saga on the failure path and compensate earlier steps."""
        self.status = "cancelled"
        current_domain.process(CancelReservation(reservation_id=self.reservation_id))
        current_domain.process(CancelOrder(order_id=self.order_id))
