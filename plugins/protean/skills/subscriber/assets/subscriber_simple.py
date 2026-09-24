"""
Basic subscriber listening to a single external stream.

This example demonstrates:
- Subscriber definition with @domain.subscriber decorator
- Required stream parameter specifying the external broker stream
- Implementing __call__(self, payload: dict) to process raw dict payloads
- Synchronous message processing via domain.config["message_processing"] = "sync"
- Subscribers receive raw dicts (NOT typed domain events)

Usage:
    domain.brokers["default"].publish(
        "payment_gateway",
        {"order_id": "ORD-001", "transaction_id": "txn-789"},
    )
    # PaymentConfirmationSubscriber.__call__ is invoked with the dict
"""

from protean import Domain
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()
domain.config["message_processing"] = "sync"


@domain.aggregate
class Payment:
    """Payment aggregate tracking order payments."""

    order_id: Identifier(required=True)
    amount: Float(required=True)
    status: String(choices=["PENDING", "CONFIRMED", "FAILED"], default="PENDING")

    def confirm(self):
        """Confirm the payment."""
        self.status = "CONFIRMED"


@domain.subscriber(stream="payment_gateway")
class PaymentConfirmationSubscriber:
    """Consumes payment confirmation messages from an external payment gateway.

    Listens on the 'payment_gateway' broker stream. When a message arrives,
    it looks up the Payment aggregate by order_id and confirms it.

    This is the simplest subscriber pattern: one stream, one action.
    """

    def __call__(self, payload: dict) -> None:
        """Process payment confirmation from external gateway.

        Args:
            payload: Raw dict from broker, e.g.
                {"order_id": "ORD-001", "transaction_id": "txn-789"}
        """
        order_id = payload["order_id"]

        repo = domain.repository_for(Payment)
        payment = repo._dao.find_by(order_id=order_id)
        payment.confirm()
        repo.add(payment)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create a pending payment
        payment = Payment(order_id="order-123", amount=49.99)
        domain.repository_for(Payment).add(payment)

        # Simulate external payment gateway publishing a confirmation
        domain.brokers["default"].publish(
            "payment_gateway",
            {"order_id": "order-123", "transaction_id": "txn-789"},
        )

        # Verify payment was confirmed by the subscriber
        updated = domain.repository_for(Payment).get(payment.id)
        print(f"Payment status: {updated.status}")
        assert updated.status == "CONFIRMED"
        print("Payment confirmed successfully!")
