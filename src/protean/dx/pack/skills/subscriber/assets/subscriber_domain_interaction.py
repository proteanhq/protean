"""
Subscriber that loads and updates aggregates through repositories.

This example demonstrates:
- Subscriber processing external messages and updating domain aggregates
- Using domain.repository_for() to load and persist aggregate state
- Conditional logic based on external message payload
- Subscriber as a bridge between external systems and domain operations

Usage:
    domain.brokers["default"].publish(
        "payment_gateway",
        {"order_id": str(order.id), "status": "SUCCESS", "transaction_id": "txn-42"},
    )
    # PaymentWebhookSubscriber processes the message and updates Order status
"""

import logging

from protean import Domain
from protean.fields import Float, String

# Domain setup
domain = Domain()
domain.config["message_processing"] = "sync"

logger = logging.getLogger(__name__)


@domain.aggregate
class Order:
    """Order aggregate with payment-related status transitions."""

    customer_email: String(max_length=255, required=True)
    total_amount: Float(required=True)
    status: String(
        choices=["PENDING", "PAID", "SHIPPED", "CANCELLED"], default="PENDING"
    )

    def mark_paid(self):
        """Mark the order as paid."""
        if self.status != "PENDING":
            raise ValueError(f"Cannot mark order as paid in '{self.status}' status")
        self.status = "PAID"


@domain.subscriber(stream="payment_gateway")
class PaymentWebhookSubscriber:
    """Processes payment webhook notifications from an external gateway.

    Listens to the 'payment_gateway' broker stream. When a payment
    confirmation arrives with status 'SUCCESS', it loads the Order
    aggregate and transitions it to PAID status.

    This demonstrates the domain interaction pattern: the subscriber
    serves as the bridge between an external system (payment gateway)
    and domain aggregate operations.
    """

    def __call__(self, payload: dict) -> None:
        """Process payment webhook from external gateway.

        Args:
            payload: Raw dict from broker, e.g.
                {"order_id": "...", "status": "SUCCESS", "transaction_id": "txn-42"}
        """
        order_id = payload["order_id"]
        status = payload["status"]

        if status == "SUCCESS":
            repo = domain.repository_for(Order)
            order = repo.get(order_id)
            order.mark_paid()
            repo.add(order)

            logger.info("Order %s marked as paid", order_id)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create an order
        order = Order(customer_email="alice@example.com", total_amount=149.99)
        domain.repository_for(Order).add(order)
        print(f"Order created: {order.id} (status: {order.status})")

        # Simulate external payment gateway confirming payment
        domain.brokers["default"].publish(
            "payment_gateway",
            {
                "order_id": str(order.id),
                "status": "SUCCESS",
                "transaction_id": "txn-42",
            },
        )

        # Verify order is now paid
        updated = domain.repository_for(Order).get(order.id)
        print(f"After payment webhook: status={updated.status}")
        assert updated.status == "PAID"
        print("Order payment confirmed successfully!")
