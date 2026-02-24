# --8<-- [start:full]
from protean import Domain, apply, handle, invariant
from protean.core.projector import on
from protean.exceptions import ValidationError
from protean.fields import DateTime, Float, Identifier, Integer, String
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
        account.deposit(command.amount, reference=command.reference)
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
# --8<-- [start:projection]
@domain.projection
class AccountSummary:
    """A read-optimized view of account data for the dashboard."""

    account_id: Identifier(identifier=True, required=True)
    account_number: String(max_length=20, required=True)
    holder_name: String(max_length=100, required=True)
    balance: Float(default=0.0)
    transaction_count: Integer(default=0)
    last_transaction_at: DateTime()


# --8<-- [end:projection]
# --8<-- [start:projector]
@domain.projector(projector_for=AccountSummary, aggregates=[Account])
class AccountSummaryProjector:
    """Maintains the AccountSummary projection from Account events."""

    @on(AccountOpened)
    def on_account_opened(self, event: AccountOpened):
        self.id = event.account_id
        summary = AccountSummary(
            account_id=event.account_id,
            account_number=event.account_number,
            holder_name=event.holder_name,
            balance=event.opening_deposit,
            transaction_count=1,
            last_transaction_at=event._metadata.headers.time,
        )
        current_domain.repository_for(AccountSummary).add(summary)

    @on(DepositMade)
    def on_deposit_made(self, event: DepositMade):
        repo = current_domain.repository_for(AccountSummary)
        summary = repo.get(event.account_id)
        summary.balance += event.amount
        summary.transaction_count += 1
        summary.last_transaction_at = event._metadata.headers.time
        repo.add(summary)

    @on(WithdrawalMade)
    def on_withdrawal_made(self, event: WithdrawalMade):
        repo = current_domain.repository_for(AccountSummary)
        summary = repo.get(event.account_id)
        summary.balance -= event.amount
        summary.transaction_count += 1
        summary.last_transaction_at = event._metadata.headers.time
        repo.add(summary)


# --8<-- [end:projector]
domain.init(traverse=False)
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Open an account with $1000
        account_id = domain.process(
            OpenAccount(
                account_number="ACC-001",
                holder_name="Alice Johnson",
                opening_deposit=1000.00,
            )
        )
        print(f"Account opened: {account_id}")

        # Make a deposit
        domain.process(
            MakeDeposit(
                account_id=account_id,
                amount=500.00,
                reference="paycheck",
            )
        )
        print("Deposit of $500.00 made")

        # Check the projection
        summary_repo = current_domain.repository_for(AccountSummary)
        summary = summary_repo.get(account_id)
        print("\n=== Account Dashboard ===")
        print(f"Account: {summary.account_number}")
        print(f"Holder: {summary.holder_name}")
        print(f"Balance: ${summary.balance:.2f}")
        print(f"Transactions: {summary.transaction_count}")
        print(f"Last activity: {summary.last_transaction_at}")

        assert summary.balance == 1500.00
        assert summary.transaction_count == 2
        print("\nAll checks passed!")
# --8<-- [end:usage]
# --8<-- [end:full]
