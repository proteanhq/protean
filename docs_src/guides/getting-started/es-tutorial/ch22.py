# --8<-- [start:full]
"""Chapter 22: The Full Picture

Brings together every concept from the Fidelis ES tutorial into a single,
complete domain: event-sourced aggregates, fact events, projections,
projectors, command handlers, event handlers, process managers, and a
production-ready configuration.
"""

from protean import Domain, apply, handle, invariant
from protean.core.projector import on
from protean.exceptions import ValidationError
from protean.fields import DateTime, Float, Identifier, Integer, String
from protean.utils.globals import current_domain

# --8<-- [start:full_domain]
domain = Domain("fidelis")


# ---------------------------------------------------------------------------
# Account Aggregate
# ---------------------------------------------------------------------------
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


@domain.aggregate(is_event_sourced=True, fact_events=True)
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


# ---------------------------------------------------------------------------
# Transfer Aggregate
# ---------------------------------------------------------------------------
@domain.event(part_of="Transfer")
class TransferInitiated:
    transfer_id: Identifier(required=True)
    source_account_id: String(required=True)
    destination_account_id: String(required=True)
    amount: Float(required=True)


@domain.event(part_of="Transfer")
class TransferCompleted:
    transfer_id: Identifier(required=True)


@domain.event(part_of="Transfer")
class TransferFailed:
    transfer_id: Identifier(required=True)
    reason: String(required=True)


@domain.aggregate(is_event_sourced=True)
class Transfer:
    source_account_id: String(max_length=50, required=True)
    destination_account_id: String(max_length=50, required=True)
    amount: Float(required=True)
    status: String(max_length=20, default="INITIATED")

    @classmethod
    def initiate(
        cls,
        source_account_id: str,
        destination_account_id: str,
        amount: float,
    ):
        transfer = cls._create_new()
        transfer.raise_(
            TransferInitiated(
                transfer_id=str(transfer.id),
                source_account_id=source_account_id,
                destination_account_id=destination_account_id,
                amount=amount,
            )
        )
        return transfer

    def complete(self) -> None:
        self.raise_(TransferCompleted(transfer_id=str(self.id)))

    def fail(self, reason: str) -> None:
        self.raise_(TransferFailed(transfer_id=str(self.id), reason=reason))

    @apply
    def on_transfer_initiated(self, event: TransferInitiated):
        self.id = event.transfer_id
        self.source_account_id = event.source_account_id
        self.destination_account_id = event.destination_account_id
        self.amount = event.amount
        self.status = "INITIATED"

    @apply
    def on_transfer_completed(self, event: TransferCompleted):
        self.status = "COMPLETED"

    @apply
    def on_transfer_failed(self, event: TransferFailed):
        self.status = "FAILED"


@domain.command(part_of=Transfer)
class InitiateTransfer:
    source_account_id: String(required=True)
    destination_account_id: String(required=True)
    amount: Float(required=True)


@domain.command(part_of=Transfer)
class CompleteTransfer:
    transfer_id: Identifier(required=True)


@domain.command(part_of=Transfer)
class FailTransfer:
    transfer_id: Identifier(required=True)
    reason: String(required=True)


@domain.command_handler(part_of=Transfer)
class TransferCommandHandler:
    @handle(InitiateTransfer)
    def handle_initiate_transfer(self, command: InitiateTransfer):
        transfer = Transfer.initiate(
            source_account_id=command.source_account_id,
            destination_account_id=command.destination_account_id,
            amount=command.amount,
        )
        current_domain.repository_for(Transfer).add(transfer)
        return str(transfer.id)

    @handle(CompleteTransfer)
    def handle_complete_transfer(self, command: CompleteTransfer):
        repo = current_domain.repository_for(Transfer)
        transfer = repo.get(command.transfer_id)
        transfer.complete()
        repo.add(transfer)

    @handle(FailTransfer)
    def handle_fail_transfer(self, command: FailTransfer):
        repo = current_domain.repository_for(Transfer)
        transfer = repo.get(command.transfer_id)
        transfer.fail(reason=command.reason)
        repo.add(transfer)


# ---------------------------------------------------------------------------
# Event Handlers
# ---------------------------------------------------------------------------
@domain.event_handler(part_of=Account)
class ComplianceAlertHandler:
    @handle(DepositMade)
    def on_large_deposit(self, event: DepositMade):
        if event.amount >= 10000:
            print(
                f"  [COMPLIANCE] Large deposit alert: "
                f"${event.amount:.2f} into account {event.account_id}"
            )

    @handle(WithdrawalMade)
    def on_large_withdrawal(self, event: WithdrawalMade):
        if event.amount >= 5000:
            print(
                f"  [COMPLIANCE] Large withdrawal alert: "
                f"${event.amount:.2f} from account {event.account_id}"
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


# ---------------------------------------------------------------------------
# AccountSummary Projection (from domain events)
# ---------------------------------------------------------------------------
@domain.projection
class AccountSummary:
    """A read-optimized view of account data built from domain events."""

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


# ---------------------------------------------------------------------------
# AccountReport Projection (from fact events)
# ---------------------------------------------------------------------------
@domain.projection
class AccountReport:
    """A projection built from fact events -- always reflects the latest
    aggregate state without incremental calculations."""

    account_id: Identifier(identifier=True, required=True)
    account_number: String(max_length=20, required=True)
    holder_name: String(max_length=100, required=True)
    balance: Float(default=0.0)
    status: String(max_length=20, default="ACTIVE")
    last_updated: DateTime()


@domain.event_handler(
    part_of=Account,
    stream_category="fidelis::account-fact",
)
class AccountReportHandler:
    """Maintains the AccountReport projection from Account fact events.

    Fact events carry the complete aggregate state, so the handler
    either creates or fully replaces the projection record on every event.
    """

    @handle("Fidelis.AccountFactEvent.v1")
    def on_account_fact_event(self, event):
        repo = current_domain.repository_for(AccountReport)

        try:
            report = repo.get(event.id)
            report.account_number = event.account_number
            report.holder_name = event.holder_name
            report.balance = event.balance
            report.status = event.status
        except Exception:
            report = AccountReport(
                account_id=event.id,
                account_number=event.account_number,
                holder_name=event.holder_name,
                balance=event.balance,
                status=event.status,
            )

        repo.add(report)


# --8<-- [end:full_domain]
# --8<-- [start:activity_feed_projection]
@domain.projection
class ActivityFeed:
    """A cross-aggregate projection that tracks all account activity,
    including deposits, withdrawals, and completed transfers."""

    entry_id: Identifier(identifier=True, required=True)
    account_id: String(max_length=50, required=True)
    entry_type: String(max_length=30, required=True)
    amount: Float(default=0.0)
    description: String(max_length=255)
    timestamp: DateTime()


# --8<-- [end:activity_feed_projection]
# --8<-- [start:activity_feed_projector]
@domain.projector(
    projector_for=ActivityFeed,
    aggregates=[Account, Transfer],
)
class ActivityFeedProjector:
    """Maintains the ActivityFeed by listening to events from both the
    Account and Transfer aggregates."""

    @on(DepositMade)
    def on_deposit_made(self, event: DepositMade):
        entry = ActivityFeed(
            entry_id=event._metadata.headers.id,
            account_id=event.account_id,
            entry_type="deposit",
            amount=event.amount,
            description=f"Deposit: {event.reference or 'no reference'}",
            timestamp=event._metadata.headers.time,
        )
        current_domain.repository_for(ActivityFeed).add(entry)

    @on(WithdrawalMade)
    def on_withdrawal_made(self, event: WithdrawalMade):
        entry = ActivityFeed(
            entry_id=event._metadata.headers.id,
            account_id=event.account_id,
            entry_type="withdrawal",
            amount=event.amount,
            description=f"Withdrawal: {event.reference or 'no reference'}",
            timestamp=event._metadata.headers.time,
        )
        current_domain.repository_for(ActivityFeed).add(entry)

    @on(TransferCompleted)
    def on_transfer_completed(self, event: TransferCompleted):
        entry = ActivityFeed(
            entry_id=event._metadata.headers.id,
            account_id=event.transfer_id,
            entry_type="transfer_completed",
            amount=0.0,
            description=f"Transfer {event.transfer_id} completed",
            timestamp=event._metadata.headers.time,
        )
        current_domain.repository_for(ActivityFeed).add(entry)


# --8<-- [end:activity_feed_projector]
# ---------------------------------------------------------------------------
# Process Manager
# ---------------------------------------------------------------------------
@domain.process_manager(stream_categories=["fidelis::transfer", "fidelis::account"])
class FundsTransferPM:
    transfer_id: Identifier()
    source_account_id: String()
    destination_account_id: String()
    amount: Float()
    status: String(default="new")

    @handle(TransferInitiated, start=True, correlate="transfer_id")
    def on_transfer_initiated(self, event: TransferInitiated) -> None:
        self.transfer_id = event.transfer_id
        self.source_account_id = event.source_account_id
        self.destination_account_id = event.destination_account_id
        self.amount = event.amount
        self.status = "withdrawing"

        current_domain.process(
            MakeWithdrawal(
                account_id=event.source_account_id,
                amount=event.amount,
                reference=f"transfer:{event.transfer_id}",
            )
        )

    @handle(WithdrawalMade, correlate="account_id")
    def on_withdrawal_made(self, event: WithdrawalMade) -> None:
        self.status = "depositing"

        current_domain.process(
            MakeDeposit(
                account_id=self.destination_account_id,
                amount=self.amount,
                reference=f"transfer:{self.transfer_id}",
            )
        )

    @handle(DepositMade, correlate="account_id")
    def on_deposit_made(self, event: DepositMade) -> None:
        self.status = "completing"

        current_domain.process(CompleteTransfer(transfer_id=self.transfer_id))

    @handle(TransferCompleted, correlate="transfer_id")
    def on_transfer_completed(self, event: TransferCompleted) -> None:
        self.status = "completed"
        self.mark_as_complete()

    @handle(TransferFailed, correlate="transfer_id", end=True)
    def on_transfer_failed(self, event: TransferFailed) -> None:
        self.status = "failed"


domain.init(traverse=False)
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --8<-- [start:production_config]
PRODUCTION_DOMAIN_TOML = """\
# domain.toml — Fidelis production configuration
# Place this file alongside your domain module.

[event_store]
provider = "message_db"
database_uri = "postgresql://message_store@localhost:5433/message_store"

[broker]
provider = "redis"
redis_url = "redis://localhost:6379/0"

[databases.default]
provider = "postgresql"
database_uri = "postgresql://postgres:postgres@localhost:5432/fidelis"

[server]
workers = 4

[server.priority_lanes]
enabled = true
threshold = 0
"""
# --8<-- [end:production_config]
if __name__ == "__main__":
    with domain.domain_context():
        # Open two accounts
        alice_id = domain.process(
            OpenAccount(
                account_number="ACC-001",
                holder_name="Alice Johnson",
                opening_deposit=10000.00,
            )
        )
        bob_id = domain.process(
            OpenAccount(
                account_number="ACC-002",
                holder_name="Bob Smith",
                opening_deposit=5000.00,
            )
        )
        print(f"Alice's account: {alice_id}")
        print(f"Bob's account: {bob_id}")

        # Direct deposit into Alice's account
        domain.process(
            MakeDeposit(
                account_id=alice_id,
                amount=2000.00,
                reference="bonus",
            )
        )
        print("Alice received $2,000.00 bonus")

        # Verify aggregate state after direct operations
        account_repo = current_domain.repository_for(Account)
        alice = account_repo.get(alice_id)
        bob = account_repo.get(bob_id)
        print(f"\nAlice's balance: ${alice.balance:.2f}")  # 10000 + 2000 = 12000
        print(f"Bob's balance: ${bob.balance:.2f}")  # 5000

        # Verify AccountSummary projection (populated by projector)
        summary_repo = current_domain.repository_for(AccountSummary)
        alice_summary = summary_repo.get(alice_id)
        print(
            f"\nAlice summary - Balance: ${alice_summary.balance:.2f}, "
            f"Transactions: {alice_summary.transaction_count}"
        )

        # Verify fact events exist in the event store
        fact_stream = f"{Account.meta_.stream_category}-fact-{alice_id}"
        fact_messages = domain.event_store.store.read(fact_stream)
        print(f"\nFact events for Alice: {len(fact_messages)}")
        last_fact = fact_messages[-1].to_domain_object()
        print(
            f"Alice report  - Balance: ${last_fact.balance:.2f}, "
            f"Status: {last_fact.status}"
        )

        # Initiate a transfer (process manager will coordinate the full
        # flow when running with `protean server` in async mode)
        transfer_id = domain.process(
            InitiateTransfer(
                source_account_id=alice_id,
                destination_account_id=bob_id,
                amount=3000.00,
            )
        )
        print(f"\nTransfer initiated: {transfer_id}")

        transfer_repo = current_domain.repository_for(Transfer)
        transfer = transfer_repo.get(transfer_id)
        print(f"Transfer status: {transfer.status}")

        assert alice.balance == 12000.00  # 10000 + 2000
        assert bob.balance == 5000.00
        assert alice_summary.balance == 12000.00
        assert alice_summary.transaction_count == 2  # open + deposit
        assert last_fact.balance == 12000.00
        assert len(fact_messages) == 2  # one per state change (open + deposit)
        assert transfer.status == "INITIATED"
        print("\nAll checks passed!")
# --8<-- [end:full]
