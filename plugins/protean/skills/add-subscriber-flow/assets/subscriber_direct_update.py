"""
Subscriber flow with direct aggregate update (simple pattern).

This example demonstrates:
- Subscriber consuming payment webhook messages
- Direct aggregate update without command dispatch
- Conditional handling based on payload status
- Simple translation from external format to aggregate method call

Domain: An order system where a payment gateway sends webhook
notifications about payment status. The subscriber updates the
Order aggregate's payment status directly.
"""

import logging

from protean import Domain
from protean.fields import Float, String

domain = Domain(__name__)
domain.config["message_processing"] = "sync"

logger = logging.getLogger(__name__)


# --- Aggregate ---


@domain.aggregate
class Order:
    """Order aggregate with payment status tracking."""

    customer_email: String(required=True, max_length=200)
    total_amount: Float(required=True)
    status: String(default="pending")
    payment_ref: String(max_length=100)

    def confirm_payment(self, payment_ref):
        """Confirm payment for this order."""
        self.status = "paid"
        self.payment_ref = payment_ref

    def fail_payment(self, reason):
        """Mark payment as failed."""
        self.status = "payment_failed"


# --- Subscriber ---


@domain.subscriber(stream="payment_webhooks")
class PaymentWebhookSubscriber:
    """Processes payment webhook notifications.

    Listens to 'payment_webhooks' broker stream from external
    payment gateway. Translates webhook status into aggregate
    method calls.

    External format:
        {
            "orderId": "ORD-001",
            "paymentStatus": "COMPLETED",
            "transactionRef": "txn-abc-123"
        }
    """

    def __call__(self, payload: dict) -> None:
        """Process payment webhook."""
        order_id = payload["orderId"]
        status = payload["paymentStatus"]

        if status == "COMPLETED":
            self._handle_completed(order_id, payload.get("transactionRef", ""))
        elif status == "FAILED":
            self._handle_failed(order_id, payload.get("failureReason", "Unknown"))
        else:
            logger.info("Ignoring payment status: %s for order %s", status, order_id)

    def _handle_completed(self, order_id: str, transaction_ref: str) -> None:
        """Handle successful payment."""
        repo = domain.repository_for(Order)
        order = repo.get(order_id)
        order.confirm_payment(payment_ref=transaction_ref)
        repo.add(order)

    def _handle_failed(self, order_id: str, reason: str) -> None:
        """Handle failed payment."""
        repo = domain.repository_for(Order)
        order = repo.get(order_id)
        order.fail_payment(reason=reason)
        repo.add(order)
