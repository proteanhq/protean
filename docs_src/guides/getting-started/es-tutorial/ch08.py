"""Chapter 8: Going Async -- The Server

This chapter is about configuration and running the Protean server
for asynchronous event processing. The Python file contains the full
domain setup, while the server is started via the CLI:

    protean server --domain fidelis.domain

The domain.toml configuration is shown below as a reference.
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


@domain.event(part_of="Account")
class AccountClosed:
    account_id: Identifier(required=True)
    reason: String()


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


@domain.event_handler(part_of=Account)
class ComplianceAlertHandler:
    @handle(DepositMade)
    def on_large_deposit(self, event: DepositMade):
        if event.amount >= 10000:
            print(
                f"  [COMPLIANCE] Large deposit alert: "
                f"${event.amount:.2f} into account {event.account_id}"
            )


@domain.event_handler(part_of=Account)
class NotificationHandler:
    @handle(AccountOpened)
    def on_account_opened(self, event: AccountOpened):
        self.id = event.account_id
        print(
            f"  [NOTIFICATION] Welcome, {event.holder_name}! "
            f"Your account {event.account_number} is now active."
        )

    @handle(WithdrawalMade)
    def on_large_withdrawal(self, event: WithdrawalMade):
        if event.amount >= 5000:
            print(
                f"  [NOTIFICATION] Large withdrawal alert: "
                f"${event.amount:.2f} from account {event.account_id}"
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


# --8<-- [start:configuration_example]
# ---------------------------------------------------------------
# domain.toml — place this file alongside your domain module
# ---------------------------------------------------------------
#
# [event_store]
# provider = "message_db"
# database_uri = "postgresql://message_store@localhost:5433/message_store"
#
# [broker]
# provider = "redis"
# redis_url = "redis://localhost:6379/0"
#
# [databases.default]
# provider = "postgresql"
# database_uri = "postgresql://postgres:postgres@localhost:5432/fidelis"
#
# [server]
# # Number of async workers for event/command processing
# workers = 4
#
# ---------------------------------------------------------------
# Start the server with:
#
#   protean server --domain fidelis.domain
#
# Start the observatory dashboard with:
#
#   protean observatory --domain fidelis.domain
#
# ---------------------------------------------------------------
# --8<-- [end:configuration_example]
