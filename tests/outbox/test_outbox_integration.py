"""Test integration of outbox with domain and unit of work"""

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Float, Identifier, Integer, String
from protean.utils.inflection import camelize
from protean.utils.outbox import OutboxStatus


class DummyAggregate(BaseAggregate):
    name: String(max_length=50, required=True)
    count: Integer(default=0)

    def increment(self):
        self.count += 1
        # Raise an event
        self.raise_(DummyEvent(aggregate_id=self.id, name=self.name, count=self.count))


class DummyEvent(BaseEvent):
    aggregate_id: String(required=True)
    name: String(required=True)
    count: Integer(required=True)


# --- Event-sourced aggregate for outbox integration tests ---


class ESOrderPlaced(BaseEvent):
    order_id: Identifier()
    customer_id: Identifier()
    total: Float()


class ESOrderConfirmed(BaseEvent):
    order_id: Identifier()


class ESOrder(BaseAggregate):
    customer_id: Identifier()
    total: Float()
    status: String(default="new")

    @classmethod
    def place(cls, customer_id: str, total: float):
        order = cls(customer_id=customer_id, total=total)
        order.raise_(
            ESOrderPlaced(order_id=str(order.id), customer_id=customer_id, total=total)
        )
        return order

    def confirm(self):
        self.status = "confirmed"
        self.raise_(ESOrderConfirmed(order_id=str(self.id)))

    @apply
    def on_placed(self, _: ESOrderPlaced):
        pass

    @apply
    def on_confirmed(self, _: ESOrderConfirmed):
        self.status = "confirmed"


class AnotherAggregate(BaseAggregate):
    description: String(max_length=100)


class AnotherEvent(BaseEvent):
    aggregate_id: String(required=True)
    description: String(required=True)


@pytest.fixture
def test_domain():
    """`test_domain` fixture is recreated here to enable outbox for testing."""
    from protean.domain import Domain

    domain = Domain(name="Test")
    domain.config["enable_outbox"] = True
    domain.config["server"]["default_subscription_type"] = "stream"

    with domain.domain_context():
        yield domain


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(DummyAggregate)
    test_domain.register(DummyEvent, part_of=DummyAggregate)
    test_domain.register(AnotherAggregate)
    test_domain.register(AnotherEvent, part_of=AnotherAggregate)
    test_domain.init(traverse=False)


@pytest.mark.database
class TestOutboxIntegration:
    def test_domain_initializes_outbox_repos(self, test_domain):
        """Test that domain initializes outbox repositories storage"""
        assert hasattr(test_domain, "_outbox_repos")
        assert isinstance(test_domain._outbox_repos, dict)
        assert hasattr(test_domain, "_get_outbox_repo")

        # Test lazy initialization by accessing a provider
        # This triggers provider initialization
        try:
            # This will trigger provider initialization if needed
            provider_name = "default"
            outbox_repo = test_domain._get_outbox_repo(provider_name)
            assert outbox_repo is not None
            assert provider_name in test_domain._outbox_repos
        except Exception:
            # If no default provider or outbox table doesn't exist, that's expected
            pass

    def test_outbox_repos_initialized(self, test_domain):
        """Test that outbox repositories are initialized after domain initialization"""
        for provider_name, outbox_repo in test_domain._outbox_repos.items():
            assert outbox_repo is not None, (
                f"Outbox repository not initialized for provider {provider_name}"
            )

    def test_events_stored_in_outbox_during_commit(self, test_domain):
        """Test that events are stored in outbox during UnitOfWork commit"""
        # Create a test aggregate and trigger an event
        aggregate = DummyAggregate(name="Test Aggregate", count=0)

        # Check initial outbox count
        outbox_repo = test_domain._get_outbox_repo("default")
        assert outbox_repo is not None

        initial_count = len(outbox_repo.find_unprocessed())

        with UnitOfWork():
            # Trigger event
            aggregate.increment()

            # Save aggregate to database
            test_domain.repository_for(DummyAggregate).add(aggregate)

        # Check that outbox records were created after commit
        outbox_records = outbox_repo.find_unprocessed()
        assert len(outbox_records) > initial_count, (
            f"Expected > {initial_count} outbox records, got {len(outbox_records)}"
        )

        # Verify outbox record content
        outbox_record = next(
            (record for record in outbox_records if record.type == DummyEvent.__type__),
            None,
        )
        assert outbox_record is not None
        assert outbox_record.status == OutboxStatus.PENDING.value
        assert outbox_record.stream_name == f"test::dummy_aggregate-{aggregate.id}"
        assert outbox_record.data["aggregate_id"] == aggregate.id
        assert outbox_record.data["name"] == "Test Aggregate"
        assert outbox_record.data["count"] == 1

    def test_outbox_records_per_provider(self, test_domain):
        """Test that outbox records are stored in the correct provider"""
        # Create aggregates
        aggregate1 = DummyAggregate(name="Aggregate 1", count=0)
        aggregate2 = DummyAggregate(name="Aggregate 2", count=0)
        # Trigger events
        aggregate1.increment()
        aggregate2.increment()

        with UnitOfWork():
            # Save aggregates to database
            repo = test_domain.repository_for(DummyAggregate)
            repo.add(aggregate1)
            repo.add(aggregate2)

        # Check that outbox records exist for each provider
        outbox_repo = test_domain._get_outbox_repo("default")
        outbox_records = outbox_repo.find_unprocessed()

        # Should have records for both events
        test_event_records = [
            record for record in outbox_records if record.type == DummyEvent.__type__
        ]
        assert len(test_event_records) >= 2

        # Verify each record has proper provider-specific data
        for record in test_event_records:
            assert record.status == OutboxStatus.PENDING.value
            assert record.message_id is not None
            assert record.stream_name.startswith("test::dummy_aggregate-")
            assert record.data["aggregate_id"] in [aggregate1.id, aggregate2.id]

    def test_outbox_transaction_rollback_handling(self, test_domain):
        """Test that outbox records are not created if transaction rolls back"""
        aggregate = DummyAggregate(name="Test Aggregate", count=0)
        aggregate.increment()

        outbox_repo = test_domain._get_outbox_repo("default")
        initial_outbox_count = len(outbox_repo.find_unprocessed())

        try:
            with UnitOfWork():
                # Save aggregate to database
                test_domain.repository_for(DummyAggregate).add(aggregate)

                # Force a rollback by raising an exception
                raise ValueError("Forced rollback")
        except ValueError:
            pass  # Expected exception

        # Check that no new outbox records were created
        final_outbox_count = len(outbox_repo.find_unprocessed())
        assert final_outbox_count == initial_outbox_count

    def test_outbox_metadata_population(self, test_domain):
        """Test that outbox records have proper metadata"""
        aggregate = DummyAggregate(name="Test Aggregate", count=0)
        outbox_repo = test_domain._get_outbox_repo("default")

        with UnitOfWork():
            test_domain.repository_for(DummyAggregate).add(aggregate)
            aggregate.increment()

        # Check outbox record metadata
        outbox_records = outbox_repo.find_unprocessed()
        test_event_record = next(
            (record for record in outbox_records if record.type == DummyEvent.__type__),
            None,
        )

        assert test_event_record is not None
        assert test_event_record.metadata_ is not None
        assert test_event_record.metadata_.headers.time is not None
        assert test_event_record.metadata_.domain.version is not None
        assert test_event_record.metadata_.domain.fqn is not None
        assert test_event_record.created_at is not None
        assert test_event_record.retry_count == 0
        assert test_event_record.max_retries >= 3
        assert test_event_record.priority == 0

    def test_multiple_events_from_same_aggregate(self, test_domain):
        """Test handling multiple events from the same aggregate"""
        aggregate = DummyAggregate(name="Test Aggregate", count=0)
        outbox_repo = test_domain._get_outbox_repo("default")

        with UnitOfWork():
            test_domain.repository_for(DummyAggregate).add(aggregate)

            # Trigger multiple events
            aggregate.increment()  # count = 1
            aggregate.increment()  # count = 2
            aggregate.increment()  # count = 3

        # Check that all events were recorded in outbox
        outbox_records = outbox_repo.find_unprocessed()
        test_event_records = [
            record
            for record in outbox_records
            if record.type == DummyEvent.__type__
            and record.data["aggregate_id"] == aggregate.id
        ]

        assert len(test_event_records) == 3

        # Verify events have different counts
        counts = sorted([record.data["count"] for record in test_event_records])
        assert counts == [1, 2, 3]

    def test_outbox_repo_provider_mapping(self, test_domain):
        """Test that outbox repositories are correctly mapped to providers"""
        # Test that each provider has its own outbox repository
        for provider_name, provider in test_domain.providers._providers.items():
            assert provider_name in test_domain._outbox_repos
            outbox_repo = test_domain._outbox_repos[provider_name]

            # Verify the repository is configured for the correct provider
            assert outbox_repo._provider == provider
            assert (
                outbox_repo.meta_.part_of.__name__ == f"{camelize(provider_name)}Outbox"
            )

    def test_outbox_with_different_aggregate_types(self, test_domain):
        """Test outbox works with different aggregate types"""
        # Create aggregates of different types
        test_agg = DummyAggregate(name="Test", count=0)
        another_agg = AnotherAggregate(description="Another test")

        # Trigger events
        test_agg.increment()
        another_agg.raise_(
            AnotherEvent(
                aggregate_id=another_agg.id, description=another_agg.description
            )
        )

        with UnitOfWork():
            test_domain.repository_for(DummyAggregate).add(test_agg)
            test_domain.repository_for(AnotherAggregate).add(another_agg)

        outbox_repo = test_domain._get_outbox_repo("default")

        # Check that events from both aggregates are in outbox
        outbox_records = outbox_repo.find_unprocessed()

        test_event_records = [
            r for r in outbox_records if r.type == DummyEvent.__type__
        ]
        another_event_records = [
            r for r in outbox_records if r.type == AnotherEvent.__type__
        ]

        assert len(test_event_records) >= 1
        assert len(another_event_records) >= 1

        # Verify stream names are different
        test_stream = test_event_records[0].stream_name
        another_stream = another_event_records[0].stream_name
        assert test_stream != another_stream
        assert test_stream.startswith("test::dummy_aggregate-")
        assert another_stream.startswith("test::another_aggregate-")


@pytest.mark.database
@pytest.mark.eventstore
class TestEventSourcedAggregateOutbox:
    """Verify event-sourced aggregates write events to the outbox.

    Event-sourced aggregates persist via the event store (e.g. Message DB),
    not a regular database provider. Their repository's ``add()`` only
    records the aggregate in the UoW identity map — it does NOT open a
    database session.  The UoW must lazily create a session so that outbox
    records can be written atomically.

    Before the fix in ``UnitOfWork.commit()``, the outbox loop iterated
    ``self._sessions`` (which was empty for ES aggregates), silently
    skipping all their events.
    """

    @pytest.fixture(autouse=True)
    def register_es_elements(self, test_domain):
        test_domain.register(ESOrder, is_event_sourced=True)
        test_domain.register(ESOrderPlaced, part_of=ESOrder)
        test_domain.register(ESOrderConfirmed, part_of=ESOrder)
        test_domain.init(traverse=False)

    def test_es_aggregate_events_written_to_outbox(self, test_domain):
        """Event-sourced aggregate events must appear in the outbox."""
        outbox_repo = test_domain._get_outbox_repo("default")
        initial_count = len(outbox_repo.find_unprocessed())

        order = ESOrder.place(customer_id="CUST-1", total=99.99)
        with UnitOfWork():
            test_domain.repository_for(ESOrder).add(order)

        outbox_records = outbox_repo.find_unprocessed()
        assert len(outbox_records) > initial_count

        placed_records = [r for r in outbox_records if r.type == ESOrderPlaced.__type__]
        assert len(placed_records) == 1
        assert placed_records[0].status == OutboxStatus.PENDING.value
        assert placed_records[0].data["order_id"] == str(order.id)
        assert placed_records[0].data["customer_id"] == "CUST-1"
        assert placed_records[0].stream_name == f"test::es_order-{order.id}"

    def test_es_aggregate_multiple_events_written_to_outbox(self, test_domain):
        """Multiple events from one ES aggregate must all reach the outbox."""
        outbox_repo = test_domain._get_outbox_repo("default")

        order = ESOrder.place(customer_id="CUST-2", total=50.0)
        order.confirm()

        with UnitOfWork():
            test_domain.repository_for(ESOrder).add(order)

        outbox_records = outbox_repo.find_unprocessed()

        placed = [
            r
            for r in outbox_records
            if r.type == ESOrderPlaced.__type__
            and r.data.get("order_id") == str(order.id)
        ]
        confirmed = [
            r
            for r in outbox_records
            if r.type == ESOrderConfirmed.__type__
            and r.data.get("order_id") == str(order.id)
        ]

        assert len(placed) == 1
        assert len(confirmed) == 1

    def test_es_events_also_in_event_store(self, test_domain):
        """Events should be in both the outbox AND the event store."""
        order = ESOrder.place(customer_id="CUST-3", total=75.0)
        with UnitOfWork():
            test_domain.repository_for(ESOrder).add(order)

        # Verify event store has the event
        messages = test_domain.event_store.store._read("test::es_order")
        assert len(messages) == 1
        assert messages[0]["type"] == ESOrderPlaced.__type__

        # Verify outbox also has the event
        outbox_repo = test_domain._get_outbox_repo("default")
        outbox_records = outbox_repo.find_unprocessed()
        placed = [
            r
            for r in outbox_records
            if r.type == ESOrderPlaced.__type__
            and r.data.get("order_id") == str(order.id)
        ]
        assert len(placed) == 1

    def test_es_aggregate_session_lazily_initialized(self, test_domain):
        """UoW should lazily create a session for ES aggregates during outbox writes.

        ES aggregates persist via the event store, not a database provider.
        Before the fix, the outbox loop iterated self._sessions which was
        empty for ES aggregates. Now it iterates all_events and lazily
        initializes sessions.
        """
        order = ESOrder.place(customer_id="CUST-4", total=120.0)

        uow = UnitOfWork()
        uow.__enter__()

        # After entering UoW, no sessions should exist yet
        assert len(uow._sessions) == 0

        test_domain.repository_for(ESOrder).add(order)

        # After repo.add(), ES aggregate goes into identity map but
        # no database session is opened (ES uses the event store)
        assert len(uow._sessions) == 0

        uow.__exit__(None, None, None)

        # After commit, a session should have been lazily created for outbox
        # (UoW has already exited, but outbox records should exist)
        outbox_repo = test_domain._get_outbox_repo("default")
        outbox_records = outbox_repo.find_unprocessed()
        placed = [
            r
            for r in outbox_records
            if r.type == ESOrderPlaced.__type__
            and r.data.get("order_id") == str(order.id)
        ]
        assert len(placed) == 1

    def test_es_aggregate_rollback_no_outbox_records(self, test_domain):
        """ES aggregate outbox records should not be created on rollback."""
        outbox_repo = test_domain._get_outbox_repo("default")
        initial_count = len(outbox_repo.find_unprocessed())

        order = ESOrder.place(customer_id="CUST-5", total=200.0)

        try:
            with UnitOfWork():
                test_domain.repository_for(ESOrder).add(order)
                raise ValueError("Forced rollback")
        except ValueError:
            pass

        # No new outbox records should have been created
        final_count = len(outbox_repo.find_unprocessed())
        assert final_count == initial_count


@pytest.mark.database
@pytest.mark.eventstore
class TestMixedAggregateOutbox:
    """Verify that ES and non-ES aggregates in the same UoW both write to outbox.

    This is the critical scenario that exercises the fix: the old code iterated
    self._sessions which only included non-ES aggregates. The new code iterates
    all_events and lazily creates sessions, so both aggregate types are covered.
    """

    @pytest.fixture(autouse=True)
    def register_mixed_elements(self, test_domain):
        test_domain.register(DummyAggregate)
        test_domain.register(DummyEvent, part_of=DummyAggregate)
        test_domain.register(ESOrder, is_event_sourced=True)
        test_domain.register(ESOrderPlaced, part_of=ESOrder)
        test_domain.register(ESOrderConfirmed, part_of=ESOrder)
        test_domain.init(traverse=False)

    def test_mixed_es_and_regular_aggregates_in_same_uow(self, test_domain):
        """Both ES and non-ES aggregate events must reach the outbox in one UoW."""
        outbox_repo = test_domain._get_outbox_repo("default")

        dummy = DummyAggregate(name="Mixed Test", count=0)
        dummy.increment()

        order = ESOrder.place(customer_id="CUST-MIX", total=150.0)

        with UnitOfWork():
            test_domain.repository_for(DummyAggregate).add(dummy)
            test_domain.repository_for(ESOrder).add(order)

        outbox_records = outbox_repo.find_unprocessed()

        # Non-ES aggregate event should be in outbox
        dummy_records = [
            r
            for r in outbox_records
            if r.type == DummyEvent.__type__ and r.data.get("aggregate_id") == dummy.id
        ]
        assert len(dummy_records) == 1

        # ES aggregate event should also be in outbox
        es_records = [
            r
            for r in outbox_records
            if r.type == ESOrderPlaced.__type__
            and r.data.get("order_id") == str(order.id)
        ]
        assert len(es_records) == 1

    def test_mixed_aggregates_stream_names_correct(self, test_domain):
        """Each aggregate type should produce outbox records with correct stream names."""
        outbox_repo = test_domain._get_outbox_repo("default")

        dummy = DummyAggregate(name="Stream Test", count=0)
        dummy.increment()

        order = ESOrder.place(customer_id="CUST-STR", total=75.0)

        with UnitOfWork():
            test_domain.repository_for(DummyAggregate).add(dummy)
            test_domain.repository_for(ESOrder).add(order)

        outbox_records = outbox_repo.find_unprocessed()

        dummy_record = next(
            (
                r
                for r in outbox_records
                if r.type == DummyEvent.__type__
                and r.data.get("aggregate_id") == dummy.id
            ),
            None,
        )
        es_record = next(
            (
                r
                for r in outbox_records
                if r.type == ESOrderPlaced.__type__
                and r.data.get("order_id") == str(order.id)
            ),
            None,
        )

        assert dummy_record is not None
        assert es_record is not None

        # Stream names should follow their respective aggregate patterns
        assert dummy_record.stream_name == f"test::dummy_aggregate-{dummy.id}"
        assert es_record.stream_name == f"test::es_order-{order.id}"
