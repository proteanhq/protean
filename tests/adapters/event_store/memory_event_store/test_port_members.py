"""The ``EventStorePort`` members of the memory event store."""

import pytest

from protean.adapters.event_store.memory import MemoryEventStore
from protean.exceptions import NotSupportedError
from protean.port.event_store import EventStoreHealth


def _write(store, stream_name: str, n: int) -> None:
    store.write_message(stream_name, "Counted", {"n": n})


def _streams(rows) -> list[str]:
    return [row["stream_name"] for row in rows]


class TestConstruction:
    def test_domain_builds_the_store_named_default(self, test_domain):
        store = test_domain.event_store.store

        assert isinstance(store, MemoryEventStore)
        assert store.name == "default"
        assert store.domain is test_domain

    def test_store_keeps_the_event_store_settings_as_config(self, test_domain):
        store = test_domain.event_store.store

        assert store.config is test_domain.config["event_store"]
        assert store.config["provider"] == "memory"


class TestCategoryReads:
    def test_category_read_leaves_out_a_category_with_the_same_suffix(
        self, test_domain
    ):
        store = test_domain.event_store.store
        _write(store, "user-1", 0)
        _write(store, "poweruser-1", 1)

        rows = store.get_category_messages("user")

        assert _streams(rows) == ["user-1"]
        assert [row["data"] for row in rows] == [{"n": 0}]

    def test_category_read_of_the_longer_name_returns_only_its_streams(
        self, test_domain
    ):
        store = test_domain.event_store.store
        _write(store, "user-1", 0)
        _write(store, "poweruser-1", 1)

        assert _streams(store.get_category_messages("poweruser")) == ["poweruser-1"]

    def test_category_read_includes_the_stream_named_as_the_category(self, test_domain):
        store = test_domain.event_store.store
        _write(store, "user", 0)
        _write(store, "users-1", 1)
        _write(store, "user-2", 2)

        assert _streams(store.get_category_messages("user")) == ["user", "user-2"]

    def test_category_read_leaves_out_snapshot_streams(self, test_domain):
        store = test_domain.event_store.store
        _write(store, "user-1", 0)
        store.write_message("user:snapshot-1", "SNAPSHOT", {"_version": 0})
        _write(store, "user-2", 1)

        assert _streams(store.get_category_messages("user")) == ["user-1", "user-2"]

    def test_category_read_pages_by_global_position(self, test_domain):
        store = test_domain.event_store.store
        _write(store, "user-1", 0)
        _write(store, "other-1", 1)
        _write(store, "user-2", 2)
        _write(store, "user-1", 3)

        first = store.get_category_messages("user")
        assert [row["data"]["n"] for row in first] == [0, 2, 3]

        rows = store.get_category_messages(
            "user", position=first[1]["global_position"], limit=1
        )

        assert [row["data"]["n"] for row in rows] == [2]


class TestConsumerGroups:
    @pytest.mark.parametrize(
        "group",
        [
            {"consumer_group_member": 0, "consumer_group_size": 2},
            {"consumer_group_member": 0},
            {"consumer_group_size": 2},
        ],
        ids=["both", "member-only", "size-only"],
    )
    def test_consumer_group_arguments_raise_not_supported(self, test_domain, group):
        store = test_domain.event_store.store

        with pytest.raises(NotSupportedError, match="consumer groups"):
            store.get_category_messages("user", **group)

    def test_category_read_without_group_arguments_returns_rows(self, test_domain):
        store = test_domain.event_store.store
        _write(store, "user-1", 0)

        assert _streams(store.get_category_messages("user")) == ["user-1"]


class TestLastMessageReads:
    def test_each_scope_returns_its_newest_row(self, test_domain):
        store = test_domain.event_store.store
        _write(store, "user-1", 0)
        _write(store, "user-1", 1)
        _write(store, "user-2", 2)
        _write(store, "order-1", 3)

        assert store.get_last_stream_message("user-1")["data"] == {"n": 1}
        assert store.get_last_category_message("user")["data"] == {"n": 2}
        assert store.get_last_message()["data"] == {"n": 3}

    def test_last_category_message_leaves_out_a_category_with_the_same_suffix(
        self, test_domain
    ):
        store = test_domain.event_store.store
        _write(store, "user-1", 0)
        _write(store, "poweruser-1", 1)

        assert store.get_last_category_message("user")["stream_name"] == "user-1"

    def test_last_category_message_leaves_out_longer_names_and_snapshots(
        self, test_domain
    ):
        store = test_domain.event_store.store
        _write(store, "user-1", 0)
        _write(store, "users-1", 1)
        store.write_message("user:snapshot-1", "SNAPSHOT", {"_version": 0})

        assert store.get_last_category_message("user")["stream_name"] == "user-1"

    def test_last_category_message_includes_the_stream_named_as_the_category(
        self, test_domain
    ):
        store = test_domain.event_store.store
        _write(store, "user-1", 0)
        _write(store, "user", 1)

        assert store.get_last_category_message("user")["stream_name"] == "user"

    def test_empty_scopes_return_none(self, test_domain):
        store = test_domain.event_store.store

        assert store.get_last_stream_message("user-1") is None
        assert store.get_last_category_message("user") is None
        assert store.get_last_message() is None


class TestStreamIds:
    def test_stream_ids_lists_the_ids_of_one_category(self, test_domain):
        store = test_domain.event_store.store
        _write(store, "user-1", 0)
        _write(store, "user-2", 1)
        _write(store, "user-1", 2)
        _write(store, "poweruser-3", 3)

        assert sorted(store.stream_ids("user")) == ["1", "2"]


class TestHealth:
    def test_ping_returns_true(self, test_domain):
        assert test_domain.event_store.store.ping() is True

    def test_health_reports_reachable_with_no_pool(self, test_domain):
        assert test_domain.event_store.store.health() == EventStoreHealth(
            reachable=True, pool=None
        )

    def test_get_connection_returns_none(self, test_domain):
        assert test_domain.event_store.store.get_connection() is None


def test_clear_removes_every_row(test_domain):
    store = test_domain.event_store.store
    _write(store, "user-1", 0)
    _write(store, "order-1", 1)

    store.clear()

    assert store.get_all_messages() == []
