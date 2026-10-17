from protean import Domain, handle
from protean.fields import DateTime, Float, Identifier, String
from protean.utils.globals import current_domain

domain = Domain(name="Ordering")
domain.config["command_processing"] = "sync"
domain.config["message_processing"] = "sync"


@domain.aggregate
class Order:
    order_id: Identifier(identifier=True)
    status: String(default="PENDING")
    payment_id: Identifier()
    amount: Float()
    currency: String()
    paid_at: DateTime()


@domain.command(part_of=Order)
class MarkOrderPaid:
    order_id: Identifier(required=True)
    payment_id: Identifier(required=True)
    amount: Float(required=True)
    currency: String(required=True)
    paid_at: DateTime(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(MarkOrderPaid)
    def mark_paid(self, command: MarkOrderPaid):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.status = "PAID"
        order.payment_id = command.payment_id
        order.amount = command.amount
        order.currency = command.currency
        order.paid_at = command.paid_at
        repo.add(order)


# --8<-- [start:subscriber]
@domain.subscriber(stream="payments")
class PaymentEventsSubscriber:
    def __call__(self, payload: dict) -> None:
        event_type = payload.get("type")

        if event_type == "PaymentConfirmed":
            current_domain.process(
                MarkOrderPaid(
                    order_id=payload["reference_id"],  # External field name
                    payment_id=payload["transaction_id"],  # Different naming
                    amount=payload["amount"],
                    currency=payload["currency_code"],  # Different naming
                    paid_at=payload["confirmed_at"],  # Different naming
                )
            )


# --8<-- [end:subscriber]
