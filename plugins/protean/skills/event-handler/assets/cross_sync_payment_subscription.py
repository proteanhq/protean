"""
Cross-aggregate sync: Payment → Subscription activation.

This example demonstrates:
- Payment aggregate raises PaymentConfirmed event
- Subscription aggregate is activated in response
- Event handler bridges Payment and Subscription aggregates
- The subscription finds its record by customer_id from the event
- Factory method on source aggregate raises event during creation

Domain: When a payment is confirmed, the customer's subscription
is activated. Payment and Subscription are separate aggregates.
"""

from protean import Domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(__name__)
domain.config["event_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Payment")
class PaymentConfirmed:
    """Raised when a payment is successfully confirmed."""

    payment_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    amount: Float(required=True)
    plan_name: String(required=True)


# --- Source Aggregate: Payment ---


@domain.aggregate
class Payment:
    """Payment aggregate (source of events)."""

    customer_id: Identifier(required=True)
    amount: Float(required=True)
    plan_name: String(required=True)
    status: String(default="pending")

    @classmethod
    def confirm(cls, customer_id, amount, plan_name):
        """Create a confirmed payment."""
        payment = cls(
            customer_id=customer_id,
            amount=amount,
            plan_name=plan_name,
            status="confirmed",
        )
        payment.raise_(
            PaymentConfirmed(
                payment_id=payment.id,
                customer_id=customer_id,
                amount=amount,
                plan_name=plan_name,
            )
        )
        return payment


# --- Target Aggregate: Subscription ---


@domain.aggregate
class Subscription:
    """Subscription aggregate (target of sync)."""

    customer_id: Identifier(required=True)
    plan_name: String(required=True)
    status: String(default="inactive")

    def activate(self, plan_name):
        """Activate the subscription with the given plan."""
        self.plan_name = plan_name
        self.status = "active"


# --- Cross-Aggregate Event Handler ---


@domain.event_handler(
    part_of=Subscription,
    stream_category=Payment.meta_.stream_category,
)
class SubscriptionSyncHandler:
    """Activates Subscription when Payment is confirmed.

    Belongs to Subscription but listens to Payment's event stream.
    """

    @handle(PaymentConfirmed)
    def on_payment_confirmed(self, event: PaymentConfirmed):
        """Activate subscription when payment is confirmed."""
        repo = domain.repository_for(Subscription)
        subscription = repo._dao.find_by(customer_id=event.customer_id)
        subscription.activate(plan_name=event.plan_name)
        repo.add(subscription)
