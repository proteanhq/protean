# --8<-- [start:invariant]
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, Float, Identifier

domain = Domain(name="EncapsulateStateChangesAccounts")


@domain.event(part_of="Account")
class MoneyWithdrawn:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    new_balance: Float(required=True)


@domain.aggregate
class Account:
    account_id: Auto(identifier=True)
    balance: Float(default=0.0)
    overdraft_limit: Float(default=50.0)

    def withdraw(self, amount: float) -> None:
        """Withdraw the specified amount."""
        if amount <= 0:
            raise ValidationError({"amount": ["Withdrawal amount must be positive"]})
        self.balance -= amount
        self.raise_(
            MoneyWithdrawn(
                account_id=self.account_id,
                amount=amount,
                new_balance=self.balance,
            )
        )

    @invariant.post
    def balance_must_be_above_overdraft_limit(self):
        if self.balance < -self.overdraft_limit:
            raise ValidationError(
                {"balance": ["Balance cannot be below overdraft limit"]}
            )


# --8<-- [end:invariant]
