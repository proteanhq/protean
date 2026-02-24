# --8<-- [start:full]
"""Chapter 19: Priority Lanes

Demonstrates how to use priority lanes to separate production traffic from
bulk/migration operations.  When priority lanes are enabled in the server
configuration, events tagged with low priority are routed to a separate
"backfill" Redis Stream and processed only when the primary stream is empty.

The ``processing_priority`` context manager tags all commands processed within
its scope with the specified priority level.
"""

from protean import Domain, apply, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain
from protean.utils.processing import Priority, processing_priority

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


# --8<-- [end:domain_setup]
domain.init(traverse=False)
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --8<-- [start:migration_example]
if __name__ == "__main__":
    with domain.domain_context():
        # Normal production traffic — uses default NORMAL priority
        account_id = domain.process(
            OpenAccount(
                account_number="ACC-001",
                holder_name="Alice Johnson",
                opening_deposit=5000.00,
            )
        )
        print(f"[NORMAL] Account opened: {account_id}")

        domain.process(
            MakeDeposit(
                account_id=account_id,
                amount=1000.00,
                reference="paycheck",
            )
        )
        print("[NORMAL] Deposit of $1,000.00 made")

        # Bulk migration — uses BULK priority so events are routed to the
        # backfill lane and processed only when the primary lane is empty
        migration_deposits = [
            {"amount": 100.00, "reference": "migration-batch-001"},
            {"amount": 200.00, "reference": "migration-batch-002"},
            {"amount": 150.00, "reference": "migration-batch-003"},
        ]

        with processing_priority(Priority.BULK):
            for item in migration_deposits:
                domain.process(
                    MakeDeposit(
                        account_id=account_id,
                        amount=item["amount"],
                        reference=item["reference"],
                    )
                )
                print(f"[BULK] Deposit of ${item['amount']:.2f} made")

        # Verify final balance
        repo = current_domain.repository_for(Account)
        account = repo.get(account_id)
        print(f"\nFinal balance: ${account.balance:.2f}")

        # 5000 + 1000 + 100 + 200 + 150 = 6450
        assert account.balance == 6450.00
        print("\nAll checks passed!")
# --8<-- [end:migration_example]
# --8<-- [end:full]
