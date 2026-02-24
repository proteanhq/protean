# --8<-- [start:full]
from protean import Domain, apply, handle
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


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Open an account via a command
        account_id = domain.process(
            OpenAccount(
                account_number="ACC-001",
                holder_name="Alice Johnson",
                opening_deposit=1000.00,
            )
        )
        print(f"Account opened: {account_id}")

        # Make a deposit via a command
        domain.process(
            MakeDeposit(
                account_id=account_id,
                amount=500.00,
                reference="paycheck",
            )
        )

        # Make a withdrawal via a command
        domain.process(
            MakeWithdrawal(
                account_id=account_id,
                amount=150.00,
                reference="groceries",
            )
        )

        # Verify the final state
        repo = domain.repository_for(Account)
        account = repo.get(account_id)
        print(f"Account: {account.holder_name}")
        print(f"Balance: ${account.balance:.2f}")  # 1000 + 500 - 150 = 1350

        assert account.balance == 1350.00
        print("\nAll checks passed!")
# --8<-- [end:usage]
# --8<-- [end:full]
