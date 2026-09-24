"""
Multiple subscribers each consuming from different external streams.

This example demonstrates:
- Multiple subscribers registered with the same domain
- Each subscriber listening to a different external stream
- Separate concerns: payment handling vs shipping tracking
- Explicit broker parameter (defaults to "default")
- Each subscriber independently processes its own stream

Usage:
    domain.brokers["default"].publish(
        "payment_gateway", {"order_id": str(order.id), "status": "SUCCESS"}
    )
    domain.brokers["default"].publish(
        "shipping_updates", {"order_id": str(order.id), "tracking_number": "TRK-123"}
    )
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
    """Order aggregate with status transitions from multiple external sources."""

    customer_email: String(max_length=255, required=True)
    total_amount: Float(required=True)
    status: String(
        choices=["PENDING", "PAID", "SHIPPED", "CANCELLED"], default="PENDING"
    )
    tracking_number: String()

    def mark_paid(self):
        """Mark the order as paid after payment confirmation."""
        self.status = "PAID"

    def mark_shipped(self, tracking_number: str):
        """Mark the order as shipped with a tracking number."""
        self.status = "SHIPPED"
        self.tracking_number = tracking_number


@domain.subscriber(stream="payment_gateway")
class PaymentWebhookSubscriber:
    """Processes payment webhook notifications from an external gateway.

    Listens to the 'payment_gateway' broker stream. Uses the default
    broker since no explicit broker parameter is provided.
    """

    def __call__(self, payload: dict) -> None:
        """Process payment confirmation."""
        order_id = payload["order_id"]
        status = payload["status"]

        if status == "SUCCESS":
            repo = domain.repository_for(Order)
            order = repo.get(order_id)
            order.mark_paid()
            repo.add(order)

            logger.info("Order %s marked as paid", order_id)


@domain.subscriber(stream="shipping_updates", broker="default")
class ShippingUpdateSubscriber:
    """Processes shipping status updates from an external logistics provider.

    Listens to the 'shipping_updates' broker stream. Explicitly specifies
    broker='default' (which is the default anyway) to demonstrate the option.
    """

    def __call__(self, payload: dict) -> None:
        """Process shipping update from logistics provider."""
        order_id = payload["order_id"]
        tracking_number = payload.get("tracking_number", "")

        repo = domain.repository_for(Order)
        order = repo.get(order_id)
        order.mark_shipped(tracking_number)
        repo.add(order)

        logger.info(
            "Order %s marked as shipped (tracking: %s)", order_id, tracking_number
        )


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create an order
        order = Order(customer_email="alice@example.com", total_amount=149.99)
        domain.repository_for(Order).add(order)
        print(f"Order created: {order.id} (status: {order.status})")

        # Simulate payment confirmation
        domain.brokers["default"].publish(
            "payment_gateway",
            {"order_id": str(order.id), "status": "SUCCESS"},
        )
        updated = domain.repository_for(Order).get(order.id)
        print(f"After payment: status={updated.status}")

        # Simulate shipping update
        domain.brokers["default"].publish(
            "shipping_updates",
            {"order_id": str(order.id), "tracking_number": "TRK-12345"},
        )
        updated = domain.repository_for(Order).get(order.id)
        print(
            f"After shipping: status={updated.status}, tracking={updated.tracking_number}"
        )
