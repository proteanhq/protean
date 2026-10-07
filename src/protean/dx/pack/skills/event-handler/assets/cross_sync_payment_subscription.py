"""
Cross-aggregate sync: Payment → Subscription activation.

This example demonstrates:
- Payment aggregate raises PaymentConfirmed event
- Factory method on source aggregate raises event during creation, called
  from Payment's command handler
- Event handler sits in Payment's own cluster (part_of=Payment), the cluster
  that owns the event
- The handler hands off to Subscription by issuing an ActivateSubscription
  command
- Subscription's command handler finds the subscription by customer_id from
  the command and activates it
- A redelivered event is a no-op: the command carries the payment id, and
  Subscription records the payment ids it has already applied

Domain: When a payment is confirmed, the customer's subscription
is activated. Payment and Subscription are separate aggregates.

Processing is synchronous, so confirming a payment runs the whole hop
in-process, with no broker and no server.

Usage:
    domain.init(traverse=False)
    with domain.domain_context():
        domain.repository_for(Subscription).add(
            Subscription(customer_id="CUST-1", plan_name="basic")
        )
        domain.process(
            ConfirmPayment(customer_id="CUST-1", amount=20.0, plan_name="pro")
        )
        # The subscription is now active on the "pro" plan.
"""

from protean import Domain, current_domain, handle
from protean.fields import Float, Identifier, List, String

domain = Domain(__name__)

# Run the hop in-process: PaymentConfirmed reaches the event handler when the
# unit of work that saves the payment commits, and ActivateSubscription reaches
# its handler as soon as it is issued.
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --- Commands ---


@domain.command(part_of="Payment")
class ConfirmPayment:
    """Confirm a customer's payment for a plan."""

    customer_id: Identifier(required=True)
    amount: Float(required=True)
    plan_name: String(required=True)


@domain.command(part_of="Subscription")
class ActivateSubscription:
    """Activate a customer's subscription for one confirmed payment.

    `payment_id` comes from the event, so a redelivered event reissues the same
    command and the handler can tell it has already applied it.
    """

    payment_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    plan_name: String(required=True)


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
    """Subscription aggregate (target of sync).

    `applied_payment_ids` records which payments have already activated this
    subscription. Without it, a repeat delivery of a payment already applied
    could switch the subscription back to that payment's plan. The guard does
    not order payments: the first delivery of an older payment that arrives
    late still applies its plan.
    """

    customer_id: Identifier(required=True)
    plan_name: String(required=True)
    status: String(default="inactive")
    applied_payment_ids: List(content_type=String)

    def activate(self, payment_id, plan_name):
        """Activate the subscription with the given plan for one payment."""
        self.plan_name = plan_name
        self.status = "active"
        self.applied_payment_ids = [*self.applied_payment_ids, payment_id]


# --- Command handlers (the write path for each aggregate) ---


@domain.command_handler(part_of=Payment)
class PaymentCommandHandler:
    """The write path for Payment."""

    @handle(ConfirmPayment)
    def confirm_payment(self, command: ConfirmPayment):
        payment = Payment.confirm(
            command.customer_id, command.amount, command.plan_name
        )
        current_domain.repository_for(Payment).add(payment)


@domain.command_handler(part_of=Subscription)
class SubscriptionCommandHandler:
    """The write path for Subscription."""

    @handle(ActivateSubscription)
    def activate_subscription(self, command: ActivateSubscription):
        repo = current_domain.repository_for(Subscription)
        subscription = repo.find_by(customer_id=command.customer_id)
        if command.payment_id in subscription.applied_payment_ids:
            # Already applied. A redelivered PaymentConfirmed reissues
            # ActivateSubscription for a payment this subscription has seen.
            return
        subscription.activate(command.payment_id, command.plan_name)
        repo.add(subscription)


# --- The cross-aggregate link: an event handler in Payment's cluster ---


@domain.event_handler(part_of=Payment)
class SubscriptionSyncHandler:
    """React to Payment's own PaymentConfirmed event and activate the subscription.

    The handler sits in Payment's cluster because PaymentConfirmed belongs to
    Payment (a handler that reacts to another cluster's event is what `check`
    reports as EVENT_HANDLER_FOREIGN_EVENT). It hands off to Subscription with
    a command, and Subscription's command handler does the write.
    """

    @handle(PaymentConfirmed)
    def on_payment_confirmed(self, event: PaymentConfirmed):
        """Ask Subscription to activate for the confirmed payment."""
        current_domain.process(
            ActivateSubscription(
                payment_id=event.payment_id,
                customer_id=event.customer_id,
                plan_name=event.plan_name,
            )
        )
