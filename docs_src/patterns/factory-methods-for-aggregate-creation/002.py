from protean import Domain, current_domain
from protean.fields import DateTime, Integer, String, ValueObject

domain = Domain(name="FactoryMethodsPayments")

# Deliver broker messages to the subscriber as soon as they are published
domain.config["message_processing"] = "sync"


@domain.value_object
class Money:
    cents: Integer(required=True)
    currency: String(max_length=3, required=True)


@domain.aggregate
class Payment:
    external_id: String(required=True)
    amount = ValueObject(Money)
    status: String(default="pending")
    customer_email: String()
    paid_at: DateTime()


# --8<-- [start:factory]
# domain/payment/factories.py
from datetime import UTC, datetime
from typing import ClassVar


class PaymentFactory:
    """Anti-corruption layer for external payment system data."""

    STRIPE_STATUS_MAP: ClassVar[dict[str, str]] = {
        "succeeded": "completed",
        "requires_payment_method": "failed",
        "canceled": "cancelled",
    }

    @classmethod
    def from_stripe_webhook(cls, payload: dict) -> "Payment":
        """Translate a Stripe webhook payload into a Payment aggregate."""
        data = payload["data"]["object"]
        return Payment(
            external_id=data["id"],
            amount=Money(
                cents=data["amount"],
                currency=data["currency"].upper(),
            ),
            status=cls.STRIPE_STATUS_MAP.get(data["status"], "pending"),
            customer_email=data.get("receipt_email", ""),
            paid_at=datetime.fromtimestamp(data["created"], tz=UTC),
        )


# The subscriber stays thin
@domain.subscriber(stream="stripe-webhooks")
class StripeWebhookSubscriber:
    def __call__(self, payload: dict) -> None:
        if payload["type"] == "payment_intent.succeeded":
            payment = PaymentFactory.from_stripe_webhook(payload)
            current_domain.repository_for(Payment).add(payment)


# --8<-- [end:factory]
