"""How the SQL event store appends: the version check, the lock and its errors."""

import threading
import time
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from protean.adapters.event_store.sql.store import _lock_key
from protean.exceptions import ExpectedVersionError

from .conftest import PG_SCHEMA, backend_config

WRITERS = 8


def race(write, count=WRITERS):
    """Start ``count`` writers at once and return what each returned or raised."""
    barrier = threading.Barrier(count)
    outcomes = [None] * count

    def run(index):
        barrier.wait()
        try:
            outcomes[index] = write(index)
        except Exception as exc:  # the outcome is the assertion
            outcomes[index] = exc

    threads = [threading.Thread(target=run, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    return outcomes


class TestExpectedVersionUnderConcurrency:
    def test_one_of_many_threads_appends_at_a_version(self, store):
        outcomes = race(
            lambda i: store.write_message("user-1", "Registered", {"i": i}, None, -1)
        )

        assert outcomes.count(0) == 1
        errors = [o for o in outcomes if o != 0]
        assert len(errors) == WRITERS - 1
        assert all(isinstance(e, ExpectedVersionError) for e in errors)
        assert len(store.get_stream_messages("user-1")) == 1

    def test_one_of_two_stores_on_one_database_appends_at_a_version(
        self, make_store, config
    ):
        stores = [make_store(config), make_store(config)]

        outcomes = race(
            lambda i: stores[i % 2].write_message("user-1", "Registered", {}, None, -1)
        )

        assert outcomes.count(0) == 1
        assert all(isinstance(o, ExpectedVersionError) for o in outcomes if o != 0)
        assert len(stores[0].get_stream_messages("user-1")) == 1

    def test_writers_without_a_version_get_every_position_once(self, store):
        outcomes = race(lambda i: store.write_message("user-1", "Counted", {"i": i}))

        assert sorted(outcomes) == list(range(WRITERS))
        rows = store.get_stream_messages("user-1")
        assert [row["position"] for row in rows] == list(range(WRITERS))

    def test_a_stale_version_names_the_stream_version(self, store):
        store.write_message("user-1", "Registered", {})

        with pytest.raises(
            ExpectedVersionError,
            match=r"Wrong expected version: 3 \(Stream: user-1, Stream Version: 0\)",
        ):
            store.write_message("user-1", "Renamed", {}, None, expected_version=3)


class TestInterruptedWrite:
    def test_a_write_that_fails_under_the_lock_releases_it(self, store, monkeypatch):
        def fail():
            raise RuntimeError("interrupted")

        monkeypatch.setattr(store, "_on_lock_taken", fail)
        with pytest.raises(RuntimeError, match="interrupted"):
            store.write_message("user-1", "Registered", {})
        monkeypatch.undo()

        started = time.monotonic()
        position = store.write_message("user-1", "Registered", {"n": 1})

        assert time.monotonic() - started < 1.0
        assert position == 0
        assert [row["data"] for row in store.get_stream_messages("user-1")] == [
            {"n": 1}
        ]


class TestConstraintViolations:
    def test_a_writer_that_bypassed_the_lock_gets_an_expected_version_error(
        self, store, monkeypatch
    ):
        store.write_message("user-1", "Registered", {})
        # A stale stream version, as a writer that read it without the lock
        # would see, sends the insert into the unique constraint.
        monkeypatch.setattr(store, "_last_position", lambda conn, name: -1)

        with pytest.raises(ExpectedVersionError, match="another writer") as caught:
            store.write_message("user-1", "Renamed", {}, None, expected_version=-1)

        assert isinstance(caught.value.__cause__, IntegrityError)
        monkeypatch.undo()
        assert len(store.get_stream_messages("user-1")) == 1

    def test_a_duplicate_message_id_is_not_a_version_error(self, store, monkeypatch):
        fixed = uuid.UUID("00000000-0000-4000-8000-000000000001")
        monkeypatch.setattr(
            "protean.adapters.event_store.sql.store.uuid4", lambda: fixed
        )
        store.write_message("user-1", "Registered", {})

        with pytest.raises(IntegrityError):
            store.write_message("user-2", "Registered", {})


class TestGlobalPosition:
    def test_the_first_message_takes_global_position_1(self, store):
        store.write_message("user-1", "Registered", {})
        store.write_message("order-1", "Placed", {})

        assert [row["global_position"] for row in store.get_all_messages()] == [1, 2]

    def test_clear_restarts_the_global_position_at_1(self, store):
        store.write_message("user-1", "Registered", {})
        store.write_message("user-1", "Renamed", {})

        store.clear()
        store.write_message("order-1", "Placed", {})

        (row,) = store.get_all_messages()
        assert row["global_position"] == 1
        assert row["stream_name"] == "order-1"

    def test_metadata_is_stored_as_given_and_none_stays_none(self, store):
        store.write_message("user-1", "Registered", {"a": 1}, {"kind": "EVENT"})
        store.write_message("user-1", "Renamed", {"a": 2})

        first, second = store.get_stream_messages("user-1")
        assert first["metadata"] == {"kind": "EVENT"}
        assert second["metadata"] is None


@pytest.mark.postgresql
class TestPostgresqlCategoryLock:
    @pytest.fixture
    def stores(self, make_store, tmp_path):
        config = backend_config("postgresql", tmp_path)
        return make_store(config), make_store(config)

    def hold_lock(self, store, monkeypatch, stream_name):
        """Start a write to ``stream_name`` that holds its category lock.

        Returns the event that releases it and the writer's thread.
        """
        held, release = threading.Event(), threading.Event()

        def wait():
            held.set()
            assert release.wait(timeout=10)

        monkeypatch.setattr(store, "_on_lock_taken", wait)
        writer = threading.Thread(
            target=store.write_message, args=(stream_name, "Registered", {})
        )
        writer.start()
        assert held.wait(timeout=10)
        return release, writer

    def test_another_category_writes_while_a_category_is_locked(
        self, stores, monkeypatch
    ):
        first, second = stores
        release, writer = self.hold_lock(first, monkeypatch, "user-1")
        try:
            other = threading.Thread(
                target=second.write_message, args=("order-1", "Placed", {})
            )
            other.start()
            other.join(timeout=5)
            assert not other.is_alive()
        finally:
            release.set()
            writer.join(timeout=10)

        assert [r["stream_name"] for r in second.get_all_messages()] == [
            "order-1",
            "user-1",
        ]

    def test_the_same_category_waits_for_the_lock(self, stores, monkeypatch):
        first, second = stores
        release, writer = self.hold_lock(first, monkeypatch, "user-1")
        try:
            same = threading.Thread(
                target=second.write_message, args=("user-2", "Registered", {})
            )
            same.start()
            same.join(timeout=0.5)
            assert same.is_alive()
        finally:
            release.set()
            writer.join(timeout=10)
        same.join(timeout=10)

        assert [r["stream_name"] for r in second.get_all_messages()] == [
            "user-1",
            "user-2",
        ]

    def test_the_lock_is_the_documented_key(self, stores, monkeypatch):
        first, second = stores
        release, writer = self.hold_lock(first, monkeypatch, "user-1")
        try:
            with second.get_connection().connect() as conn:
                held = (
                    conn.execute(
                        text(
                            "SELECT (classid::bigint << 32) | objid::bigint "
                            "FROM pg_locks WHERE locktype = 'advisory' AND granted"
                        )
                    )
                    .scalars()
                    .all()
                )
        finally:
            release.set()
            writer.join(timeout=10)

        key = _lock_key(PG_SCHEMA, "user")
        assert key in [value - 2**64 if value >= 2**63 else value for value in held]


@pytest.mark.sqlite
def test_the_lock_key_is_message_db_hash_64_of_the_schema_and_category():
    # The value PostgreSQL computes for
    # ('x' || left(md5('public.messages:user'), 16))::bit(64)::bigint.
    assert _lock_key("public", "user") == -3616439629249783035
