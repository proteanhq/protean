from protean import Domain, invariant
from pydantic import Field

banking = Domain()


class InsufficientFundsException(Exception):
    pass


@banking.event(part_of="Account")
class AccountWithdrawn:
    account_number: str
    amount: float


@banking.aggregate
class Account:
    account_number: str = Field(json_schema_extra={"unique": True})
    balance: float | None = None
    overdraft_limit: float = 0.0

    @invariant.post
    def balance_must_be_greater_than_or_equal_to_overdraft_limit(self):
        if self.balance < -self.overdraft_limit:
            raise InsufficientFundsException("Balance cannot be below overdraft limit")

    def withdraw(self, amount: float):
        self.balance -= amount  # Update account state (mutation)

        self.raise_(AccountWithdrawn(account_number=self.account_number, amount=amount))
