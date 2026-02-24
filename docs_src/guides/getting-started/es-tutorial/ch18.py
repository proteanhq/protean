"""Chapter 18: Monitoring Health

Demonstrates the domain setup for health monitoring with the Observatory
dashboard and Prometheus metrics.  Protean provides CLI commands to inspect
subscription lag, handler throughput, and system health:

    protean observatory --domain fidelis.domain
    protean server --domain fidelis.domain --prometheus-port 9090

This chapter is primarily about operational tooling and CLI workflows; the
Python source only needs to set up the domain so the tools can operate on it.
"""

from protean import Domain, apply, handle, invariant
from protean.core.projector import on
from protean.exceptions import ValidationError
from protean.fields import DateTime, Float, Identifier, Integer, String
from protean.utils.globals import current_domain

# --8<-- [start:domain_setup]
domain = Domain("fidelis")


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


@domain.event_handler(part_of=Account)
class ComplianceAlertHandler:
    @handle(DepositMade)
    def on_large_deposit(self, event: DepositMade):
        if event.amount >= 10000:
            print(
                f"  [COMPLIANCE] Large deposit alert: "
                f"${event.amount:.2f} into account {event.account_id}"
            )


@domain.projection
class AccountSummary:
    account_id: Identifier(identifier=True, required=True)
    account_number: String(max_length=20, required=True)
    holder_name: String(max_length=100, required=True)
    balance: Float(default=0.0)
    transaction_count: Integer(default=0)
    last_transaction_at: DateTime()


@domain.projector(projector_for=AccountSummary, aggregates=[Account])
class AccountSummaryProjector:
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


# --8<-- [end:domain_setup]
