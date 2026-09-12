"""Loading an event-sourced aggregate whose snapshot predates the current schema.

A snapshot is written straight from the aggregate's serialized state, with no
version and no upcaster path (see ``BaseEventStore._load_aggregate_current`` and
``create_snapshot``). Change the aggregate's fields (rename one, remove one, add
a newly required one) and a snapshot written before the change no longer
constructs: Pydantic ``extra="forbid"`` rejects the stale key or the missing
required field surfaces as a ``ValidationError``.

A snapshot is a rebuildable cache over the authoritative event stream, so the
load path treats a stale snapshot as a cache miss: it discards the snapshot,
replays the events, and logs a WARNING on ``protean.snapshot`` so an operator
knows to rebuild snapshots. A snapshot that still matches the schema keeps the
fast path and is not replayed from the beginning.
"""

import logging
from enum import Enum
from unittest.mock import patch
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
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


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(UserRegistered, part_of=User)
    test_domain.register(UserActivated, part_of=User)
    test_domain.register(UserRenamed, part_of=User)
    test_domain.init(traverse=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot_stream(identifier):
    return f"test::user:snapshot-{identifier}"


def _aggregate_stream(identifier):
    return f"test::user-{identifier}"


def _register_and_snapshot(test_domain, identifier, *, extra_events=0):
    """Persist a User (register + activate + ``extra_events`` renames) and write
    a valid snapshot. Return the store and the valid snapshot payload."""
    repo = test_domain.repository_for(User)
    with UnitOfWork():
        user = User.register(
            user_id=identifier, name="John Doe", email="john@example.com"
        )
        user.activate()
        repo.add(user)

    for i in range(extra_events):
        with UnitOfWork():
            user = repo.get(identifier)
            user.change_name(f"John Doe {i}")
            repo.add(user)

    test_domain.create_snapshot(User, identifier)
    store = test_domain.event_store.store
    snapshot = store._read_last_message(_snapshot_stream(identifier))
    assert snapshot is not None, "Precondition: a valid snapshot must exist"
    return store, snapshot["data"]


def _write_stale_snapshot(store, identifier, data):
    """Overwrite the snapshot stream with a payload the current schema rejects.

    ``_read_last_message`` returns the newest snapshot row, so this drifted row
    is the one the load path reads.
    """
    store._write(_snapshot_stream(identifier), "SNAPSHOT", data)


def _discard_records(caplog, identifier):
    """The ``snapshot_discarded`` warnings on ``protean.snapshot`` for this id."""
    return [
        r
        for r in caplog.records
        if r.name == "protean.snapshot"
        and r.getMessage() == "snapshot_discarded"
        and getattr(r, "aggregate_id", None) == identifier
    ]


# ---------------------------------------------------------------------------
# Positive: a stale snapshot is discarded and the aggregate still loads
# ---------------------------------------------------------------------------


class TestStaleSnapshotRecovers:
    @pytest.mark.eventstore
    def test_removed_field_loads_by_replay(self, test_domain, caplog):
        """A field the class no longer declares is rejected by ``extra="forbid"``;
        the aggregate loads correctly by replaying events."""
        identifier = str(uuid4())
        store, data = _register_and_snapshot(test_domain, identifier)
        _write_stale_snapshot(store, identifier, {**data, "obsolete_field": "x"})

        with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
            user = store.load_aggregate(User, identifier)

        assert user is not None
        assert user.name == "John Doe"
        assert user.email == "john@example.com"
        assert user.status == "ACTIVE"
        assert len(_discard_records(caplog, identifier)) == 1

    @pytest.mark.eventstore
    def test_renamed_field_loads_by_replay(self, test_domain, caplog):
        """The snapshot carries the old key and misses the new one, so both a
        missing required field and an unknown key surface as a ValidationError."""
        identifier = str(uuid4())
        store, data = _register_and_snapshot(test_domain, identifier)
        renamed = {k: v for k, v in data.items() if k != "name"}
        renamed["full_name"] = data["name"]
        _write_stale_snapshot(store, identifier, renamed)

        with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
            user = store.load_aggregate(User, identifier)

        assert user is not None
        assert user.name == "John Doe"
        assert len(_discard_records(caplog, identifier)) == 1

    @pytest.mark.eventstore
    def test_newly_required_field_loads_by_replay(self, test_domain, caplog):
        """A field the snapshot lacks but the class now requires surfaces as a
        ValidationError; the aggregate loads correctly by replaying events."""
        identifier = str(uuid4())
        store, data = _register_and_snapshot(test_domain, identifier)
        missing = {k: v for k, v in data.items() if k != "email"}
        _write_stale_snapshot(store, identifier, missing)

        with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
            user = store.load_aggregate(User, identifier)

        assert user is not None
        assert user.email == "john@example.com"
        assert len(_discard_records(caplog, identifier)) == 1

    @pytest.mark.eventstore
    def test_discard_record_names_the_aggregate_and_reason(self, test_domain, caplog):
        """The discard warning carries the aggregate name, identifier, and a
        reason string an operator can act on."""
        identifier = str(uuid4())
        store, data = _register_and_snapshot(test_domain, identifier)
        _write_stale_snapshot(store, identifier, {**data, "obsolete_field": "x"})

        with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
            store.load_aggregate(User, identifier)

        records = _discard_records(caplog, identifier)
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.WARNING
        assert record.aggregate == "User"
        assert record.reason  # a non-empty explanation of the mismatch

    @pytest.mark.eventstore
    def test_at_version_stale_snapshot_recovers(self, test_domain, caplog):
        """The temporal-query load path discards a stale snapshot too, replaying
        from the beginning up to the requested version."""
        identifier = str(uuid4())
        store, data = _register_and_snapshot(test_domain, identifier, extra_events=2)
        # The snapshot is usable for this query only when its version does not
        # exceed the requested version, so target exactly the snapshot version.
        snapshot_version = data["_version"]
        _write_stale_snapshot(store, identifier, {**data, "obsolete_field": "x"})

        with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
            user = store.load_aggregate(User, identifier, at_version=snapshot_version)

        assert user is not None
        assert user._version == snapshot_version
        assert len(_discard_records(caplog, identifier)) == 1

    @pytest.mark.eventstore
    def test_replay_includes_events_after_the_snapshot(self, test_domain, caplog):
        """Replay must start at the beginning of the stream, so events written
        after the snapshot are included. Reusing the discarded snapshot's
        position would drop them."""
        identifier = str(uuid4())
        store, data = _register_and_snapshot(test_domain, identifier)
        # A rename written AFTER the snapshot. Only a replay from position 0
        # reaches it; replaying from the snapshot version would miss it.
        repo = test_domain.repository_for(User)
        with UnitOfWork():
            user = repo.get(identifier)
            user.change_name("Jane Smith")
            repo.add(user)
        _write_stale_snapshot(store, identifier, {**data, "obsolete_field": "x"})

        with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
            loaded = store.load_aggregate(User, identifier)

        assert loaded is not None
        assert loaded.name == "Jane Smith"  # post-snapshot event applied
        assert loaded.email == "john@example.com"  # pre-snapshot event applied
        assert loaded.status == "ACTIVE"
        assert len(_discard_records(caplog, identifier)) == 1

    @pytest.mark.eventstore
    def test_at_version_replays_past_the_snapshot_version(self, test_domain, caplog):
        """The temporal replay after a discard must reach a version later than
        the discarded snapshot's, applying the events in between."""
        identifier = str(uuid4())
        repo = test_domain.repository_for(User)
        with UnitOfWork():
            user = User.register(
                user_id=identifier, name="John Doe", email="john@example.com"
            )
            user.activate()
            repo.add(user)
        # Snapshot at this version, then add later events so the snapshot is
        # intermediate rather than at the stream head.
        test_domain.create_snapshot(User, identifier)
        store = test_domain.event_store.store
        valid = store._read_last_message(_snapshot_stream(identifier))["data"]
        snapshot_version = valid["_version"]
        for i in range(3):
            with UnitOfWork():
                user = repo.get(identifier)
                user.change_name(f"Rename {i}")
                repo.add(user)

        _write_stale_snapshot(store, identifier, {**valid, "obsolete_field": "x"})
        target = snapshot_version + 2  # a version strictly after the snapshot

        with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
            user = store.load_aggregate(User, identifier, at_version=target)

        assert user is not None
        assert user._version == target
        assert len(_discard_records(caplog, identifier)) == 1

    @pytest.mark.eventstore
    def test_stale_snapshot_without_events_returns_none(self, test_domain, caplog):
        """A stale snapshot for an identifier with no event stream is discarded
        and the load returns None, the same as a missing aggregate."""
        identifier = str(uuid4())
        store = test_domain.event_store.store
        _write_stale_snapshot(
            store,
            identifier,
            {"user_id": identifier, "obsolete_field": "x", "_version": 0},
        )

        with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
            result = store.load_aggregate(User, identifier)

        assert result is None
        assert len(_discard_records(caplog, identifier)) == 1


# ---------------------------------------------------------------------------
# Negative: a valid snapshot is used, not discarded, and not fully replayed
# ---------------------------------------------------------------------------


class TestValidSnapshotKeepsFastPath:
    @pytest.mark.eventstore
    def test_valid_snapshot_not_discarded(self, test_domain, caplog):
        """A snapshot matching the current schema emits no discard warning."""
        identifier = str(uuid4())
        _register_and_snapshot(test_domain, identifier, extra_events=3)
        store = test_domain.event_store.store

        with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
            user = store.load_aggregate(User, identifier)

        assert user is not None
        assert _discard_records(caplog, identifier) == []

    @pytest.mark.eventstore
    def test_valid_snapshot_does_not_replay_whole_stream(self, test_domain):
        """A valid snapshot reads events from just after the snapshot version,
        not from position 0."""
        identifier = str(uuid4())
        _, data = _register_and_snapshot(test_domain, identifier, extra_events=3)
        store = test_domain.event_store.store
        snapshot_version = data["_version"]

        with patch.object(store, "_read", wraps=store._read) as spy:
            store.load_aggregate(User, identifier)

        aggregate_reads = [
            call
            for call in spy.call_args_list
            if call.args and call.args[0] == _aggregate_stream(identifier)
        ]
        assert len(aggregate_reads) == 1
        assert aggregate_reads[0].kwargs.get("position") == snapshot_version + 1


# ---------------------------------------------------------------------------
# Self-healing: a stale snapshot is rebuilt so the next load is clean
# ---------------------------------------------------------------------------


class TestStaleSnapshotSelfHeals:
    @pytest.mark.eventstore
    def test_next_load_uses_rebuilt_snapshot(self, test_domain, caplog):
        """After a stale snapshot is discarded and the event count meets the
        threshold, a fresh snapshot is written, so the next load does not discard."""
        identifier = str(uuid4())
        threshold = test_domain.config["snapshot_threshold"]
        store, data = _register_and_snapshot(
            test_domain, identifier, extra_events=threshold
        )
        _write_stale_snapshot(store, identifier, {**data, "obsolete_field": "x"})

        with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
            store.load_aggregate(User, identifier)
        assert len(_discard_records(caplog, identifier)) == 1

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
            user = store.load_aggregate(User, identifier)

        assert user is not None
        assert _discard_records(caplog, identifier) == []
        rebuilt = store._read_last_message(_snapshot_stream(identifier))
        assert "obsolete_field" not in rebuilt["data"]

    @pytest.mark.eventstore
    def test_below_threshold_rediscards_without_rebuilding(self, test_domain, caplog):
        """Below the snapshot threshold no fresh snapshot is written, so the
        stale row survives and every load re-discards and re-warns."""
        identifier = str(uuid4())
        # Two events, below the default threshold of 10.
        store, data = _register_and_snapshot(test_domain, identifier)
        _write_stale_snapshot(store, identifier, {**data, "obsolete_field": "x"})

        with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
            store.load_aggregate(User, identifier)
            store.load_aggregate(User, identifier)

        assert len(_discard_records(caplog, identifier)) == 2
        current = store._read_last_message(_snapshot_stream(identifier))
        assert "obsolete_field" in current["data"]  # the stale row was not rebuilt
