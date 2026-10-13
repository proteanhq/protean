from protean import Domain, handle
from protean.fields import Auto, Identifier, String
from protean.utils.globals import current_domain

domain = Domain(name="Customers")
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


@domain.event(part_of="Customer")
class CustomerRegistered:
    customer_id: Identifier(required=True)
    email: String(required=True)


@domain.event(part_of="Customer")
class CustomerDeactivated:
    customer_id: Identifier(required=True)


# --8<-- [start:same-domain]
@domain.aggregate
class Customer:
    """Authority for customer lifecycle."""

    customer_id: Auto(identifier=True)
    name: String(required=True)
    email: String(required=True)


@domain.aggregate
class BillingAccount:
    """Billing context's local model of a customer."""

    account_id: Auto(identifier=True)
    customer_id: Identifier(required=True)  # Correlation ID
    email: String(required=True)
    account_status: String(default="ACTIVE")

    def suspend(self):
        self.account_status = "SUSPENDED"


@domain.command(part_of=BillingAccount)
class OpenBillingAccount:
    customer_id: Identifier(required=True)
    email: String(required=True)


@domain.command(part_of=BillingAccount)
class SuspendBillingAccount:
    customer_id: Identifier(required=True)


@domain.event_handler(part_of=Customer)
class CustomerLifecycleHandler:
    """Turns Customer lifecycle events into BillingAccount commands."""

    @handle(CustomerRegistered)
    def on_customer_registered(self, event: CustomerRegistered):
        current_domain.process(
            OpenBillingAccount(customer_id=event.customer_id, email=event.email)
        )

    @handle(CustomerDeactivated)
    def on_customer_deactivated(self, event: CustomerDeactivated):
        current_domain.process(SuspendBillingAccount(customer_id=event.customer_id))


@domain.command_handler(part_of=BillingAccount)
class BillingAccountCommandHandler:
    @handle(OpenBillingAccount)
    def open_account(self, command: OpenBillingAccount):
        repo = current_domain.repository_for(BillingAccount)
        if repo.query.filter(customer_id=command.customer_id).all().total:
            return  # An account for this customer already exists

        repo.add(
            BillingAccount(
                customer_id=command.customer_id,  # Correlation
                email=command.email,
                account_status="ACTIVE",
            )
        )

    @handle(SuspendBillingAccount)
    def suspend_account(self, command: SuspendBillingAccount):
        repo = current_domain.repository_for(BillingAccount)
        account = repo.find_by(customer_id=command.customer_id)
        if account.account_status == "SUSPENDED":
            return  # Already suspended

        account.suspend()
        repo.add(account)


# --8<-- [end:same-domain]
