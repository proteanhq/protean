from protean import Domain

domain = Domain(name="CommandHandlerPayments")

# --8<-- [start:order_handler]
from datetime import UTC, datetime

from protean import current_domain, handle
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.exceptions import ValidationError
from protean.fields import Auto, DateTime, Float, Identifier, String

# --- Domain elements ---


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    status: String(default="draft")
    total: Float(default=0.0)
    payment_id: String()
    paid_at: DateTime()

    def confirm_payment(self, payment_id: str, amount: float) -> None:
        """Confirm that payment has been received."""
        if self.status != "pending_payment":
            raise ValidationError(
                {"status": ["Only orders pending payment can be confirmed"]}
            )

        if amount < self.total:
            raise ValidationError(
                {"amount": ["Payment amount is less than order total"]}
            )

        self.status = "paid"
        self.payment_id = payment_id
        self.paid_at = datetime.now(UTC)

        self.raise_(
            OrderPaid(
                order_id=self.order_id,
                customer_id=self.customer_id,
                payment_id=payment_id,
                amount=amount,
            )
        )


@domain.command(part_of=Order)
class ConfirmPayment(BaseCommand):
    order_id: Identifier(required=True)
    payment_id: String(required=True)
    amount: Float(required=True)


@domain.event(part_of=Order)
class OrderPaid(BaseEvent):
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    payment_id: String(required=True)
    amount: Float(required=True)


# --- Command Handler ---


@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):
    @handle(ConfirmPayment)
    def confirm_payment(self, command: ConfirmPayment):
        """Process the payment confirmation.

        This handler is invoked by the Protean engine when it reads
        the ConfirmPayment command from the event store. The engine
        wraps the handler in a UoW automatically.
        """
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.confirm_payment(command.payment_id, command.amount)
        repo.add(order)


# --8<-- [end:order_handler]

# --8<-- [start:per_call]
domain.init(traverse=False)

with domain.domain_context():
    order = Order(customer_id="cust-789", status="pending_payment", total=99.99)
    domain.repository_for(Order).add(order)

    # Force synchronous processing for this specific call
    result = domain.process(
        ConfirmPayment(order_id=order.order_id, payment_id="pay-456", amount=99.99),
        asynchronous=False,
    )
# --8<-- [end:per_call]
