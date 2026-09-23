"""
Process manager with dictionary correlation mapping.

This example demonstrates:
- Dictionary-style correlate parameter: correlate={"pm_field": "event_field"}
- When event field names differ from PM field names
- How the framework extracts the event field value and maps it to the PM field
- A payment reconciliation scenario with external payment references
- Two handlers using consistent dict correlation

Domain: Payment reconciliation for external billing system
    - ExternalPaymentReceived (start) -> status: received
    - ReconciliationCompleted (end) -> status: reconciled

Usage:
    from pm_dict_correlation import PaymentReconciliationPM, domain

    domain.init(traverse=False)
    with domain.domain_context():
        pm = PaymentReconciliationPM(order_id="ORD-001", status="pending")
"""

from protean import Domain, handle
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain(__file__, "billing")


# --- Events ---


@domain.event(part_of="Invoice")
class ExternalPaymentReceived:
    """Event from external payment provider with different field naming.

    The external system uses 'ext_order_ref' instead of 'order_id'.
    Dictionary correlation maps between these different field names.
    """

    ext_order_ref: Identifier(required=True)
    amount: Float(required=True)


@domain.event(part_of="Invoice")
class ReconciliationCompleted:
    """Event raised when reconciliation is confirmed by the external system."""

    ext_order_ref: Identifier(required=True)


# --- Aggregate ---


@domain.aggregate
class Invoice:
    """Invoice aggregate representing an external billing record."""

    ext_order_ref: Identifier(required=True)
    amount: Float(required=True)


# --- Process Manager ---


@domain.process_manager(stream_categories=["billing::invoice"])
class PaymentReconciliationPM:
    """Reconciles external payments using dictionary correlation.

    The external system uses 'ext_order_ref' but our PM tracks 'order_id'.
    Dictionary correlation maps between these different field names:
        correlate={"order_id": "ext_order_ref"}
    means: extract event.ext_order_ref and use it to find/create PM by order_id.
    """

    order_id: Identifier()
    amount: Float()
    status: String(default="pending")

    @handle(
        ExternalPaymentReceived,
        start=True,
        correlate={"order_id": "ext_order_ref"},
    )
    def on_payment_received(self, event: ExternalPaymentReceived) -> None:
        """Start reconciliation when an external payment arrives."""
        self.order_id = event.ext_order_ref
        self.amount = event.amount
        self.status = "received"

    @handle(
        ReconciliationCompleted,
        correlate={"order_id": "ext_order_ref"},
        end=True,
    )
    def on_reconciliation_completed(self, event: ReconciliationCompleted) -> None:
        """Complete reconciliation (auto-completes PM via end=True)."""
        self.status = "reconciled"
