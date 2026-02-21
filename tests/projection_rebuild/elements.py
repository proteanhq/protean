"""Domain elements for projection rebuild tests.

Provides aggregates, events, projections, and projectors used across all
projection rebuild test modules.  Includes both database-backed and
cache-backed projections to cover both truncation paths.
"""

from protean import current_domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.fields import Float, Identifier, String


# ---- User aggregate ----


class User(BaseAggregate):
    email: String()
    name: String()

    @classmethod
    def register(cls, email: str, name: str):
        user = cls(email=email, name=name)
        user.raise_(Registered(user_id=user.id, email=email, name=name))
        return user


class Registered(BaseEvent):
    user_id: Identifier()
    email: String()
    name: String()


class ProfileUpdated(BaseEvent):
    """Event that no projector handles — used to test silent skip."""

    user_id: Identifier()
    new_name: String()


# ---- Transaction aggregate ----


class Transaction(BaseAggregate):
    user_id: Identifier()
    amount: Float()

    @classmethod
    def transact(cls, user_id: str, amount: float):
        transaction = cls(user_id=user_id, amount=amount)
        transaction.raise_(Transacted(user_id=user_id, amount=amount))
        return transaction


class Transacted(BaseEvent):
    user_id: Identifier()
    amount: Float()


# ---- Balances projection (cross-aggregate, database-backed) ----


class Balances(BaseProjection):
    user_id: Identifier(identifier=True)
    name: String()
    balance: Float(default=0.0)


class TransactionProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered):
        balance = Balances(user_id=event.user_id, name=event.name, balance=0)
        current_domain.repository_for(Balances).add(balance)

    @on(Transacted)
    def on_transacted(self, event: Transacted):
        balance = current_domain.repository_for(Balances).get(event.user_id)
        if balance:
            balance.balance += event.amount
        else:
            balance = Balances(user_id=event.user_id, name="", balance=event.amount)
        current_domain.repository_for(Balances).add(balance)


# ---- UserDirectory projection (single-aggregate, database-backed) ----


class UserDirectory(BaseProjection):
    user_id: Identifier(identifier=True)
    email: String()
    name: String()


class UserDirectoryProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered):
        entry = UserDirectory(user_id=event.user_id, email=event.email, name=event.name)
        current_domain.repository_for(UserDirectory).add(entry)


# ---- CachedSummary projection (cache-backed) ----


class CachedSummary(BaseProjection):
    """A cache-backed projection used to test cache truncation path."""

    user_id: Identifier(identifier=True)
    name: String()


class CachedSummaryProjector(BaseProjector):
    @on(Registered)
    def on_registered(self, event: Registered):
        entry = CachedSummary(user_id=event.user_id, name=event.name)
        current_domain.cache_for(CachedSummary).add(entry)


# ---- FailingProjector (for error handling tests) ----


class FailingProjector(BaseProjector):
    """A projector that raises an exception on every event."""

    @on(Registered)
    def on_registered(self, event: Registered):
        raise RuntimeError("Deliberate failure in projector handler")
