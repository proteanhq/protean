from protean import Domain
from protean.fields import Auto, Float, Identifier, String

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


@domain.projector(
    projector_for=CustomerDashboard,
    stream_categories=[
        Customer.meta_.stream_category,  # "<domain>::customer"
        BillingAccount.meta_.stream_category,  # "<domain>::billing_account"
    ],
)
class CustomerDashboardProjector:
    @on(CustomerRegistered)
    def on_customer_registered(self, event: CustomerRegistered):
        dashboard = CustomerDashboard(
            customer_id=event.customer_id,
            name=event.name,
            email=event.email,
        )
        current_domain.repository_for(CustomerDashboard).add(dashboard)

    @on(InvoiceIssued)
    def on_invoice_issued(self, event: InvoiceIssued):
        repo = current_domain.repository_for(CustomerDashboard)
        dashboard = repo.get(event.customer_id)
        dashboard.total_invoiced += event.amount
        repo.add(dashboard)


# --8<-- [end:dashboard]
