"""How the SQL event store reads: snapshots, categories, times and health."""

import time
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import Engine, inspect

from protean.adapters.event_store.sql.store import SqlEventStore
from protean.exceptions import NotSupportedError
from tests.shared import FrozenClock

from .conftest import backend_config

SNAPSHOT = "user:snapshot-1"


class TestSnapshots:
    def test_a_snapshot_stream_keeps_one_row_and_counts_its_writes(self, store):
        assert store.write_message(SNAPSHOT, "SNAPSHOT", {"_version": 3}) == 0
        assert store.write_message(SNAPSHOT, "SNAPSHOT", {"_version": 7}) == 1

        (row,) = store.get_stream_messages(SNAPSHOT)
        assert row["data"] == {"_version": 7}
        assert row["position"] == 1
        assert row["global_position"] == 0
        assert row["type"] == "SNAPSHOT"
        assert row["metadata"] is None
        assert store.get_last_stream_message(SNAPSHOT) == row

    def test_a_snapshot_is_left_out_of_category_and_all_reads(self, store):
        store.write_message("user-1", "Registered", {})
        store.write_message(SNAPSHOT, "SNAPSHOT", {"_version": 0})

        assert [r["stream_name"] for r in store.get_all_messages()] == ["user-1"]
        assert [r["stream_name"] for r in store.get_category_messages("user")] == [
            "user-1"
        ]
        assert store.get_last_message()["stream_name"] == "user-1"
        assert store.get_last_category_message("user")["stream_name"] == "user-1"
        assert store.stream_ids("user") == ["1"]

    def test_a_snapshot_takes_no_global_position(self, store):
        store.write_message(SNAPSHOT, "SNAPSHOT", {"_version": 0})

        store.write_message("user-1", "Registered", {})

        assert store.get_last_message()["global_position"] == 1

    def test_a_stream_read_past_the_snapshot_position_is_empty(self, store):
        store.write_message(SNAPSHOT, "SNAPSHOT", {"_version": 0})

        assert store.get_stream_messages(SNAPSHOT, position=1) == []
        assert store.get_stream_messages(SNAPSHOT, limit=0) == []

    def test_snapshot_metadata_is_not_kept(self, store):
        store.write_message(SNAPSHOT, "SNAPSHOT", {"_version": 3}, {"kind": "x"})

        assert store.get_last_stream_message(SNAPSHOT)["metadata"] is None

    def test_a_missing_snapshot_reads_as_none(self, store):
        assert store.get_stream_messages(SNAPSHOT) == []
        assert store.get_last_stream_message(SNAPSHOT) is None


class TestCategories:
    def test_a_category_read_matches_the_category_exactly(self, store):
        store.write_message("user-1", "Registered", {})
        store.write_message("users-1", "Registered", {})
        store.write_message("user", "Registered", {})

        names = [r["stream_name"] for r in store.get_category_messages("user")]

        assert names == ["user-1", "user"]

    def test_stream_ids_are_sorted_and_skip_a_stream_without_one(self, store):
        for name in ("user-b", "user-a", "user-b", "user", "users-c"):
            store.write_message(name, "Registered", {})

        assert store.stream_ids("user") == ["a", "b"]

    def test_stream_ids_keep_the_text_after_the_first_dash(self, store):
        store.write_message("user-1-2", "Registered", {})

        assert store.stream_ids("user") == ["1-2"]

    @pytest.mark.parametrize(
        "group", [{"consumer_group_member": 0}, {"consumer_group_size": 2}]
    )
    def test_a_consumer_group_read_is_not_supported(self, store, group):
        with pytest.raises(NotSupportedError, match="consumer groups"):
            store.get_category_messages("user", **group)


class TestLimit:
    @pytest.mark.parametrize(
        "read",
        [
            lambda store: store.get_stream_messages("user-1", limit=-1),
            lambda store: store.get_category_messages("user", limit=-1),
            lambda store: store.get_all_messages(limit=-1),
        ],
        ids=["stream", "category", "all"],
    )
    def test_a_negative_limit_is_refused(self, store, read):
        store.write_message("user-1", "Registered", {})

        with pytest.raises(ValueError, match="limit must be 0 or more, not -1"):
            read(store)

    def test_a_limit_of_0_reads_nothing(self, store):
        store.write_message("user-1", "Registered", {})

        assert store.get_stream_messages("user-1", limit=0) == []


@pytest.mark.sqlite
class TestSqliteReadsDuringAWrite:
    def test_a_read_and_a_ping_do_not_wait_for_a_write(self, make_store, tmp_path):
        config = backend_config("sqlite", tmp_path)
        store, writer = make_store(config), make_store(config)
        store.write_message("user-1", "Registered", {})

        with writer._write_engine.begin() as conn:
            conn.execute(writer._messages.select().limit(1))
            started = time.monotonic()
            rows = store.get_stream_messages("user-1")
            reachable = store.ping()
            elapsed = time.monotonic() - started

        assert len(rows) == 1
        assert reachable is True
        assert elapsed < 1.0


class TestTime:
    def test_a_time_in_another_zone_reads_back_as_the_same_instant_in_utc(
        self, store, test_domain
    ):
        written = datetime(
            2031, 3, 4, 12, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
        )
        test_domain.clock = FrozenClock(written)

        store.write_message("user-1", "Registered", {})
        store.write_message(SNAPSHOT, "SNAPSHOT", {})

        for row in (store.get_last_message(), store.get_last_stream_message(SNAPSHOT)):
            assert row["time"] == written
            assert row["time"].tzinfo == UTC
            assert row["time"].hour == 7


class TestHealth:
    def test_a_reachable_store_pings_and_reports_its_pool(self, store):
        store.get_stream_messages("user-1")

        health = store.health()

        assert health.reachable is True
        assert health.pool is not None
        assert health.pool["checked_out"] == 0

    def test_get_connection_returns_the_engine(self, store):
        engine = store.get_connection()
        assert isinstance(engine, Engine)
        assert engine.dialect.name in ("sqlite", "postgresql")

    def test_close_disposes_of_the_pool(self, store):
        before = store.get_connection().pool
        store.ping()

        store.close()

        assert store.get_connection().pool is not before
        assert before.checkedin() == 0

    def test_the_tables_carry_the_documented_names(self, store):
        inspector = inspect(store.get_connection())
        schema = store._messages.schema

        unique = {
            c["name"] for c in inspector.get_unique_constraints("messages", schema)
        }
        indexes = {i["name"] for i in inspector.get_indexes("messages", schema)}
        assert {"uq_messages_id", "uq_messages_stream_position"} <= unique | indexes
        assert "ix_messages_category_global_position" in indexes

    @pytest.mark.postgresql
    def test_an_unreachable_database_pings_false(self, test_domain, caplog):
        store = SqlEventStore(
            "default",
            test_domain,
            {
                "provider": "sql",
                "database_uri": "postgresql://postgres:postgres@localhost:1/none",
            },
        )
        try:
            with caplog.at_level(
                "DEBUG", logger="protean.adapters.event_store.sql.store"
            ):
                assert store.ping() is False
            assert store.health().reachable is False
            assert "SQL event store ping failed" in caplog.text
        finally:
            store.close()
