"""
Complete command flow with an event-sourced aggregate.

This example demonstrates:
- Full vertical slice: Command → CommandHandler → ES Aggregate → Event
- Command classes with imperative naming (DepositMoney, WithdrawMoney)
- Command handler loading aggregate via domain.repository_for() (auto-selects ES repo)
- Aggregate business methods that mutate state and raise events
- @apply methods for state reconstruction during event replay
- Invariant enforcement on ES aggregates
- Synchronous event processing configuration

Domain: Bank account with deposit/withdraw operations
    - Accounts are opened with an initial balance
    - Money can be deposited or withdrawn
    - Withdrawals are rejected if they exceed the balance

Usage:
    from es_aggregate_command_flow import Account, OpenAccount, domain

    domain.init(traverse=False)
    with domain.domain_context():
        domain.process(OpenAccount(account_id="ACC-001", owner_name="Alice", initial_deposit=500.0))  # noqa: E501
"""

from protean import Domain, handle, invariant
from protean.core.aggregate import apply
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain

# Domain setup
domain = Domain()
domain.config["command_processing"] = "sync"
domain.config["event_processing"] = "sync"


# --- Events ---


@domain.event(part_of="Account")
class AccountOpened:
    """Raised when a new account is opened."""

    account_id: Identifier(required=True)
    owner_name: String(required=True)
    balance: Float(required=True)


@domain.event(part_of="Account")
class MoneyDeposited:
    """Raised when money is deposited into an account."""

    account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.event(part_of="Account")
class MoneyWithdrawn:
    """Raised when money is withdrawn from an account."""

    account_id: Identifier(required=True)
    amount: Float(required=True)


# --- Commands ---


@domain.command(part_of="Account")
class OpenAccount:
    """Command to open a new bank account."""

    account_id: Identifier(required=True)
    owner_name: String(required=True, max_length=100)
    initial_deposit: Float(required=True)


@domain.command(part_of="Account")
class DepositMoney:
    """Command to deposit money into an account."""

    account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.command(part_of="Account")
class WithdrawMoney:
    """Command to withdraw money from an account."""

    account_id: Identifier(required=True)
    amount: Float(required=True)


# --- Aggregate ---


@domain.aggregate(event_sourced=True)
class Account:
    """Event-sourced bank account aggregate.

    Demonstrates the complete command flow pattern:
    Command → Handler → Aggregate method → raise_() → @apply mutates state
    """

    account_id: Identifier(identifier=True)
    owner_name: String(required=True, max_length=100)
    balance: Float(default=0.0)
    status: String(max_length=20, default="ACTIVE")

    # --- Invariant ---

    @invariant.post
    def balance_must_not_be_negative(self):
        """Account balance cannot go below zero."""
        if self.balance < 0:
            raise ValueError(f"Insufficient funds: balance would be {self.balance}")

    # --- Factory classmethod ---

    @classmethod
    def open(cls, account_id, owner_name, initial_deposit):
        """Open a new account with an initial deposit."""
        if initial_deposit <= 0:
            raise ValueError("Initial deposit must be positive")
        account = cls(
            account_id=account_id, owner_name=owner_name, balance=initial_deposit
        )
        account.raise_(
            AccountOpened(
                account_id=account_id,
                owner_name=owner_name,
                balance=initial_deposit,
            )
        )
        return account

    # --- Business methods (validate then raise; @apply handles state) ---

    def deposit(self, amount):
        """Deposit money into the account."""
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        self.raise_(MoneyDeposited(account_id=self.account_id, amount=amount))

    def withdraw(self, amount):
        """Withdraw money from the account."""
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if amount > self.balance:
            raise ValueError(
                f"Insufficient funds: balance={self.balance}, requested={amount}"
            )
        self.raise_(MoneyWithdrawn(account_id=self.account_id, amount=amount))

    # --- @apply methods (for replaying events during state reconstruction) ---

    @apply
    def account_opened(self, event: AccountOpened):
        self.account_id = event.account_id
        self.owner_name = event.owner_name
        self.balance = event.balance
        self.status = "ACTIVE"

    @apply
    def money_deposited(self, event: MoneyDeposited):
        self.balance += event.amount

    @apply
    def money_withdrawn(self, event: MoneyWithdrawn):
        self.balance -= event.amount


# --- Command Handler ---


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    """Handles account commands.

    Each @handle method:
    1. Loads or creates the aggregate
    2. Invokes the appropriate business method
    3. Persists via the repository (auto-selects ES repository)
    """

    @handle(OpenAccount)
    def handle_open_account(self, command: OpenAccount):
        account = Account.open(
            account_id=command.account_id,
            owner_name=command.owner_name,
            initial_deposit=command.initial_deposit,
        )
        current_domain.repository_for(Account).add(account)

    @handle(DepositMoney)
    def handle_deposit(self, command: DepositMoney):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.deposit(command.amount)
        repo.add(account)

    @handle(WithdrawMoney)
    def handle_withdraw(self, command: WithdrawMoney):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.withdraw(command.amount)
        repo.add(account)


# Example usage
if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)

    with domain.domain_context():
        # Open account via command
        domain.process(
            OpenAccount(
                account_id="ACC-001",
                owner_name="Alice Smith",
                initial_deposit=1000.00,
            )
        )

        # Deposit via command
        domain.process(DepositMoney(account_id="ACC-001", amount=250.00))

        # Withdraw via command
        domain.process(WithdrawMoney(account_id="ACC-001", amount=100.00))

        # Check final state
        repo = current_domain.repository_for(Account)
        account = repo.get("ACC-001")
        print(f"Account {account.account_id}")
        print(f"  Owner: {account.owner_name}")
        print(f"  Balance: ${account.balance:.2f}")
        print(f"  Version: {account._version}")
