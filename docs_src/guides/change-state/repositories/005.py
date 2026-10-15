from datetime import UTC, datetime, timedelta

from protean import Domain, apply
from protean.fields import Float, Identifier

domain = Domain()


@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)
    balance: Float(required=True)


@domain.event(part_of="Account")
class Deposited:
    account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate(event_sourced=True)
class Account:
    account_id: Identifier(identifier=True)
    balance: Float(default=0.0)

    @classmethod
    def open(cls, account_id: str, balance: float) -> "Account":
        account = cls(account_id=account_id, balance=balance)
        account.raise_(AccountOpened(account_id=account_id, balance=balance))
        return account

    def deposit(self, amount: float) -> None:
        self.raise_(Deposited(account_id=self.account_id, amount=amount))

    @apply
    def opened(self, event: AccountOpened) -> None:
        self.account_id = event.account_id
        self.balance = event.balance

    @apply
    def deposited(self, event: Deposited) -> None:
        self.balance += event.amount


# --8<-- [start:event_sourced_get_or_none]
def balance_or_zero(account_id: str) -> float:
    repo = domain.repository_for(Account)

    # Returns None when the account has no event stream
    account = repo.get_or_none(account_id)
    if account is None:
        return 0.0
    return account.balance


def balance_at_version(account_id: str, version: int) -> float | None:
    repo = domain.repository_for(Account)

    # Returns None when the stream has no event at that version
    account = repo.get_or_none(account_id, at_version=version)
    return None if account is None else account.balance


def balance_as_of(account_id: str, as_of: datetime) -> float | None:
    repo = domain.repository_for(Account)

    # Returns None when the stream has no events on or before as_of
    account = repo.get_or_none(account_id, as_of=as_of)
    return None if account is None else account.balance


# --8<-- [end:event_sourced_get_or_none]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        repo = domain.repository_for(Account)
        repo.add(Account.open("acc-1", 100.0))

        account = repo.get("acc-1")
        account.deposit(50.0)
        repo.add(account)

        print(balance_or_zero("acc-1"))  # 150.0
        print(balance_or_zero("unknown"))  # 0.0
        print(balance_at_version("acc-1", 0))  # 100.0
        print(balance_at_version("acc-1", 5))  # None
        print(balance_as_of("acc-1", datetime.now(UTC) - timedelta(days=1)))  # None
