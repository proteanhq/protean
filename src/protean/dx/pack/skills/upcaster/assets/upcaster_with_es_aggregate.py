"""
Event upcasters with event-sourced aggregate reconstruction.

This example demonstrates:
- Event-sourced aggregate with @apply handlers that only handle current schema
- Upcasters that transform old events before they reach @apply
- Clean separation: upcasters handle schema migration, @apply handles state
- Factory classmethod and business methods raising current-version events

Domain: Bank account
    - AccountOpened event evolved from v1 to v2 (added currency field)
    - FundsDeposited event unchanged at v1
    - @apply handlers always see current schema thanks to upcasting

Usage:
    from upcaster_with_es_aggregate import domain, BankAccount

    domain.init(traverse=False)
    with domain.domain_context():
        account = BankAccount.open(
            account_id="ACCT-1", owner="Alice", initial_balance=100.0, currency="USD"
        )
        account.deposit(50.0)
"""

from protean import Domain
from protean.core.aggregate import apply
from protean.core.upcaster import BaseUpcaster
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()


# --- Events (current versions) ---


@domain.event(part_of="BankAccount")
class AccountOpened:
    """Account was opened. Current version: v2.

    Evolution history:
        v1: account_id, owner, initial_balance
        v2: account_id, owner, initial_balance, currency (added)
    """

    __version__ = 2

    account_id = Identifier(required=True)
    owner = String(required=True, max_length=150)
    initial_balance = Float(required=True)
    currency = String(required=True)


@domain.event(part_of="BankAccount")
class FundsDeposited:
    """Funds were deposited into the account. Unchanged since v1."""

    account_id = Identifier(required=True)
    amount = Float(required=True)


@domain.event(part_of="BankAccount")
class FundsWithdrawn:
    """Funds were withdrawn from the account. Unchanged since v1."""

    account_id = Identifier(required=True)
    amount = Float(required=True)


# --- Upcaster ---


@domain.upcaster(event_type=AccountOpened, from_version=1, to_version=2)
class UpcastAccountOpenedV1ToV2(BaseUpcaster):
    """v1 -> v2: Add currency field.

    All accounts opened before v2 were denominated in USD.
    """

    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data


# --- Aggregate ---


@domain.aggregate(is_event_sourced=True)
class BankAccount:
    """Event-sourced bank account aggregate.

    The @apply handlers only deal with the CURRENT event schema.
    Old events (e.g., v1 AccountOpened without currency) are automatically
    transformed by upcasters before reaching @apply.
    """

    account_id = Identifier(identifier=True)
    owner = String(required=True, max_length=150)
    balance = Float(default=0.0)
    currency = String(default="USD")

    @classmethod
    def open(cls, account_id, owner, initial_balance=0.0, currency="USD"):
        """Factory: open a new bank account."""
        account = cls(
            account_id=account_id,
            owner=owner,
            balance=initial_balance,
            currency=currency,
        )
        account.raise_(
            AccountOpened(
                account_id=account_id,
                owner=owner,
                initial_balance=initial_balance,
                currency=currency,
            )
        )
        return account

    def deposit(self, amount):
        """Deposit funds into the account."""
        if amount <= 0:
            raise ValueError("Deposit amount must be positive")
        self.raise_(FundsDeposited(account_id=self.account_id, amount=amount))

    def withdraw(self, amount):
        """Withdraw funds from the account."""
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive")
        if amount > self.balance:
            raise ValueError("Insufficient funds")
        self.raise_(FundsWithdrawn(account_id=self.account_id, amount=amount))

    # --- @apply handlers (current schema only) ---

    @apply
    def on_opened(self, event: AccountOpened):
        self.account_id = event.account_id
        self.owner = event.owner
        self.balance = event.initial_balance
        self.currency = event.currency  # Always present: v1 events are upcast

    @apply
    def on_deposited(self, event: FundsDeposited):
        self.balance += event.amount

    @apply
    def on_withdrawn(self, event: FundsWithdrawn):
        self.balance -= event.amount


# Example usage
if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)

    with domain.domain_context():
        # Create account with current schema
        account = BankAccount.open(
            account_id="ACCT-1",
            owner="Alice",
            initial_balance=1000.0,
            currency="EUR",
        )
        print(
            f"Opened: {account.owner}, balance={account.balance}, currency={account.currency}"
        )

        # Deposit and withdraw
        account.deposit(250.0)
        print(f"After deposit: balance={account.balance}")

        account.withdraw(100.0)
        print(f"After withdrawal: balance={account.balance}")

        # Reconstruct from events
        reconstructed = BankAccount.from_events(account._events)
        print(
            f"\nReconstructed: balance={reconstructed.balance}, currency={reconstructed.currency}"
        )

        # The upcaster ensures old v1 events (without currency) get
        # currency="USD" added before reaching the @apply handler.
        # This means @apply handlers never need to handle missing fields.
