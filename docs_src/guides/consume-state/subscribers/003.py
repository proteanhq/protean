import logging

from protean import Domain, handle
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain

logger = logging.getLogger(__name__)

domain = Domain(name="Payments", config={"command_processing": "sync"})


@domain.aggregate
class Payment:
    order_id: Identifier(required=True)
    status: String(max_length=20, required=True)
    amount: Float(required=True)


@domain.command(part_of=Payment)
class RecordPayment:
    order_id: Identifier(required=True)
    status: String(max_length=20, required=True)
    amount: Float(required=True)


@domain.command_handler(part_of=Payment)
class PaymentCommandHandler:
    @handle(RecordPayment)
    def record(self, command: RecordPayment) -> None:
        current_domain.repository_for(Payment).add(
            Payment(
                order_id=command.order_id,
                status=command.status,
                amount=command.amount,
            )
        )


# --8<-- [start:subscriber]
@domain.subscriber(stream="payments")
class PaymentWebhookSubscriber:
    REQUIRED_FIELDS = ("order_id", "status", "amount")

    def __call__(self, payload: dict) -> None:
        # Validate required fields
        missing = [f for f in self.REQUIRED_FIELDS if f not in payload]
        if missing:
            logger.warning(f"Missing fields {missing}, skipping message")
            return

        # Validate types
        if not isinstance(payload["amount"], (int, float)):
            logger.warning(f"Invalid amount type: {type(payload['amount'])}")
            return

        # Safe to process
        current_domain.process(
            RecordPayment(
                order_id=payload["order_id"],
                status=payload["status"],
                amount=payload["amount"],
            )
        )


# --8<-- [end:subscriber]
