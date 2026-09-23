"""
Projector that listens to events from multiple aggregates.

This example demonstrates:
- Cross-aggregate projector using aggregates=[User, Transaction]
- A projection that combines data from two different aggregates
- Handling events from User aggregate (Registered) and Transaction aggregate (Transacted)
- Building a denormalized view (Balances) that spans aggregate boundaries
- Synchronous event processing for testing

Usage:
    user = User.register(email="alice@example.com", name="Alice")
    domain.repository_for(User).add(user)
    # Creates Balances projection with balance=0

    txn = Transaction.transact(user_id=user.id, amount=100.0)
    domain.repository_for(Transaction).add(txn)
    # Updates Balances projection with new balance
"""

from protean import Domain
from protean.core.projector import on
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()
domain.config["event_processing"] = "sync"


@domain.event(part_of="User")
class Registered:
    """Event raised when a new user registers."""

    user_id: Identifier(required=True)
    email: String(required=True)
    name: String(required=True)


@domain.event(part_of="Transaction")
class Transacted:
    """Event raised when a transaction occurs."""

    user_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate
class User:
    """User aggregate representing registered users."""

    email: String(required=True)
    name: String(required=True)

    @classmethod
    def register(cls, email, name):
        """Factory method that registers a user and raises Registered event."""
        user = cls(email=email, name=name)
        user.raise_(Registered(user_id=user.id, email=email, name=name))
        return user


@domain.aggregate
class Transaction:
    """Transaction aggregate representing financial transactions."""

    user_id: Identifier(required=True)
    amount: Float(required=True)

    @classmethod
    def transact(cls, user_id, amount):
        """Factory method that creates a transaction and raises Transacted event."""
        txn = cls(user_id=user_id, amount=amount)
        txn.raise_(Transacted(user_id=user_id, amount=amount))
        return txn


@domain.projection
class Balances:
    """Cross-aggregate projection combining User and Transaction data.

    Tracks each user's current balance by processing registration
    events (to initialize the record) and transaction events
    (to update the balance).
    """

    user_id: Identifier(identifier=True)
    name: String()
    balance: Float()


@domain.projector(
    projector_for=Balances,
    aggregates=[User, Transaction],
)
class TransactionProjector:
    """Projector maintaining the Balances projection.

    Listens to events from both User and Transaction aggregates
    to build a denormalized view of user balances.
    """

    @on(Registered)
    def on_registered(self, event: Registered):
        """Initialize a balance record when a new user registers."""
        balance = Balances(user_id=event.user_id, name=event.name, balance=0)
        domain.repository_for(Balances).add(balance)

    @on(Transacted)
    def on_transacted(self, event: Transacted):
        """Update balance when a transaction occurs."""
        balance = domain.repository_for(Balances).get(event.user_id)
        balance.balance += event.amount
        domain.repository_for(Balances).add(balance)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Register a user
        user = User.register(email="alice@example.com", name="Alice")
        domain.repository_for(User).add(user)

        # Verify initial balance
        balance = domain.repository_for(Balances).get(user.id)
        print(f"User: {balance.name}, Balance: {balance.balance}")
        assert balance.balance == 0

        # Process a transaction
        txn = Transaction.transact(user_id=user.id, amount=100.0)
        domain.repository_for(Transaction).add(txn)

        # Verify updated balance
        balance = domain.repository_for(Balances).get(user.id)
        print(f"After deposit: {balance.name}, Balance: {balance.balance}")
        assert balance.balance == 100.0

        # Process another transaction
        txn2 = Transaction.transact(user_id=user.id, amount=-30.0)
        domain.repository_for(Transaction).add(txn2)

        balance = domain.repository_for(Balances).get(user.id)
        print(f"After withdrawal: {balance.name}, Balance: {balance.balance}")
        assert balance.balance == 70.0
        print("Cross-aggregate projector working correctly!")
