"""
Repository with explicit Unit of Work usage.

This example demonstrates:
- Command handlers automatically wrap repository operations in a UnitOfWork
- Explicit UnitOfWork usage outside handlers (e.g., in scripts, tests, migrations)
- Transactional semantics: all changes commit together or rollback together
- Multiple repository operations within a single UnitOfWork
- UnitOfWork as context manager

Usage:
    # Inside command handlers, UoW is implicit — no manual wrapping needed
    # Outside handlers, use explicit UoW:
    with UnitOfWork():
        repo = domain.repository_for(Account)
        account = Account(...)
        repo.add(account)
    # Changes are committed when exiting the context manager
"""

from protean import Domain, handle
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()


@domain.aggregate
class Account:
    """Bank account aggregate."""

    account_id: Identifier(identifier=True)
    holder_name: String(required=True)
    balance: Float(default=0.0)
    status: String(default="active")

    def deposit(self, amount: float):
        """Deposit money into the account."""
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        self.balance += amount

    def withdraw(self, amount: float):
        """Withdraw money from the account."""
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if amount > self.balance:
            raise ValueError("Insufficient funds")
        self.balance -= amount

    def close(self):
        """Close the account."""
        if self.balance != 0:
            raise ValueError("Account must have zero balance to close")
        self.status = "closed"


@domain.command(part_of="Account")
class OpenAccount:
    """Command to open a new account."""

    account_id: Identifier(required=True)
    holder_name: String(required=True)
    initial_deposit: Float(default=0.0)


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    """Handler that uses the implicit UnitOfWork.

    Command handlers are automatically wrapped in a UnitOfWork.
    No manual UoW management is needed inside handler methods.
    """

    @handle(OpenAccount)
    def handle_open_account(self, command: OpenAccount):
        """Open a new account with optional initial deposit.

        The implicit UoW ensures both the account creation and
        the deposit (if any) are committed atomically.
        """
        account = Account(
            account_id=command.account_id,
            holder_name=command.holder_name,
        )
        if command.initial_deposit > 0:
            account.deposit(command.initial_deposit)

        domain.repository_for(Account).add(account)
        return account.account_id


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # 1. Command handler with implicit UoW
        cmd = OpenAccount(
            account_id="ACC-001",
            holder_name="Alice",
            initial_deposit=1000.0,
        )
        result = domain.process(cmd, asynchronous=False)
        print(f"Account opened: {result}")

        # 2. Explicit UoW outside a handler (e.g., in a script)
        with UnitOfWork():
            repo = domain.repository_for(Account)
            account = repo.get("ACC-001")
            account.deposit(500.0)
            repo.add(account)
        # Changes are committed when exiting the `with` block

        # Verify the balance
        repo = domain.repository_for(Account)
        account = repo.get("ACC-001")
        print(f"Balance after deposit: {account.balance}")
