"""
Application service with multiple @use_case methods.

This example demonstrates:
- Multiple use case methods on a single application service
- Each method represents a distinct business operation
- Loading aggregates from repository for mutations
- Separate use cases for create vs. update operations
- All methods share the same aggregate association

Usage:
    svc = AccountApplicationServices()
    account_id = svc.create_account(email="user@example.com", name="User")
    svc.activate_account(account_id=account_id)
    svc.change_email(account_id=account_id, new_email="new@example.com")
    svc.deactivate_account(account_id=account_id)
"""

from protean import Domain, current_domain, use_case
from protean.fields import Identifier, String

# Domain setup
domain = Domain()


@domain.aggregate
class Account:
    """Account aggregate with multiple state transitions."""

    email: String(required=True)
    name: String(required=True)
    status: String(choices=["PENDING", "ACTIVE", "SUSPENDED"], default="PENDING")

    def activate(self):
        """Activate the account."""
        self.status = "ACTIVE"

    def deactivate(self):
        """Suspend the account."""
        self.status = "SUSPENDED"

    def change_email(self, new_email: str):
        """Update the account email."""
        self.email = new_email


@domain.application_service(part_of=Account)
class AccountApplicationServices:
    """Application service with multiple use cases for the Account aggregate.

    Each method is a separate use case with its own UnitOfWork context.
    Methods are named after business operations, not technical actions.
    """

    @use_case
    def create_account(self, email: str, name: str) -> Identifier:
        """Create a new account and return its ID."""
        account = Account(email=email, name=name)
        current_domain.repository_for(Account).add(account)
        return account.id

    @use_case
    def activate_account(self, account_id: Identifier) -> None:
        """Activate an existing account."""
        account = current_domain.repository_for(Account).get(account_id)
        account.activate()
        current_domain.repository_for(Account).add(account)

    @use_case
    def deactivate_account(self, account_id: Identifier) -> None:
        """Suspend an existing account."""
        account = current_domain.repository_for(Account).get(account_id)
        account.deactivate()
        current_domain.repository_for(Account).add(account)

    @use_case
    def change_email(self, account_id: Identifier, new_email: str) -> None:
        """Change the email address for an account."""
        account = current_domain.repository_for(Account).get(account_id)
        account.change_email(new_email)
        current_domain.repository_for(Account).add(account)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        svc = AccountApplicationServices()

        # Create
        account_id = svc.create_account(email="alice@example.com", name="Alice")
        print(f"Created account: {account_id}")

        # Activate
        svc.activate_account(account_id=account_id)
        account = current_domain.repository_for(Account).get(account_id)
        print(f"Account status: {account.status}")

        # Change email
        svc.change_email(account_id=account_id, new_email="alice.new@example.com")
        account = current_domain.repository_for(Account).get(account_id)
        print(f"Account email: {account.email}")

        # Deactivate
        svc.deactivate_account(account_id=account_id)
        account = current_domain.repository_for(Account).get(account_id)
        print(f"Account status: {account.status}")
