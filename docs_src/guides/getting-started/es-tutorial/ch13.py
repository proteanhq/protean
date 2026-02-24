# --8<-- [start:full]
"""Chapter 13: Temporal Queries

Demonstrates how to load an event-sourced aggregate at a specific point
in time or at a specific version.  Temporal aggregates are read-only —
they represent a historical snapshot and cannot raise new events.
"""

from datetime import datetime, timezone

from protean import Domain, apply, handle, invariant
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain

domain = Domain("fidelis")


# --8<-- [start:events]
@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)
    account_number: String(required=True)
    holder_name: String(required=True)
    opening_deposit: Float(required=True)


@domain.event(part_of="Account")
class DepositMade:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


@domain.event(part_of="Account")
class WithdrawalMade:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


@domain.event(part_of="Account")
class AccountClosed:
    account_id: Identifier(required=True)
    reason: String()


# --8<-- [end:events]
# --8<-- [start:aggregate]
@domain.aggregate(is_event_sourced=True)
class Account:
    account_number: String(max_length=20, required=True)
    holder_name: String(max_length=100, required=True)
    balance: Float(default=0.0)
    status: String(max_length=20, default="ACTIVE")

    @invariant.post
    def balance_must_not_be_negative(self):
        if self.balance is not None and self.balance < 0:
            raise ValidationError(
                {"balance": ["Insufficient funds: balance cannot be negative"]}
            )

    @invariant.post
    def closed_account_must_have_zero_balance(self):
        if self.status == "CLOSED" and self.balance != 0:
            raise ValidationError(
                {"status": ["Cannot close account with non-zero balance"]}
            )

    @classmethod
    def open(cls, account_number: str, holder_name: str, opening_deposit: float):
        account = cls._create_new()
        account.raise_(
            AccountOpened(
                account_id=str(account.id),
                account_number=account_number,
                holder_name=holder_name,
                opening_deposit=opening_deposit,
            )
        )
        return account

    def deposit(self, amount: float, reference: str = None) -> None:
        if amount <= 0:
            raise ValidationError({"amount": ["Deposit amount must be positive"]})
        self.raise_(
            DepositMade(
                account_id=str(self.id),
                amount=amount,
                reference=reference,
            )
        )

    def withdraw(self, amount: float, reference: str = None) -> None:
        if amount <= 0:
            raise ValidationError({"amount": ["Withdrawal amount must be positive"]})
        self.raise_(
            WithdrawalMade(
                account_id=str(self.id),
                amount=amount,
                reference=reference,
            )
        )

    def close(self, reason: str = None) -> None:
        self.raise_(
            AccountClosed(
                account_id=str(self.id),
                reason=reason,
            )
        )

    @apply
    def on_account_opened(self, event: AccountOpened):
        self.id = event.account_id
        self.account_number = event.account_number
        self.holder_name = event.holder_name
        self.balance = event.opening_deposit
        self.status = "ACTIVE"

    @apply
    def on_deposit_made(self, event: DepositMade):
        self.balance += event.amount

    @apply
    def on_withdrawal_made(self, event: WithdrawalMade):
        self.balance -= event.amount

    @apply
    def on_account_closed(self, event: AccountClosed):
        self.status = "CLOSED"


# --8<-- [end:aggregate]
# --8<-- [start:commands]
@domain.command(part_of=Account)
class OpenAccount:
    account_number: String(required=True)
    holder_name: String(required=True)
    opening_deposit: Float(required=True)


@domain.command(part_of=Account)
class MakeDeposit:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


@domain.command(part_of=Account)
class MakeWithdrawal:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


# --8<-- [end:commands]
# --8<-- [start:command_handler]
@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(OpenAccount)
    def handle_open_account(self, command: OpenAccount):
        account = Account.open(
            account_number=command.account_number,
            holder_name=command.holder_name,
            opening_deposit=command.opening_deposit,
        )
        current_domain.repository_for(Account).add(account)
        return str(account.id)

    @handle(MakeDeposit)
    def handle_make_deposit(self, command: MakeDeposit):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.deposit(command.amount, reference=command.reference)
        repo.add(account)

    @handle(MakeWithdrawal)
    def handle_make_withdrawal(self, command: MakeWithdrawal):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.withdraw(command.amount, reference=command.reference)
        repo.add(account)


# --8<-- [end:command_handler]
domain.init(traverse=False)
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --8<-- [start:temporal_usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Build up a transaction history
        # Event 0: AccountOpened  -> balance $1000
        account_id = domain.process(
            OpenAccount(
                account_number="ACC-001",
                holder_name="Alice Johnson",
                opening_deposit=1000.00,
            )
        )
        print(f"Account opened: {account_id}")

        # Event 1: DepositMade   -> balance $1500
        domain.process(
            MakeDeposit(account_id=account_id, amount=500.00, reference="paycheck")
        )

        # Event 2: DepositMade   -> balance $1700
        domain.process(
            MakeDeposit(account_id=account_id, amount=200.00, reference="refund")
        )

        # Capture a timestamp between events for as_of queries
        midpoint = datetime.now(timezone.utc)

        # Event 3: WithdrawalMade -> balance $1200
        domain.process(
            MakeWithdrawal(account_id=account_id, amount=500.00, reference="rent")
        )

        # Event 4: DepositMade    -> balance $1500
        domain.process(
            MakeDeposit(account_id=account_id, amount=300.00, reference="freelance")
        )

        repo = current_domain.repository_for(Account)

        # --- Current state ---
        current = repo.get(account_id)
        print(f"\nCurrent balance: ${current.balance:.2f} (version {current._version})")
        assert current.balance == 1500.00

        # --- Temporal query: at_version ---
        # at_version=2 replays events 0, 1, and 2 (the first 3 events)
        historical = repo.get(account_id, at_version=2)
        print(
            f"Balance at version 2: ${historical.balance:.2f} "
            f"(version {historical._version})"
        )
        assert historical.balance == 1700.00  # 1000 + 500 + 200

        # --- Temporal query: as_of ---
        # Load the aggregate as it was at the midpoint timestamp
        snapshot_in_time = repo.get(account_id, as_of=midpoint)
        print(
            f"Balance at midpoint: ${snapshot_in_time.balance:.2f} "
            f"(version {snapshot_in_time._version})"
        )
        assert snapshot_in_time.balance == 1700.00  # Before rent withdrawal

        # --- Temporal aggregates are read-only ---
        try:
            historical.raise_(
                DepositMade(
                    account_id=str(historical.id),
                    amount=100.00,
                    reference="should-fail",
                )
            )
        except IncorrectUsageError as e:
            print(f"\nRead-only guard: {e.args[0]}")

        print("\nAll checks passed!")
# --8<-- [end:temporal_usage]
# --8<-- [end:full]
