from protean import Domain, handle
from protean.fields import Float, Identifier

domain = Domain(name="Payments")
domain.config["command_processing"] = "sync"
domain.config["message_processing"] = "sync"

# --8<-- [start:webhook]
from protean.utils.eventing import Message
from protean.utils.globals import current_domain


@domain.subscriber(stream="payment-webhooks")
class PaymentWebhookSubscriber:
    def __call__(self, payload: dict) -> None:
        message = Message.from_cloudevent(payload)

        if message.metadata.headers.type == "com.stripe.payment.succeeded":
            current_domain.process(
                ConfirmPayment(
                    payment_id=message.data["payment_intent_id"],
                    amount=message.data["amount"],
                )
            )


# --8<-- [end:webhook]


@domain.aggregate
class Payment:
    payment_id: Identifier(identifier=True)
    amount: Float(required=True)


@domain.command(part_of=Payment)
class ConfirmPayment:
    payment_id: Identifier(required=True)
    amount: Float(required=True)


@domain.command_handler(part_of=Payment)
class PaymentCommandHandler:
    @handle(ConfirmPayment)
    def confirm(self, command: ConfirmPayment):
        current_domain.repository_for(Payment).add(Payment(**command.payload))
