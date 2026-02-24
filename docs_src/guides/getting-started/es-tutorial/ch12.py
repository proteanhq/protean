# --8<-- [start:full]
"""Chapter 12: Snapshots

Demonstrates how snapshots optimize event-sourced aggregate loading.
Instead of replaying every event from the beginning of time, Protean
can periodically capture a snapshot of the aggregate's state.  Subsequent
loads replay only the events *after* the snapshot.

Snapshots are mostly a configuration and operational concern — the domain
code itself stays unchanged.
"""

from protean import Domain, apply, handle, invariant
from protean.exceptions import ValidationError
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


# --8<-- [end:command_handler]
# --8<-- [start:configuration]
# Snapshot threshold is configured in domain.toml or pyproject.toml:
#
#   [tool.protean]
#   snapshot_threshold = 10
#
# This means a snapshot is automatically considered after every 10 events.
# You can also trigger snapshots programmatically or via the CLI:
#
#   CLI:
#     protean snapshot --domain path.to.domain --aggregate Account
#
#   Programmatic:
#     domain.create_snapshot(Account, account_id)     # Single aggregate
#     domain.create_snapshots(Account)                 # All instances
#     domain.create_all_snapshots()                    # All aggregates
# --8<-- [end:configuration]
domain.init(traverse=False)
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"

# Set a low snapshot threshold for demonstration
domain.config["snapshot_threshold"] = 5


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Open an account
        account_id = domain.process(
            OpenAccount(
                account_number="ACC-001",
                holder_name="Alice Johnson",
                opening_deposit=1000.00,
            )
        )
        print(f"Account opened: {account_id}")

        # Make several deposits to build up event history
        for i in range(1, 8):
            domain.process(
                MakeDeposit(
                    account_id=account_id,
                    amount=100.00,
                    reference=f"deposit-{i}",
                )
            )
        print("Made 7 deposits of $100 each")

        # At this point, 8 events exist (1 open + 7 deposits).
        # With snapshot_threshold=5, a snapshot can be created.

        # Create a snapshot programmatically
        created = domain.create_snapshot(Account, account_id)
        print(f"\nSnapshot created: {created}")

        # Now when we load the account, Protean starts from the snapshot
        # and only replays events written after the snapshot position —
        # much faster than replaying all 8 events from scratch.
        repo = current_domain.repository_for(Account)
        account = repo.get(account_id)
        print(f"\nAccount holder: {account.holder_name}")
        print(f"Balance: ${account.balance:.2f}")
        print(f"Version: {account._version}")

        assert account.balance == 1700.00  # 1000 + (7 * 100)
        print("\nAll checks passed!")
# --8<-- [end:usage]
# --8<-- [end:full]
