# --8<-- [start:event_sourced]
from protean import Domain, apply
from protean.exceptions import ValidationError
from protean.fields import Auto, Float, Identifier

domain = Domain(name="EncapsulateStateChangesLedger")


@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)
    opening_balance: Float(required=True)


@domain.event(part_of="Account")
class MoneyWithdrawn:
    account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate(event_sourced=True)
class Account:
    account_id: Auto(identifier=True)
    balance: Float(default=0.0)

    @classmethod
    def open(cls, opening_balance: float) -> "Account":
        account = cls._create_new()
        account.raise_(
            AccountOpened(
                account_id=account.account_id,
                opening_balance=opening_balance,
            )
        )
        return account

    def withdraw(self, amount: float) -> None:
        if amount <= 0:
            raise ValidationError({"amount": ["Withdrawal amount must be positive"]})
        if self.balance - amount < 0:
            raise ValidationError({"balance": ["Insufficient funds"]})
        self.raise_(
            MoneyWithdrawn(
                account_id=self.account_id,
                amount=amount,
            )
        )

    @apply
    def on_account_opened(self, event: AccountOpened):
        self.account_id = event.account_id
        self.balance = event.opening_balance

    @apply
    def on_money_withdrawn(self, event: MoneyWithdrawn):
        self.balance -= event.amount


# --8<-- [end:event_sourced]
