"""
Process manager that issues commands to drive other aggregates forward.

This example demonstrates:
- Issuing commands via current_domain.process() inside handler methods
- Importing current_domain from protean (the public API)
- Commands committed atomically within the same Unit of Work
- PM as coordinator: decides WHAT happens next, aggregates decide HOW
- Two command issuance patterns: from event data and from PM state

Domain: Order-to-payment coordination
    - OrderPlaced (start) -> issues RequestPayment command
    - PaymentFailed (end) -> issues CancelOrder command

Usage:
    from pm_command_issuance import OrderPaymentPM, domain

    domain.init(traverse=False)
    with domain.domain_context():
        pm = OrderPaymentPM(order_id="ORD-001", status="new")
"""

from protean import Domain, current_domain, handle
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain(__file__, "ecommerce")


# --- Commands ---


@domain.command(part_of="Payment")
class RequestPayment:
    """Command to request payment processing for an order."""

    order_id: Identifier(required=True)
    amount: Float(required=True)


@domain.command(part_of="Order")
class CancelOrder:
    """Command to cancel an order after payment failure."""

    order_id: Identifier(required=True)


# --- Events ---


@domain.event(part_of="Order")
class OrderPlaced:
    """Raised when a new order is placed."""

    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.event(part_of="Payment")
class PaymentFailed:
    """Raised when payment processing fails."""

    payment_id: Identifier(required=True)
    order_id: Identifier(required=True)
    reason: String(required=True)


# --- Aggregates ---


@domain.aggregate
class Order:
    """Order aggregate."""

    customer_id: Identifier(required=True)
    total: Float(required=True)


@domain.aggregate
class Payment:
    """Payment aggregate."""

    order_id: Identifier(required=True)
    amount: Float(required=True)


# --- Process Manager ---


@domain.process_manager(stream_categories=["ecommerce::order", "ecommerce::payment"])
class OrderPaymentPM:
    """Coordinates order-to-payment flow by issuing commands.

    This PM demonstrates the coordinator pattern:
    - It does NOT contain business logic
    - It decides WHAT should happen next (issue commands)
    - Target aggregates' command handlers decide HOW to execute

    Command issuance patterns:
    1. From event data: RequestPayment uses event.order_id and event.total
    2. From PM state: CancelOrder uses self.order_id (previously stored)
    """

    order_id: Identifier()
    status: String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        """Start payment flow and issue RequestPayment command."""
        self.order_id = event.order_id
        self.status = "awaiting_payment"
        current_domain.process(
            RequestPayment(order_id=event.order_id, amount=event.total)
        )

    @handle(PaymentFailed, correlate="order_id", end=True)
    def on_payment_failed(self, event: PaymentFailed) -> None:
        """Cancel the order when payment fails and issue CancelOrder command."""
        self.status = "cancelled"
        current_domain.process(CancelOrder(order_id=self.order_id))
