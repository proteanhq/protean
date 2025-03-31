from protean import Domain, invariant
from protean.fields import Float, Identifier

banking = Domain(__file__)


class InsufficientFundsException(Exception):
    pass


@banking.event(part_of="Account")
class AccountWithdrawn:
    account_number = Identifier(required=True)
    amount = Float(required=True)


@banking.aggregate
class Account:
    account_number = Identifier(required=True, unique=True)
    balance = Float()
    overdraft_limit = Float(default=0.0)

    @invariant.post
    def balance_must_be_greater_than_or_equal_to_overdraft_limit(self):
        if self.balance < -self.overdraft_limit:
            raise InsufficientFundsException("Balance cannot be below overdraft limit")

    def withdraw(self, amount: float):
        self.balance -= amount  # Update account state (mutation)

        self.raise_(AccountWithdrawn(account_number=self.account_number, amount=amount))
