# --8<-- [start:bank_account]
from protean import Domain, apply, handle
from protean.fields import Float, Identifier
from protean.utils.globals import current_domain

domain = Domain(name="Banking")


@domain.event(part_of="BankAccount")
class AccountOpened:
    account_id: Identifier(required=True)


@domain.event(part_of="BankAccount")
class MoneyDeposited:
    account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.command(part_of="BankAccount")
class DepositMoney:
    account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate(event_sourced=True)
class BankAccount:
    account_id: Identifier(identifier=True)
    balance: Float(default=0.0)

    @classmethod
    def open(cls, account_id: str) -> "BankAccount":
        account = cls(account_id=account_id)
        account.raise_(AccountOpened(account_id=account_id))
        return account

    @apply
    def on_opened(self, event: AccountOpened) -> None:
        self.account_id = event.account_id
        self.balance = 0.0

    @apply
    def on_deposited(self, event: MoneyDeposited) -> None:
        self.balance += event.amount


@domain.command_handler(part_of=BankAccount)
class BankAccountCommandHandler:
    @handle(DepositMoney)
    def deposit(self, command: DepositMoney) -> None:
        repo = current_domain.repository_for(BankAccount)
        account = repo.get(command.account_id)

        account.raise_(
            MoneyDeposited(
                account_id=command.account_id,
                amount=command.amount,
            )
        )
        repo.add(account)


# --8<-- [end:bank_account]
