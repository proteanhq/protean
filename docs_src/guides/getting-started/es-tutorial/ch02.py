# --8<-- [start:full]
from protean import Domain, apply
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String

domain = Domain("fidelis")


# --8<-- [start:events]
@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)
    account_number: String(required=True)
    holder_name: String(required=True)
    opening_deposit: Float(required=True)


# --8<-- [start:deposit_withdrawal_events]
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


# --8<-- [end:deposit_withdrawal_events]


# --8<-- [end:events]
# --8<-- [start:aggregate]
@domain.aggregate(is_event_sourced=True)
class Account:
    account_number: String(max_length=20, required=True)
    holder_name: String(max_length=100, required=True)
    balance: Float(default=0.0)
    status: String(max_length=20, default="ACTIVE")

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
        if amount > self.balance:
            raise ValidationError({"amount": ["Insufficient funds"]})
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


# --8<-- [end:aggregate]
domain.init(traverse=False)


# --8<-- [start:usage]
# --8<-- [start:main_usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Open an account
        account = Account.open(
            account_number="ACC-001",
            holder_name="Alice Johnson",
            opening_deposit=1000.00,
        )

        # Make several transactions
        account.deposit(500.00, reference="paycheck")
        account.deposit(200.00, reference="refund")
        account.withdraw(150.00, reference="groceries")

        # Persist — all four events are written to the event store
        repo = domain.repository_for(Account)
        repo.add(account)

        # Retrieve — all four events are replayed
        loaded = repo.get(account.id)
        print(f"Account: {loaded.holder_name} ({loaded.account_number})")
        print(f"Balance: ${loaded.balance:.2f}")  # 1000 + 500 + 200 - 150 = 1550
        print(f"Version: {loaded._version}")

        # Each event incremented the version
        assert loaded.balance == 1550.00
        assert loaded._version == 3  # 0-indexed: events 0, 1, 2, 3
        # --8<-- [end:main_usage]
        # --8<-- [start:overdraft_validation]
        # Try an invalid withdrawal
        try:
            loaded.withdraw(10000.00)
        except ValidationError as e:
            print(f"\nRejected: {e.messages}")
        # --8<-- [end:overdraft_validation]
        print("\nAll checks passed!")
# --8<-- [end:usage]
# --8<-- [end:full]
