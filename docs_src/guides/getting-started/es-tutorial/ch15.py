# --8<-- [start:full]
"""Chapter 15: Fact Events

Demonstrates how fact events provide a snapshot of aggregate state after every
change.  Fact events are auto-generated when an aggregate is configured with
``fact_events=True``.  They flow through a separate ``<aggregate>-fact``
stream, making them ideal for building projections that only need the latest
state rather than reconstructing it from individual domain events.
"""

from protean import Domain, apply, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import DateTime, Float, Identifier, String
from protean.utils.globals import current_domain

domain = Domain("fidelis")


# --8<-- [start:aggregate_with_facts]
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


# --8<-- [end:aggregate_with_facts]
# --8<-- [start:report_projection]
@domain.projection
class AccountReport:
    """A projection built entirely from fact events.

    Each fact event carries the full aggregate state, so the projector
    simply overwrites the projection record — no incremental calculations.
    """

    account_id: Identifier(identifier=True, required=True)
    account_number: String(max_length=20, required=True)
    holder_name: String(max_length=100, required=True)
    balance: Float(default=0.0)
    status: String(max_length=20, default="ACTIVE")
    last_updated: DateTime()


# --8<-- [end:report_projection]
# --8<-- [start:report_projector]
@domain.event_handler(
    part_of=Account,
    stream_category="fidelis::account-fact",
)
class AccountReportHandler:
    """Maintains the AccountReport projection from Account fact events.

    Because fact events carry the complete aggregate state, the handler
    either creates or fully replaces the projection record on every event.

    Fact events are consumed as Messages (not typed domain events) since
    the auto-generated fact event class is created at runtime.
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


# --8<-- [end:report_projector]
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

        # Make a withdrawal
        domain.process(
            MakeWithdrawal(
                account_id=account_id,
                amount=200.00,
                reference="groceries",
            )
        )
        print("Withdrawal of $200.00 made")

        # Verify account state from the event-sourced aggregate
        repo = current_domain.repository_for(Account)
        account = repo.get(account_id)
        print(f"\nAggregate balance: ${account.balance:.2f}")
        assert account.balance == 1300.00  # 1000 + 500 - 200

        # Verify fact events were generated in the event store
        fact_stream = f"{Account.meta_.stream_category}-fact-{account_id}"
        fact_messages = domain.event_store.store.read(fact_stream)
        print(f"\nFact events in stream: {len(fact_messages)}")
        for msg in fact_messages:
            event = msg.to_domain_object()
            print(f"  Balance: ${event.balance:.2f}, Status: {event.status}")

        assert len(fact_messages) == 3  # One per state change
        # Last fact event has the final state
        last_fact = fact_messages[-1].to_domain_object()
        assert last_fact.balance == 1300.00
        assert last_fact.status == "ACTIVE"

        # When the server runs, AccountReportHandler processes these
        # fact events to maintain the AccountReport projection.
        print("\nAll checks passed!")
# --8<-- [end:usage]
# --8<-- [end:full]
