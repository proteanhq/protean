# --8<-- [start:domain]
from protean import Domain, current_domain
from protean.core.projector import on
from protean.fields import Float, Identifier, String

domain = Domain(name="Banking")


@domain.event(part_of="User")
class Registered:
    user_id: Identifier(required=True)
    name: String(required=True)


@domain.aggregate
class User:
    user_id: Identifier(identifier=True)
    name: String(required=True)

    @classmethod
    def register(cls, user_id, name):
        user = cls(user_id=user_id, name=name)
        user.raise_(Registered(user_id=user_id, name=name))
        return user


@domain.event(part_of="Transaction")
class Transacted:
    transaction_id: Identifier(required=True)
    user_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate
class Transaction:
    transaction_id: Identifier(identifier=True)
    user_id: Identifier(required=True)
    amount: Float(required=True)

    @classmethod
    def record(cls, transaction_id, user_id, amount):
        transaction = cls(transaction_id=transaction_id, user_id=user_id, amount=amount)
        transaction.raise_(
            Transacted(transaction_id=transaction_id, user_id=user_id, amount=amount)
        )
        return transaction


@domain.projection
class Balances:
    user_id: Identifier(identifier=True)
    name: String()
    balance: Float(default=0.0)


@domain.projector(projector_for=Balances, aggregates=[User, Transaction])
class BalancesProjector:
    @on(Registered)
    def registered(self, event: Registered):
        current_domain.repository_for(Balances).add(
            Balances(user_id=event.user_id, name=event.name)
        )

    @on(Transacted)
    def transacted(self, event: Transacted):
        repo = current_domain.repository_for(Balances)
        balances = repo.get(event.user_id)
        balances.balance += event.amount
        repo.add(balances)


domain.init(traverse=False)

with domain.domain_context():
    domain.repository_for(User).add(User.register("u-1", "Alice"))
    domain.repository_for(Transaction).add(Transaction.record("t-1", "u-1", 100.0))
    domain.repository_for(Transaction).add(Transaction.record("t-2", "u-1", -30.0))
    domain.repository_for(User).add(User.register("u-2", "Bob"))
# --8<-- [end:domain]

# --8<-- [start:api]
with domain.domain_context():
    # Rebuild a single projection
    result = domain.rebuild_projection(Balances)
    assert result.success
    print(f"{result.events_dispatched} events, {result.events_skipped} skipped")

    # Rebuild all projections
    results = domain.rebuild_all_projections()  # {"Balances": RebuildResult, ...}
# --8<-- [end:api]
