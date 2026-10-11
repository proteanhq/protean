# --8<-- [start:aggregate]
from protean import Domain, apply
from protean.fields import Float, Identifier, String

domain = Domain(name="Banking")


@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)
    holder: String(required=True)


@domain.event(part_of="Account")
class MoneyDeposited:
    account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate(event_sourced=True)
class Account:
    account_id: Identifier(identifier=True)
    holder: String(required=True)
    balance: Float(default=0.0)

    @classmethod
    def open(cls, account_id: str, holder: str) -> "Account":
        account = cls(account_id=account_id, holder=holder)
        account.raise_(AccountOpened(account_id=account_id, holder=holder))
        return account

    def deposit(self, amount: float) -> None:
        self.raise_(MoneyDeposited(account_id=self.account_id, amount=amount))

    @apply
    def opened(self, event: AccountOpened) -> None:
        self.account_id = event.account_id
        self.holder = event.holder
        self.balance = 0.0

    @apply
    def deposited(self, event: MoneyDeposited) -> None:
        self.balance += event.amount


domain.init(traverse=False)

with domain.domain_context():
    account = Account.open("acc-001", holder="Alice")
    account.deposit(100.0)
    account.deposit(50.0)
    domain.repository_for(Account).add(account)
# --8<-- [end:aggregate]

# --8<-- [start:manual]
with domain.domain_context():
    # Snapshot a single aggregate instance
    domain.create_snapshot(Account, "acc-001")

    # Snapshot all instances of an aggregate
    count = domain.create_snapshots(Account)
    print(f"Created {count} snapshots")

    # Snapshot all event-sourced aggregates
    results = domain.create_all_snapshots()
    for name, count in results.items():
        print(f"{name}: {count} snapshots")
# --8<-- [end:manual]
