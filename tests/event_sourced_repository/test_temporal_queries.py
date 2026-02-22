"""Tests for temporal queries — ``repo.get(id, at_version=N)`` and
``repo.get(id, as_of=timestamp)``.

Temporal queries reconstitute an event-sourced aggregate at a historical
point in time.  The returned aggregate is read-only: calling ``raise_()``
on it raises ``IncorrectUsageError``.
"""

import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import IncorrectUsageError, ObjectNotFoundError
from protean.fields import Identifier, String
from protean.fields.basic import Boolean
from protean.port.event_store import BaseEventStore
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Domain elements
# ---------------------------------------------------------------------------


class Register(BaseCommand):
    user_id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class ChangeAddress(BaseCommand):
    user_id = Identifier()
    address = String()


class ChangeName(BaseCommand):
    user_id = Identifier()
    name = String()


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class AddressChanged(BaseEvent):
    user_id = Identifier()
    address = String()


class NameChanged(BaseEvent):
    user_id = Identifier()
    name = String()


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()
    password_hash = String()
    address = String()

    is_registered = Boolean()

    @classmethod
    def register(cls, command: Register) -> "User":
        user = cls(
            user_id=command.user_id,
            email=command.email,
            name=command.name,
            password_hash=command.password_hash,
        )
        user.raise_(
            Registered(
                user_id=command.user_id,
                email=command.email,
                name=command.name,
                password_hash=command.password_hash,
            )
        )
        return user

    def change_address(self, address: str) -> None:
        self.raise_(AddressChanged(user_id=self.user_id, address=address))

    def change_name(self, name: str) -> None:
        self.raise_(NameChanged(user_id=self.user_id, name=name))

    @apply
    def registered(self, event: Registered) -> None:
        self.user_id = event.user_id
        self.email = event.email
        self.name = event.name
        self.password_hash = event.password_hash
        self.is_registered = True

    @apply
    def address_changed(self, event: AddressChanged) -> None:
        self.address = event.address

    @apply
    def name_changed(self, event: NameChanged) -> None:
        self.name = event.name


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register_user(self, command: Register) -> None:
        user = User.register(command)
        current_domain.repository_for(User).add(user)

    @handle(ChangeAddress)
    def change_address(self, command: ChangeAddress) -> None:
        user_repo = current_domain.repository_for(User)
        user = user_repo.get(command.user_id)
        user.change_address(command.address)
        user_repo.add(user)

    @handle(ChangeName)
    def change_name(self, command: ChangeName) -> None:
        user_repo = current_domain.repository_for(User)
        user = user_repo.get(command.user_id)
        user.change_name(command.name)
        user_repo.add(user)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(ChangeAddress, part_of=User)
    test_domain.register(AddressChanged, part_of=User)
    test_domain.register(ChangeName, part_of=User)
    test_domain.register(NameChanged, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Helper to create a user with multiple events
# ---------------------------------------------------------------------------


def _create_user_with_events(identifier: str) -> None:
    """Create a user and apply three events: Register, ChangeAddress, ChangeName.

    After this, the aggregate has version 2 (events at positions 0, 1, 2).
    """
    UserCommandHandler().register_user(
        Register(
            user_id=identifier,
            email="john@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )
    UserCommandHandler().change_address(
        ChangeAddress(user_id=identifier, address="123 Main St")
    )
    UserCommandHandler().change_name(ChangeName(user_id=identifier, name="Jane Doe"))


# ===========================================================================
# at_version tests
# ===========================================================================


class TestGetAtVersion:
    """Tests for ``repo.get(id, at_version=N)``."""

    @pytest.mark.eventstore
    def test_get_at_version_zero(self):
        """Version 0 = state after the first event only."""
        identifier = str(uuid4())
        _create_user_with_events(identifier)

        user = current_domain.repository_for(User).get(identifier, at_version=0)

        assert user._version == 0
        assert user.name == "John Doe"
        assert user.email == "john@example.com"
        assert user.is_registered is True
        # Fields from later events should not be set
        assert user.address is None

    @pytest.mark.eventstore
    def test_get_at_version_intermediate(self):
        """Version 1 = state after two events (Register + ChangeAddress)."""
        identifier = str(uuid4())
        _create_user_with_events(identifier)

        user = current_domain.repository_for(User).get(identifier, at_version=1)

        assert user._version == 1
        assert user.name == "John Doe"  # Not yet renamed
        assert user.address == "123 Main St"
        assert user.is_registered is True

    @pytest.mark.eventstore
    def test_get_at_version_latest(self):
        """Getting at the latest version matches a normal ``get()``."""
        identifier = str(uuid4())
        _create_user_with_events(identifier)

        repo = current_domain.repository_for(User)
        user_current = repo.get(identifier)
        user_at_latest = repo.get(identifier, at_version=user_current._version)

        assert user_at_latest._version == user_current._version
        assert user_at_latest.name == user_current.name
        assert user_at_latest.address == user_current.address

    @pytest.mark.eventstore
    def test_get_at_version_too_high(self):
        """Requesting a version beyond the stream raises ObjectNotFoundError."""
        identifier = str(uuid4())
        _create_user_with_events(identifier)  # latest version = 2

        with pytest.raises(ObjectNotFoundError) as exc:
            current_domain.repository_for(User).get(identifier, at_version=100)

        assert "does not have version 100" in str(exc.value)
        assert "Latest version is 2" in str(exc.value)

    @pytest.mark.eventstore
    def test_get_at_version_nonexistent_aggregate(self):
        """Non-existent aggregate raises ObjectNotFoundError."""
        with pytest.raises(ObjectNotFoundError):
            current_domain.repository_for(User).get("nonexistent-id", at_version=0)

    @pytest.mark.eventstore
    def test_get_at_version_single_event(self):
        """Works with an aggregate that has only one event."""
        identifier = str(uuid4())
        UserCommandHandler().register_user(
            Register(
                user_id=identifier,
                email="solo@example.com",
                name="Solo User",
                password_hash="hash",
            )
        )

        user = current_domain.repository_for(User).get(identifier, at_version=0)

        assert user._version == 0
        assert user.name == "Solo User"
        assert user.is_registered is True


class TestGetAtVersionWithSnapshots:
    """Tests for at_version interacting with the snapshot mechanism."""

    @pytest.mark.eventstore
    def test_get_at_version_uses_snapshot_when_helpful(self, test_domain):
        """When a snapshot exists at version <= requested, it is leveraged."""
        identifier = str(uuid4())
        repo = current_domain.repository_for(User)

        # Create user and enough events to trigger a snapshot
        UserCommandHandler().register_user(
            Register(
                user_id=identifier,
                email="snap@example.com",
                name="Snap User",
                password_hash="hash",
            )
        )
        for i in range(test_domain.config["snapshot_threshold"] + 1):
            UserCommandHandler().change_name(
                ChangeName(user_id=identifier, name=f"Name {i}")
            )

        # Verify a snapshot was created
        snapshot = test_domain.event_store.store._read_last_message(
            f"test::user:snapshot-{identifier}"
        )
        assert snapshot is not None

        # Request the latest version — should use snapshot
        latest_user = repo.get(identifier)
        user_at_version = repo.get(identifier, at_version=latest_user._version)

        assert user_at_version._version == latest_user._version
        assert user_at_version.name == latest_user.name

    @pytest.mark.eventstore
    def test_get_at_version_before_snapshot(self, test_domain):
        """When requested version < snapshot version, snapshot is skipped."""
        identifier = str(uuid4())
        repo = current_domain.repository_for(User)

        UserCommandHandler().register_user(
            Register(
                user_id=identifier,
                email="snap@example.com",
                name="Original Name",
                password_hash="hash",
            )
        )
        for i in range(test_domain.config["snapshot_threshold"] + 1):
            UserCommandHandler().change_name(
                ChangeName(user_id=identifier, name=f"Name {i}")
            )

        # Verify snapshot exists
        snapshot = test_domain.event_store.store._read_last_message(
            f"test::user:snapshot-{identifier}"
        )
        assert snapshot is not None

        # Request version 0 — before the snapshot
        user_v0 = repo.get(identifier, at_version=0)

        assert user_v0._version == 0
        assert user_v0.name == "Original Name"


# ===========================================================================
# as_of tests
# ===========================================================================


class TestGetAsOf:
    """Tests for ``repo.get(id, as_of=timestamp)``."""

    @pytest.mark.eventstore
    def test_get_as_of_after_all_events(self):
        """Timestamp after all events returns the full current state."""
        identifier = str(uuid4())
        _create_user_with_events(identifier)

        future = datetime.now(UTC) + timedelta(hours=1)
        user = current_domain.repository_for(User).get(identifier, as_of=future)

        assert user.name == "Jane Doe"
        assert user.address == "123 Main St"
        assert user.is_registered is True
        assert user._version == 2

    @pytest.mark.eventstore
    def test_get_as_of_between_events(self):
        """Timestamp between events returns state at that point in time."""
        identifier = str(uuid4())

        # Event 1: Register
        UserCommandHandler().register_user(
            Register(
                user_id=identifier,
                email="john@example.com",
                name="John Doe",
                password_hash="hash",
            )
        )

        # Record timestamp after first event
        time.sleep(0.05)  # Small delay to ensure distinct timestamps
        cutoff = datetime.now(UTC)
        time.sleep(0.05)

        # Event 2: ChangeAddress (after cutoff)
        UserCommandHandler().change_address(
            ChangeAddress(user_id=identifier, address="123 Main St")
        )

        user = current_domain.repository_for(User).get(identifier, as_of=cutoff)

        assert user._version == 0
        assert user.name == "John Doe"
        assert user.is_registered is True
        assert user.address is None  # Address change was after cutoff

    @pytest.mark.eventstore
    def test_get_as_of_before_first_event(self):
        """Timestamp before the first event raises ObjectNotFoundError."""
        identifier = str(uuid4())
        past = datetime.now(UTC) - timedelta(hours=1)

        _create_user_with_events(identifier)

        with pytest.raises(ObjectNotFoundError) as exc:
            current_domain.repository_for(User).get(identifier, as_of=past)

        assert "has no events on or before" in str(exc.value)

    @pytest.mark.eventstore
    def test_get_as_of_nonexistent_aggregate(self):
        """Non-existent aggregate returns ObjectNotFoundError."""
        future = datetime.now(UTC) + timedelta(hours=1)

        with pytest.raises(ObjectNotFoundError):
            current_domain.repository_for(User).get("nonexistent-id", as_of=future)

    @pytest.mark.eventstore
    def test_get_as_of_with_multiple_cutoffs(self):
        """Multiple as_of queries at different times return correct states."""
        identifier = str(uuid4())

        UserCommandHandler().register_user(
            Register(
                user_id=identifier,
                email="john@example.com",
                name="John Doe",
                password_hash="hash",
            )
        )
        time.sleep(0.05)
        after_register = datetime.now(UTC)
        time.sleep(0.05)

        UserCommandHandler().change_address(
            ChangeAddress(user_id=identifier, address="123 Main St")
        )
        time.sleep(0.05)
        after_address = datetime.now(UTC)
        time.sleep(0.05)

        UserCommandHandler().change_name(
            ChangeName(user_id=identifier, name="Jane Doe")
        )

        repo = current_domain.repository_for(User)

        # After register only
        user_t1 = repo.get(identifier, as_of=after_register)
        assert user_t1._version == 0
        assert user_t1.name == "John Doe"
        assert user_t1.address is None

        # After address change
        user_t2 = repo.get(identifier, as_of=after_address)
        assert user_t2._version == 1
        assert user_t2.name == "John Doe"
        assert user_t2.address == "123 Main St"

    @pytest.mark.eventstore
    def test_get_as_of_bypasses_snapshot(self, test_domain):
        """as_of queries skip snapshots and replay from events."""
        identifier = str(uuid4())

        UserCommandHandler().register_user(
            Register(
                user_id=identifier,
                email="snap@example.com",
                name="Original Name",
                password_hash="hash",
            )
        )

        time.sleep(0.05)
        after_register = datetime.now(UTC)
        time.sleep(0.05)

        for i in range(test_domain.config["snapshot_threshold"] + 1):
            UserCommandHandler().change_name(
                ChangeName(user_id=identifier, name=f"Name {i}")
            )

        # Verify snapshot exists
        snapshot = test_domain.event_store.store._read_last_message(
            f"test::user:snapshot-{identifier}"
        )
        assert snapshot is not None

        # as_of before all the name changes — should get original
        user = current_domain.repository_for(User).get(identifier, as_of=after_register)
        assert user.name == "Original Name"
        assert user._version == 0


# ===========================================================================
# Error handling and safety tests
# ===========================================================================


class TestTemporalErrorsAndSafety:
    """Tests for mutual exclusivity, read-only guard, and identity map bypass."""

    @pytest.mark.eventstore
    def test_both_params_raises(self):
        """Providing both at_version and as_of raises IncorrectUsageError."""
        identifier = str(uuid4())
        _create_user_with_events(identifier)

        with pytest.raises(IncorrectUsageError) as exc:
            current_domain.repository_for(User).get(
                identifier,
                at_version=0,
                as_of=datetime.now(UTC),
            )

        assert "mutually exclusive" in str(exc.value)

    @pytest.mark.eventstore
    def test_temporal_aggregate_is_read_only(self):
        """Calling raise_() on a temporal aggregate raises IncorrectUsageError."""
        identifier = str(uuid4())
        _create_user_with_events(identifier)

        user = current_domain.repository_for(User).get(identifier, at_version=0)

        assert user._is_temporal is True

        with pytest.raises(IncorrectUsageError) as exc:
            user.raise_(NameChanged(user_id=user.user_id, name="New Name"))

        assert "read-only" in str(exc.value)

    @pytest.mark.eventstore
    def test_temporal_aggregate_is_temporal_flag_set(self):
        """Temporal aggregates have ``_is_temporal`` set to True."""
        identifier = str(uuid4())
        _create_user_with_events(identifier)

        user_version = current_domain.repository_for(User).get(identifier, at_version=1)
        assert user_version._is_temporal is True

        user_as_of = current_domain.repository_for(User).get(
            identifier, as_of=datetime.now(UTC) + timedelta(hours=1)
        )
        assert user_as_of._is_temporal is True

    @pytest.mark.eventstore
    def test_normal_get_is_not_temporal(self):
        """Normal ``get()`` does not set ``_is_temporal``."""
        identifier = str(uuid4())
        _create_user_with_events(identifier)

        user = current_domain.repository_for(User).get(identifier)
        assert user._is_temporal is False

    @pytest.mark.eventstore
    def test_temporal_bypasses_identity_map(self):
        """Temporal queries bypass the UoW identity map."""
        identifier = str(uuid4())
        _create_user_with_events(identifier)

        with UnitOfWork():
            repo = current_domain.repository_for(User)

            # Load current version into UoW identity map
            user_current = repo.get(identifier)
            assert user_current._version == 2
            assert user_current.name == "Jane Doe"

            # Temporal query should bypass the identity map
            user_v0 = repo.get(identifier, at_version=0)
            assert user_v0._version == 0
            assert user_v0.name == "John Doe"

            # The current user in the identity map is unchanged
            user_again = repo.get(identifier)
            assert user_again._version == 2
            assert user_again.name == "Jane Doe"


# ===========================================================================
# Unit tests for helper methods
# ===========================================================================


class TestParseEventTime:
    """Tests for ``BaseEventStore._parse_event_time``."""

    def test_none_returns_none(self):
        assert BaseEventStore._parse_event_time(None) is None

    def test_datetime_passthrough(self):
        now = datetime.now(UTC)
        assert BaseEventStore._parse_event_time(now) is now

    def test_iso_string_parsed(self):
        dt = datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC)
        result = BaseEventStore._parse_event_time(dt.isoformat())
        assert result == dt

    def test_unexpected_type_returns_none(self):
        assert BaseEventStore._parse_event_time(12345) is None


class TestGetAtVersionSnapshotExact:
    """Cover the branch where a snapshot is at exactly the requested version."""

    @pytest.mark.eventstore
    def test_snapshot_at_exact_requested_version(self, test_domain):
        """When the snapshot version equals at_version, no extra events are replayed."""
        identifier = str(uuid4())
        repo = current_domain.repository_for(User)

        # Create initial event
        UserCommandHandler().register_user(
            Register(
                user_id=identifier,
                email="snap@example.com",
                name="Snap User",
                password_hash="hash",
            )
        )
        # Generate enough events to trigger a snapshot
        threshold = test_domain.config["snapshot_threshold"]
        for i in range(threshold):
            UserCommandHandler().change_name(
                ChangeName(user_id=identifier, name=f"Name {i}")
            )

        # Verify a snapshot was created
        snapshot = test_domain.event_store.store._read_last_message(
            f"test::user:snapshot-{identifier}"
        )
        assert snapshot is not None
        snapshot_version = snapshot["data"]["_version"]

        # Request exactly the snapshot version — remaining == 0
        user = repo.get(identifier, at_version=snapshot_version)
        assert user._version == snapshot_version


class TestParseEventTimeEdgeCases:
    """Cover edge cases in ``_parse_event_time`` and ``as_of`` filtering."""

    @pytest.mark.eventstore
    def test_as_of_handles_events_with_string_timestamps(self):
        """Events with ISO-8601 string timestamps are parsed and compared correctly.

        This exercises the ``isinstance(raw_time, str)`` branch in ``_parse_event_time``
        via a full integration path — the memory adapter serializes ``time`` as a
        string in ``to_dict()``.
        """
        identifier = str(uuid4())

        UserCommandHandler().register_user(
            Register(
                user_id=identifier,
                email="john@example.com",
                name="John Doe",
                password_hash="hash",
            )
        )

        # The memory adapter stores time as a string (ISO-8601) in to_dict(),
        # which exercises the string-parsing branch of _parse_event_time
        future = datetime.now(UTC) + timedelta(hours=1)
        user = current_domain.repository_for(User).get(identifier, as_of=future)

        assert user._version == 0
        assert user.name == "John Doe"
