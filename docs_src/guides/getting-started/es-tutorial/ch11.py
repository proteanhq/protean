# --8<-- [start:full]
"""Chapter 11: Event Upcasting

Demonstrates how to evolve event schemas over time using upcasters.
When a stored event's version no longer matches the current event class,
an upcaster transforms the old payload into the new shape during replay.
"""

from protean import Domain, apply, handle, invariant
from protean.core.upcaster import BaseUpcaster
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


# --8<-- [start:deposit_made_v2]
@domain.event(part_of="Account")
class DepositMade:
    """v2 adds a source_type field to track how the deposit originated."""

    __version__ = 2

    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()
    source_type: String(default="unknown")
    # --8<-- [end:deposit_made_v2]


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

    def deposit(
        self, amount: float, reference: str = None, source_type: str = "manual"
    ) -> None:
        if amount <= 0:
            raise ValidationError({"amount": ["Deposit amount must be positive"]})
        self.raise_(
            DepositMade(
                account_id=str(self.id),
                amount=amount,
                reference=reference,
                source_type=source_type,
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
# --8<-- [start:upcaster]
@domain.upcaster(event_type=DepositMade, from_version=1, to_version=2)
class UpcastDepositV1ToV2(BaseUpcaster):
    """Transform v1 DepositMade events to v2 by adding source_type.

    Old v1 events stored in the event store lack the source_type field.
    This upcaster ensures they are transparently upgraded when replayed,
    defaulting source_type to "unknown" since the original source is lost.
    """

    def upcast(self, data: dict) -> dict:
        data["source_type"] = "unknown"
        return data


# --8<-- [end:upcaster]
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
    source_type: String(default="manual")


@domain.command(part_of=Account)
class MakeWithdrawal:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


@domain.command(part_of=Account)
class CloseAccount:
    account_id: Identifier(required=True)
    reason: String()


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
        account.deposit(
            command.amount,
            reference=command.reference,
            source_type=command.source_type,
        )
        repo.add(account)

    @handle(MakeWithdrawal)
    def handle_make_withdrawal(self, command: MakeWithdrawal):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.withdraw(command.amount, reference=command.reference)
        repo.add(account)

    @handle(CloseAccount)
    def handle_close_account(self, command: CloseAccount):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.close(reason=command.reason)
        repo.add(account)


# --8<-- [end:command_handler]
domain.init(traverse=False)
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"
# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Open an account and make deposits with the new v2 schema
        account_id = domain.process(
            OpenAccount(
                account_number="ACC-001",
                holder_name="Alice Johnson",
                opening_deposit=1000.00,
            )
        )
        print(f"Account opened: {account_id}")

        # This deposit is written with v2 schema (includes source_type)
        domain.process(
            MakeDeposit(
                account_id=account_id,
                amount=500.00,
                reference="paycheck",
                source_type="payroll",
            )
        )
        print("Deposit of $500.00 made (source_type=payroll)")

        # In a real system, older deposits already in the store would have
        # been written as v1 (without source_type). When those events are
        # replayed, the UpcastDepositV1ToV2 upcaster automatically adds
        # source_type="unknown" so the v2 DepositMade class can deserialize
        # them without error.

        # Make another deposit with a different source
        domain.process(
            MakeDeposit(
                account_id=account_id,
                amount=250.00,
                reference="wire-transfer",
                source_type="bank_transfer",
            )
        )
        print("Deposit of $250.00 made (source_type=bank_transfer)")

        # Reload the account — replays all events from the store
        repo = current_domain.repository_for(Account)
        account = repo.get(account_id)
        print(f"\nAccount holder: {account.holder_name}")
        print(f"Balance: ${account.balance:.2f}")
        print(f"Version: {account._version}")

        # Verify the upcaster is registered
        assert UpcastDepositV1ToV2.meta_.event_type == DepositMade
        assert UpcastDepositV1ToV2.meta_.from_version == 1
        assert UpcastDepositV1ToV2.meta_.to_version == 2

        assert account.balance == 1750.00  # 1000 + 500 + 250
        print("\nAll checks passed!")
# --8<-- [end:usage]
# --8<-- [end:full]
