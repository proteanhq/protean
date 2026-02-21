"""Tests for manual snapshot creation on event-sourced aggregates."""

from enum import Enum
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import IncorrectUsageError, ObjectNotFoundError
from protean.fields import Identifier, String


class UserStatus(Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class UserRegistered(BaseEvent):
    user_id: Identifier(required=True)
    name: String(max_length=50, required=True)
    email: String(required=True)


class UserActivated(BaseEvent):
    user_id: Identifier(required=True)


class UserRenamed(BaseEvent):
    user_id: Identifier(required=True)
    name: String(required=True, max_length=50)


class User(BaseAggregate):
    user_id: Identifier(identifier=True)
    name: String(max_length=50, required=True)
    email: String(required=True)
    status: String(choices=UserStatus)

    @classmethod
    def register(cls, user_id, name, email):
        user = cls(user_id=user_id, name=name, email=email)
        user.raise_(UserRegistered(user_id=user_id, name=name, email=email))
        return user

    def activate(self):
        self.raise_(UserActivated(user_id=self.user_id))

    def change_name(self, name):
        self.raise_(UserRenamed(user_id=self.user_id, name=name))

    @apply
    def registered(self, event: UserRegistered):
        self.user_id = event.user_id
        self.name = event.name
        self.email = event.email
        self.status = UserStatus.INACTIVE.value

    @apply
    def activated(self, event: UserActivated):
        self.status = UserStatus.ACTIVE.value

    @apply
    def renamed(self, event: UserRenamed):
        self.name = event.name


# Non-event-sourced aggregate for negative tests
class Order(BaseAggregate):
    order_id: Identifier(identifier=True)
    total: String(max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.register(Order)
    test_domain.init(traverse=False)


class TestCreateSnapshot:
    """Tests for domain.create_snapshot() -- single aggregate instance."""

    @pytest.mark.eventstore
    def test_creates_snapshot_below_threshold(self, test_domain):
        """Manual snapshot works even when event count is below threshold."""
        identifier = str(uuid4())
        repo = test_domain.repository_for(User)

        with UnitOfWork():
            user = User.register(
                user_id=identifier, name="John Doe", email="john@example.com"
            )
            user.activate()
            repo.add(user)

        # Only 2 events, well below default threshold of 10
        result = test_domain.create_snapshot(User, identifier)
        assert result is True

        snapshot = test_domain.event_store.store._read_last_message(
            f"test::user:snapshot-{identifier}"
        )
        assert snapshot is not None
        assert snapshot["data"]["name"] == "John Doe"
        assert snapshot["data"]["status"] == "ACTIVE"

    @pytest.mark.eventstore
    def test_snapshot_reflects_current_state(self, test_domain):
        """Snapshot captures the latest aggregate state after mutations."""
        identifier = str(uuid4())
        repo = test_domain.repository_for(User)

        with UnitOfWork():
            user = User.register(
                user_id=identifier, name="John Doe", email="john@example.com"
            )
            repo.add(user)

        with UnitOfWork():
            user = repo.get(identifier)
            user.change_name("Jane Smith")
            repo.add(user)

        test_domain.create_snapshot(User, identifier)

        snapshot = test_domain.event_store.store._read_last_message(
            f"test::user:snapshot-{identifier}"
        )
        assert snapshot["data"]["name"] == "Jane Smith"

    @pytest.mark.eventstore
    def test_forced_refresh_overwrites_existing_snapshot(self, test_domain):
        """Calling create_snapshot twice succeeds (forced refresh)."""
        identifier = str(uuid4())
        repo = test_domain.repository_for(User)

        with UnitOfWork():
            user = User.register(
                user_id=identifier, name="John Doe", email="john@example.com"
            )
            repo.add(user)

        result1 = test_domain.create_snapshot(User, identifier)
        assert result1 is True

        # Call again -- should succeed even if already at latest
        result2 = test_domain.create_snapshot(User, identifier)
        assert result2 is True

    @pytest.mark.eventstore
    def test_raises_for_nonexistent_aggregate(self, test_domain):
        with pytest.raises(ObjectNotFoundError):
            test_domain.create_snapshot(User, "nonexistent-id")

    @pytest.mark.eventstore
    def test_raises_for_non_event_sourced_aggregate(self, test_domain):
        with pytest.raises(IncorrectUsageError, match="not an event-sourced"):
            test_domain.create_snapshot(Order, "some-id")

    @pytest.mark.eventstore
    def test_raises_for_unregistered_aggregate(self, test_domain):
        class UnregisteredAggregate(BaseAggregate):
            pass

        with pytest.raises(IncorrectUsageError, match="not registered"):
            test_domain.create_snapshot(UnregisteredAggregate, "some-id")

    @pytest.mark.eventstore
    def test_aggregate_loads_correctly_from_manual_snapshot(self, test_domain):
        """After manual snapshot, repo.get() uses it for reconstruction."""
        identifier = str(uuid4())
        repo = test_domain.repository_for(User)

        with UnitOfWork():
            user = User.register(
                user_id=identifier, name="John Doe", email="john@example.com"
            )
            user.activate()
            repo.add(user)

        test_domain.create_snapshot(User, identifier)

        # Load aggregate -- should use the snapshot
        loaded_user = repo.get(identifier)
        assert loaded_user.name == "John Doe"
        assert loaded_user.status == "ACTIVE"
        assert loaded_user._version == 1


class TestStreamIdentifiers:
    """Tests for event store _stream_identifiers()."""

    @pytest.mark.eventstore
    def test_returns_empty_when_no_events(self, test_domain):
        identifiers = test_domain.event_store.store._stream_identifiers("test::user")
        assert identifiers == []

    @pytest.mark.eventstore
    def test_returns_unique_identifiers(self, test_domain):
        repo = test_domain.repository_for(User)
        ids = []
        for _ in range(3):
            uid = str(uuid4())
            ids.append(uid)
            with UnitOfWork():
                user = User.register(user_id=uid, name="User", email="u@example.com")
                repo.add(user)

        identifiers = test_domain.event_store.store._stream_identifiers("test::user")
        assert sorted(identifiers) == sorted(ids)

    @pytest.mark.eventstore
    def test_deduplicates_across_multiple_events(self, test_domain):
        """Multiple events for same aggregate yield one identifier."""
        identifier = str(uuid4())
        repo = test_domain.repository_for(User)

        with UnitOfWork():
            user = User.register(user_id=identifier, name="John", email="j@example.com")
            user.activate()
            repo.add(user)

        identifiers = test_domain.event_store.store._stream_identifiers("test::user")
        assert identifiers == [identifier]

    @pytest.mark.eventstore
    def test_skips_malformed_stream_names(self, test_domain):
        """Stream names without a valid identifier part are ignored."""
        identifier = str(uuid4())
        repo = test_domain.repository_for(User)

        with UnitOfWork():
            user = User.register(user_id=identifier, name="John", email="j@example.com")
            repo.add(user)

        # Write a raw message with a malformed stream name (trailing dash,
        # no identifier) to exercise the guard in _stream_identifiers.
        test_domain.event_store.store._write("test::user-", "SomeType", {"key": "val"})

        identifiers = test_domain.event_store.store._stream_identifiers("test::user")
        # Only the valid identifier should appear
        assert identifiers == [identifier]


class TestCreateSnapshots:
    """Tests for domain.create_snapshots() -- bulk per aggregate."""

    @pytest.mark.eventstore
    def test_creates_snapshots_for_all_instances(self, test_domain):
        repo = test_domain.repository_for(User)
        ids = []
        for _ in range(3):
            uid = str(uuid4())
            ids.append(uid)
            with UnitOfWork():
                user = User.register(user_id=uid, name="User", email="u@example.com")
                repo.add(user)

        count = test_domain.create_snapshots(User)
        assert count == 3

        for uid in ids:
            snapshot = test_domain.event_store.store._read_last_message(
                f"test::user:snapshot-{uid}"
            )
            assert snapshot is not None

    @pytest.mark.eventstore
    def test_returns_zero_for_no_instances(self, test_domain):
        count = test_domain.create_snapshots(User)
        assert count == 0

    @pytest.mark.eventstore
    def test_raises_for_non_event_sourced(self, test_domain):
        with pytest.raises(IncorrectUsageError, match="not an event-sourced"):
            test_domain.create_snapshots(Order)

    @pytest.mark.eventstore
    def test_raises_for_unregistered_aggregate(self, test_domain):
        class UnregisteredAggregate(BaseAggregate):
            pass

        with pytest.raises(IncorrectUsageError, match="not registered"):
            test_domain.create_snapshots(UnregisteredAggregate)


class TestCreateAllSnapshots:
    """Tests for domain.create_all_snapshots() -- all ES aggregates."""

    @pytest.mark.eventstore
    def test_creates_snapshots_for_all_es_aggregates(self, test_domain):
        repo = test_domain.repository_for(User)
        identifier = str(uuid4())

        with UnitOfWork():
            user = User.register(
                user_id=identifier, name="John Doe", email="john@example.com"
            )
            repo.add(user)

        results = test_domain.create_all_snapshots()
        assert "User" in results
        assert results["User"] == 1

    @pytest.mark.eventstore
    def test_excludes_non_es_aggregates(self, test_domain):
        results = test_domain.create_all_snapshots()
        assert "Order" not in results

    @pytest.mark.eventstore
    def test_returns_empty_dict_when_no_instances(self, test_domain):
        results = test_domain.create_all_snapshots()
        # User is event-sourced but has no instances, so count is 0
        assert results == {"User": 0}
