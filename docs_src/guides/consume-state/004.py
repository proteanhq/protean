import logging

from protean import Domain
from typing import Annotated
from pydantic import Field

logger = logging.getLogger(__name__)

domain = Domain()
domain.config["message_processing"] = "sync"


@domain.aggregate
class Order:
    customer_email: Annotated[str, Field(max_length=255)]
    total_amount: float
    status: str = Field(
        default="PENDING",
        json_schema_extra={"choices": ["PENDING", "PAID", "SHIPPED", "CANCELLED"]},
    )

    def mark_paid(self):
        self.status = "PAID"


@domain.subscriber(stream="payment_gateway")  # (1)
class PaymentWebhookSubscriber:
    """Processes payment webhook notifications from an external gateway.

    This subscriber listens to the `payment_gateway` broker stream and updates
    order status when payments are confirmed.
    """

    def __call__(self, payload: dict) -> None:  # (2)
        order_id = payload["order_id"]
        status = payload["status"]

        if status == "SUCCESS":
            repo = domain.repository_for(Order)
            order = repo.get(order_id)
            order.mark_paid()
            repo.add(order)

            logger.info(f"Order {order_id} marked as paid")

    @classmethod
    def handle_error(cls, exc: Exception, message: dict) -> None:  # (3)
        """Handle processing errors gracefully."""
        order_id = message.get("order_id", "unknown")
        logger.error(f"Failed to process payment for order {order_id}: {exc}")


@domain.subscriber(stream="shipping_updates", broker="default")  # (4)
class ShippingUpdateSubscriber:
    """Processes shipping status updates from an external logistics provider."""

    def __call__(self, payload: dict) -> None:
        order_id = payload["order_id"]

        repo = domain.repository_for(Order)
        order = repo.get(order_id)
        order.status = "SHIPPED"
        repo.add(order)

        logger.info(f"Order {order_id} marked as shipped")


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

        # Simulate external shipping provider sending an update
        domain.brokers["default"].publish(
            "shipping_updates",
            {"order_id": str(order.id), "tracking_number": "TRACK-12345"},
        )

        # Verify order is now shipped
        updated = domain.repository_for(Order).get(order.id)
        print(f"After shipping webhook: status={updated.status}")
        assert updated.status == "SHIPPED"

        print("\nAll webhooks processed successfully!")
