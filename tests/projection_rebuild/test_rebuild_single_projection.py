"""Tests for rebuilding a single projection."""

import pytest

from protean import current_domain

from .elements import (
    Balances,
    Registered,
    Transacted,
    Transaction,
    TransactionProjector,
    User,
    UserDirectory,
    UserDirectoryProjector,
    ProfileUpdated,
)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(ProfileUpdated, part_of=User)
    test_domain.register(Transaction)
    test_domain.register(Transacted, part_of=Transaction)
    test_domain.register(Balances)
    test_domain.register(
        TransactionProjector,
        projector_for=Balances,
        aggregates=[Transaction, User],
    )
    test_domain.register(UserDirectory)
    test_domain.register(
        UserDirectoryProjector,
        projector_for=UserDirectory,
        aggregates=[User],
    )
    test_domain.init(traverse=False)


class TestRebuildEmptyEventStore:
    def test_rebuild_with_no_events(self, test_domain):
        """Rebuilding when the event store is empty succeeds with 0 events."""
        result = test_domain.rebuild_projection(Balances)

        assert result.success
        assert result.events_dispatched == 0
        assert result.projection_name == "Balances"


class TestRebuildRestoresState:
    def test_rebuild_restores_projection_state(self, test_domain):
        """After rebuilding, projection data matches what events produce."""
        # Create events by persisting aggregates (sync processing populates projection)
        user = User.register(email="john@example.com", name="John")
        current_domain.repository_for(User).add(user)

        transaction = Transaction.transact(user_id=user.id, amount=100.0)
        current_domain.repository_for(Transaction).add(transaction)

        # Verify projection is populated
        balance = current_domain.repository_for(Balances).get(user.id)
        assert balance is not None
        assert balance.balance == 100.0

        # Now rebuild — this truncates and replays
        result = test_domain.rebuild_projection(Balances)

        assert result.success
        assert result.events_dispatched > 0

        # Verify projection is restored correctly
        balance = current_domain.repository_for(Balances).get(user.id)
        assert balance is not None
        assert balance.name == "John"
        assert balance.balance == 100.0

    def test_rebuild_truncates_stale_data(self, test_domain):
        """Rebuild removes stale data that doesn't correspond to any events."""
        # Insert stale data directly
        stale = Balances(user_id="stale-id", name="Stale", balance=999.0)
        current_domain.repository_for(Balances).add(stale)

        # Verify stale data exists
        assert current_domain.repository_for(Balances).get("stale-id") is not None

        # Rebuild with empty event store
        result = test_domain.rebuild_projection(Balances)
        assert result.success

        # Stale data should be gone
        with pytest.raises(Exception):
            current_domain.repository_for(Balances).get("stale-id")


class TestRebuildWithMultipleEvents:
    def test_multiple_transactions_accumulate(self, test_domain):
        """Multiple events for the same aggregate accumulate correctly."""
        user = User.register(email="jane@example.com", name="Jane")
        current_domain.repository_for(User).add(user)

        for amount in [50.0, 75.0, 25.0]:
            txn = Transaction.transact(user_id=user.id, amount=amount)
            current_domain.repository_for(Transaction).add(txn)

        # Rebuild
        result = test_domain.rebuild_projection(Balances)
        assert result.success

        balance = current_domain.repository_for(Balances).get(user.id)
        assert balance is not None
        assert balance.balance == 150.0


class TestRebuildCrossAggregate:
    def test_cross_aggregate_projection(self, test_domain):
        """Projector listening to multiple stream categories replays all."""
        user = User.register(email="cross@example.com", name="Cross")
        current_domain.repository_for(User).add(user)

        txn = Transaction.transact(user_id=user.id, amount=200.0)
        current_domain.repository_for(Transaction).add(txn)

        result = test_domain.rebuild_projection(Balances)

        assert result.success
        # TransactionProjector listens to both User and Transaction categories
        assert result.categories_processed == 2
        assert result.projectors_processed == 1

        balance = current_domain.repository_for(Balances).get(user.id)
        assert balance is not None
        assert balance.balance == 200.0


class TestRebuildSkipsUnhandledEvents:
    def test_unhandled_events_skipped(self, test_domain):
        """Events that the projector has no handler for are silently skipped."""
        user = User.register(email="skip@example.com", name="Skipper")
        current_domain.repository_for(User).add(user)

        # Raise an event that no projector handles
        user.raise_(ProfileUpdated(user_id=user.id, new_name="New Name"))
        current_domain.repository_for(User).add(user)

        # Rebuild should succeed — ProfileUpdated has no handler in TransactionProjector
        result = test_domain.rebuild_projection(Balances)
        assert result.success


class TestRebuildReturnsResult:
    def test_result_fields(self, test_domain):
        """RebuildResult has correct field values."""
        user = User.register(email="result@example.com", name="Result")
        current_domain.repository_for(User).add(user)

        result = test_domain.rebuild_projection(Balances)

        assert result.projection_name == "Balances"
        assert result.projectors_processed == 1
        assert result.categories_processed == 2  # User + Transaction categories
        assert result.events_dispatched >= 1
        assert result.events_skipped == 0
        assert result.success is True
        assert result.errors == []
