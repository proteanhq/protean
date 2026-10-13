# --8<-- [start:full]
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier

banking = Domain()


@banking.event(part_of="Account")
class AccountWithdrawn:
    account_number: Identifier(required=True)
    amount: Float(required=True)


# --8<-- [start:account]
@banking.aggregate
class Account:
    account_number: Identifier(required=True, unique=True)
    balance: Float()
    overdraft_limit: Float(default=0.0)

    @invariant.post
    def balance_must_be_greater_than_or_equal_to_overdraft_limit(self):
        if self.balance < -self.overdraft_limit:
            raise ValidationError(
                {"_entity": ["Balance cannot be below overdraft limit"]}
            )

    def withdraw(self, amount: float):
        self.balance -= amount  # Update account state (mutation)

        self.raise_(AccountWithdrawn(account_number=self.account_number, amount=amount))


# --8<-- [end:account]
# --8<-- [end:full]
