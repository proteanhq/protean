"""
Command handler with multiple @handle methods for the same aggregate.

This example demonstrates:
- A single command handler class handling multiple commands
- Each command has its own @handle method
- All commands must be associated with the SAME aggregate as the handler
- Different handler methods for different operations on the same aggregate
- Loading an existing aggregate from the repository (hydration)
- Creating vs. loading aggregates in different handler methods

Usage:
    register_cmd = RegisterAccount(
        account_id="ACC-001",
        email="alice@example.com",
        name="Alice Smith",
    )
    domain.process(register_cmd, asynchronous=False)

    activate_cmd = ActivateAccount(account_id="ACC-001")
    domain.process(activate_cmd, asynchronous=False)
"""

from protean import Domain, handle
from protean.fields import Identifier, String

# Domain setup
domain = Domain()


@domain.aggregate
class Account:
    """Account aggregate with multiple state transitions."""

    account_id: Identifier(identifier=True)
    email: String(required=True)
    name: String(required=True)
    status: String(default="pending")
    suspended_reason: String()

    def activate(self):
        """Activate a pending account."""
        if self.status != "pending":
            raise ValueError(f"Cannot activate account in '{self.status}' status")
        self.status = "active"

    def suspend(self, reason: str):
        """Suspend an active account."""
        if self.status != "active":
            raise ValueError(f"Cannot suspend account in '{self.status}' status")
        self.status = "suspended"
        self.suspended_reason = reason


@domain.command(part_of="Account")
class RegisterAccount:
    """Command to register a new account."""

    account_id: Identifier(required=True)
    email: String(required=True)
    name: String(required=True)


@domain.command(part_of="Account")
class ActivateAccount:
    """Command to activate a pending account."""

    account_id: Identifier(required=True)


@domain.command(part_of="Account")
class SuspendAccount:
    """Command to suspend an active account."""

    account_id: Identifier(required=True)
    reason: String(required=True)


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    """Handler that processes all account-related commands.

    A single command handler class can handle multiple commands,
    each with its own @handle method. All commands must be
    associated with the same aggregate (Account).
    """

    @handle(RegisterAccount)
    def handle_register(self, command: RegisterAccount):
        """Handle RegisterAccount by creating a new Account aggregate."""
        account = Account(
            account_id=command.account_id,
            email=command.email,
            name=command.name,
        )
        domain.repository_for(Account).add(account)
        return account.account_id

    @handle(ActivateAccount)
    def handle_activate(self, command: ActivateAccount):
        """Handle ActivateAccount by loading and activating an existing account."""
        account = domain.repository_for(Account).get(command.account_id)
        account.activate()
        domain.repository_for(Account).add(account)

    @handle(SuspendAccount)
    def handle_suspend(self, command: SuspendAccount):
        """Handle SuspendAccount by loading and suspending an existing account."""
        account = domain.repository_for(Account).get(command.account_id)
        account.suspend(reason=command.reason)
        domain.repository_for(Account).add(account)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Step 1: Register a new account
        register_cmd = RegisterAccount(
            account_id="ACC-001",
            email="alice@example.com",
            name="Alice Smith",
        )
        result = domain.process(register_cmd, asynchronous=False)
        print(f"Registered account: {result}")

        # Step 2: Activate the account
        activate_cmd = ActivateAccount(account_id="ACC-001")
        domain.process(activate_cmd, asynchronous=False)
        print("Account activated")

        # Step 3: Suspend the account
        suspend_cmd = SuspendAccount(
            account_id="ACC-001",
            reason="Suspicious activity detected",
        )
        domain.process(suspend_cmd, asynchronous=False)
        print("Account suspended")
