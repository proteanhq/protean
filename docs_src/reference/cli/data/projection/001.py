# --8<-- [start:domain]
from protean import Domain, current_domain
from protean.core.projector import on
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


@domain.aggregate
class Account:
    account_id: Identifier(identifier=True)
    holder: String(required=True)

    @classmethod
    def open(cls, account_id: str, holder: str) -> "Account":
        account = cls(account_id=account_id, holder=holder)
        account.raise_(AccountOpened(account_id=account_id, holder=holder))
        return account

    def deposit(self, amount: float) -> None:
        self.raise_(MoneyDeposited(account_id=self.account_id, amount=amount))


@domain.projection
class Balances:
    account_id: Identifier(identifier=True)
    holder: String()
    balance: Float(default=0.0)


@domain.projector(projector_for=Balances, aggregates=[Account])
class BalancesProjector:
    @on(AccountOpened)
    def opened(self, event: AccountOpened) -> None:
        current_domain.repository_for(Balances).add(
            Balances(account_id=event.account_id, holder=event.holder)
        )

    @on(MoneyDeposited)
    def deposited(self, event: MoneyDeposited) -> None:
        repo = current_domain.repository_for(Balances)
        balances = repo.get(event.account_id)
        balances.balance += event.amount
        repo.add(balances)


domain.init(traverse=False)

with domain.domain_context():
    alice = Account.open("acc-1", holder="Alice")
    alice.deposit(100.0)
    alice.deposit(50.0)
    domain.repository_for(Account).add(alice)
    domain.repository_for(Account).add(Account.open("acc-2", holder="Bob"))
# --8<-- [end:domain]

# --8<-- [start:api]
from protean.utils.projection_rebuilder import RebuildResult

with domain.domain_context():
    # Rebuild a single projection
    result = domain.rebuild_projection(Balances)
    assert result.success
    print(f"{result.events_dispatched} events replayed")

    # Rebuild a single projection with custom batch size
    result = domain.rebuild_projection(Balances, batch_size=1000)

    # Rebuild all projections
    results: dict[str, RebuildResult] = domain.rebuild_all_projections()
    for name, result in results.items():
        print(f"{name}: {result.events_dispatched} events")
# --8<-- [end:api]
