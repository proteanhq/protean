import logging

from protean import Domain
from protean.fields import Float, Identifier, String

logger = logging.getLogger(__name__)

domain = Domain()
domain.config["message_processing"] = "sync"


@domain.aggregate
class Payment:
    order_id = Identifier(required=True)
    amount = Float(required=True)
    status = String(choices=["PENDING", "CONFIRMED", "FAILED"], default="PENDING")

    def confirm(self):
        self.status = "CONFIRMED"


@domain.subscriber(stream="payment_gateway")  # (1)
class PaymentConfirmationSubscriber:
    """Consumes payment confirmation messages from an external payment gateway."""

    def __call__(self, payload: dict) -> None:  # (2)
        order_id = payload["order_id"]

        repo = domain.repository_for(Payment)
        payment = repo._dao.find_by(order_id=order_id)
        payment.confirm()  # (3)
        repo.add(payment)


domain.init(traverse=False)

if __name__ == "__main__":
    with domain.domain_context():
        # Create a pending payment
        payment = Payment(order_id="order-123", amount=49.99)
        domain.repository_for(Payment).add(payment)

        # Simulate an external payment gateway publishing a confirmation
        domain.brokers["default"].publish(
            "payment_gateway",
            {"order_id": "order-123", "transaction_id": "txn-789"},
        )

        # Verify payment was confirmed by the subscriber
        updated = domain.repository_for(Payment).get(payment.id)
        print(f"Payment status: {updated.status}")
        assert updated.status == "CONFIRMED"
        print("Payment confirmed successfully!")
