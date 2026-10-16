from protean import Domain
from protean.fields import Auto, Float, Identifier, List, String

domain = Domain(name="CustomerViews")


@domain.aggregate
class Customer:
    customer_id: Auto(identifier=True)
    name: String(required=True)
    email: String(required=True)


@domain.event(part_of=Customer)
class CustomerRegistered:
    customer_id: Identifier(required=True)
    name: String(required=True)
    email: String(required=True)


@domain.aggregate
class BillingAccount:
    account_id: Auto(identifier=True)
    customer_id: Identifier(required=True)


# --8<-- [start:dashboard]
from protean.core.projector import on
from protean.utils.globals import current_domain


@domain.event(part_of=BillingAccount)
class InvoiceIssued:
    invoice_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    amount: Float(required=True)


@domain.projection
class CustomerDashboard:
    """Read model combining data from Customer and BillingAccount."""

    customer_id: Identifier(identifier=True)
    name: String()
    email: String()
    account_status: String()
    total_invoiced: Float(default=0.0)
    invoice_ids: List(content_type=String)


@domain.projector(
    projector_for=CustomerDashboard,
    stream_categories=[
        Customer.meta_.stream_category,  # "<domain>::customer"
        BillingAccount.meta_.stream_category,  # "<domain>::billing_account"
    ],
)
class CustomerDashboardProjector:
    # Events can arrive more than once, so each handler skips a repeat
    @on(CustomerRegistered)
    def on_customer_registered(self, event: CustomerRegistered):
        repo = current_domain.repository_for(CustomerDashboard)
        if repo.query.filter(customer_id=event.customer_id).all().items:
            return

        dashboard = CustomerDashboard(
            customer_id=event.customer_id,
            name=event.name,
            email=event.email,
        )
        repo.add(dashboard)

    @on(InvoiceIssued)
    def on_invoice_issued(self, event: InvoiceIssued):
        repo = current_domain.repository_for(CustomerDashboard)
        dashboard = repo.get(event.customer_id)
        if event.invoice_id in dashboard.invoice_ids:
            return

        dashboard.total_invoiced += event.amount
        dashboard.invoice_ids = [*dashboard.invoice_ids, event.invoice_id]
        repo.add(dashboard)


# --8<-- [end:dashboard]
