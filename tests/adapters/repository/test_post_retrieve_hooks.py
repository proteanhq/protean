"""Tests for BaseDAO._sync_event_position and _track_in_uow.

These methods are post-retrieval hooks called by QuerySet.all() and
QuerySet.raw() after converting database models to domain entities.
They were extracted from inline logic in QuerySet to decouple the
query layer from aggregate-specific business logic (event-position
syncing and UoW identity-map tracking).
"""

import pytest

from protean import UnitOfWork
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.fields import HasOne, Identifier, Integer, String


# --- Domain elements for testing ---


class Wallet(BaseEntity):
    balance: Integer(default=0)


class BalanceUpdated(BaseEvent):
    customer_id: Identifier(required=True)
    new_balance: Integer(required=True)


class Customer(BaseAggregate):
    name: String(max_length=100, required=True)
    email: String(max_length=255, required=True)

    wallet = HasOne(Wallet)

    def update_balance(self, new_balance: int) -> None:
        self.wallet.balance = new_balance
        self.raise_(BalanceUpdated(customer_id=self.id, new_balance=new_balance))


class CustomerRegistered(BaseEvent):
    customer_id: Identifier(required=True)
    name: String(max_length=100, required=True)
    email: String(max_length=255, required=True)


class SimpleEntity(BaseEntity):
    """A non-aggregate entity used to verify no-op behavior."""

    name: String(max_length=50)


class SimpleAggregate(BaseAggregate):
    name: String(max_length=50, required=True)
    simple = HasOne(SimpleEntity)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Customer)
    test_domain.register(Wallet, part_of=Customer)
    test_domain.register(BalanceUpdated, part_of=Customer)
    test_domain.register(CustomerRegistered, part_of=Customer)
    test_domain.register(SimpleAggregate)
    test_domain.register(SimpleEntity, part_of=SimpleAggregate)
    test_domain.init(traverse=False)


# --- Tests for _sync_event_position ---


class TestSyncEventPosition:
    """Tests for BaseDAO._sync_event_position."""

    def test_no_op_for_non_aggregate(self, test_domain):
        """_sync_event_position is a no-op for non-aggregate entities."""
        # Persist a SimpleAggregate (which contains a SimpleEntity)
        agg = SimpleAggregate(name="Parent")
        test_domain.repository_for(SimpleAggregate).add(agg)

        # Get the entity DAO and verify _sync_event_position is a no-op
        entity_dao = test_domain.repository_for(SimpleEntity)._dao
        entity = SimpleEntity(name="Child")
        # Should not raise and should not modify the entity
        entity_dao._sync_event_position(entity)

    def test_event_position_negative_one_when_no_events(self, test_domain):
        """Aggregate with no events should have _event_position == -1."""
        customer = Customer(name="John", email="john@example.com")
        test_domain.repository_for(Customer).add(customer)

        refreshed = test_domain.repository_for(Customer).get(customer.id)
        assert refreshed._event_position == -1

    def test_event_position_synced_after_one_event(self, test_domain):
        """After raising one event, _event_position should be 0."""
        customer = Customer(name="John", email="john@example.com")
        customer.raise_(
            CustomerRegistered(
                customer_id=customer.id,
                name=customer.name,
                email=customer.email,
            )
        )
        test_domain.repository_for(Customer).add(customer)

        refreshed = test_domain.repository_for(Customer).get(customer.id)
        assert refreshed._event_position == 0

    def test_event_position_synced_after_multiple_events(self, test_domain):
        """After raising multiple events across updates, position increments."""
        customer = Customer(name="John", email="john@example.com")
        customer.raise_(
            CustomerRegistered(
                customer_id=customer.id,
                name=customer.name,
                email=customer.email,
            )
        )
        test_domain.repository_for(Customer).add(customer)

        # Reload and raise another event
        refreshed = test_domain.repository_for(Customer).get(customer.id)
        assert refreshed._event_position == 0

        refreshed.raise_(BalanceUpdated(customer_id=refreshed.id, new_balance=100))
        test_domain.repository_for(Customer).add(refreshed)

        # Reload again — position should now be 1
        refreshed2 = test_domain.repository_for(Customer).get(customer.id)
        assert refreshed2._event_position == 1

    def test_direct_dao_call_syncs_position(self, test_domain):
        """Calling _sync_event_position directly on a DAO-fetched entity works."""
        customer = Customer(name="Jane", email="jane@example.com")
        customer.raise_(
            CustomerRegistered(
                customer_id=customer.id,
                name=customer.name,
                email=customer.email,
            )
        )
        test_domain.repository_for(Customer).add(customer)

        # Load via DAO query (which goes through QuerySet.all())
        dao = test_domain.repository_for(Customer)._dao
        results = dao.query.filter(email="jane@example.com").all()
        assert results.first._event_position == 0


# --- Tests for _track_in_uow ---


class TestTrackInUoW:
    """Tests for BaseDAO._track_in_uow."""

    def test_no_op_without_uow(self, test_domain):
        """_track_in_uow is a no-op when there is no active UoW."""
        customer = Customer(name="John", email="john@example.com")
        dao = test_domain.repository_for(Customer)._dao
        # Should not raise — simply a no-op
        dao._track_in_uow(customer)

    def test_aggregate_tracked_in_uow(self, test_domain):
        """Aggregate retrieved inside a UoW is tracked in the identity map."""
        customer = Customer(name="John", email="john@example.com")
        test_domain.repository_for(Customer).add(customer)

        with UnitOfWork() as uow:
            refreshed = test_domain.repository_for(Customer).get(customer.id)
            # The aggregate should be in the identity map
            provider_name = refreshed.meta_.provider
            assert customer.id in uow._identity_map[provider_name]

    def test_non_aggregate_not_tracked(self, test_domain):
        """Non-aggregate entities should not be tracked in the UoW."""
        entity = SimpleEntity(name="Child")
        dao = test_domain.repository_for(SimpleEntity)._dao

        with UnitOfWork() as uow:
            dao._track_in_uow(entity)
            # Identity map should have no entries for this entity
            for provider_map in uow._identity_map.values():
                assert entity not in provider_map.values()


# --- Integration tests: QuerySet.all() and QuerySet.raw() ---


class TestQuerySetIntegration:
    """Verify that QuerySet.all() and QuerySet.raw() call the hooks."""

    def test_all_syncs_event_position(self, test_domain):
        """QuerySet.all() syncs event position for aggregates."""
        customer = Customer(name="Alice", email="alice@example.com")
        customer.raise_(
            CustomerRegistered(
                customer_id=customer.id,
                name=customer.name,
                email=customer.email,
            )
        )
        test_domain.repository_for(Customer).add(customer)

        results = test_domain.repository_for(Customer)._dao.query.all()
        assert results.first._event_position == 0

    def test_all_tracks_aggregate_in_uow(self, test_domain):
        """QuerySet.all() registers aggregates in the UoW identity map."""
        customer = Customer(name="Bob", email="bob@example.com")
        test_domain.repository_for(Customer).add(customer)

        with UnitOfWork() as uow:
            results = test_domain.repository_for(Customer)._dao.query.all()
            assert len(results) == 1
            provider_name = results.first.meta_.provider
            assert customer.id in uow._identity_map[provider_name]

    def test_raw_syncs_event_position(self, test_domain):
        """QuerySet.raw() syncs event position (previously missing)."""
        customer = Customer(name="Carol", email="carol@example.com")
        customer.raise_(
            CustomerRegistered(
                customer_id=customer.id,
                name=customer.name,
                email=customer.email,
            )
        )
        test_domain.repository_for(Customer).add(customer)

        # Memory provider expects raw queries as JSON strings
        results = test_domain.repository_for(Customer)._dao.query.raw(
            '{"email": "carol@example.com"}'
        )
        assert results.first._event_position == 0

    def test_raw_tracks_aggregate_in_uow(self, test_domain):
        """QuerySet.raw() registers aggregates in the UoW identity map."""
        customer = Customer(name="Dave", email="dave@example.com")
        test_domain.repository_for(Customer).add(customer)

        with UnitOfWork() as uow:
            results = test_domain.repository_for(Customer)._dao.query.raw(
                '{"email": "dave@example.com"}'
            )
            assert len(results) == 1
            provider_name = results.first.meta_.provider
            assert customer.id in uow._identity_map[provider_name]
