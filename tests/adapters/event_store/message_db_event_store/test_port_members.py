"""The ``EventStorePort`` members of the Message DB event store."""

import pytest

from protean import Domain
from protean.adapters.event_store.message_db import (
    MessageDBStore,
    _superuser_connection,
)
from protean.port.event_store import EventStoreHealth
from tests.shared import MESSAGE_DB_PORT

pytestmark = pytest.mark.message_db


@pytest.fixture
def store(test_domain):
    test_domain.init(traverse=False)
    event_store = test_domain.event_store.store
    assert isinstance(event_store, MessageDBStore)
    return event_store


def _write(store, stream_name: str, n: int) -> None:
    store.write_message(stream_name, "Counted", {"n": n})


def _streams(rows) -> list[str]:
    return [row["stream_name"] for row in rows]


def test_domain_builds_the_store_named_default(store, test_domain):
    assert store.name == "default"
    assert store.config is test_domain.config["event_store"]


class TestCategoryReads:
    def test_category_read_leaves_out_a_category_with_the_same_suffix(self, store):
        _write(store, "user-1", 0)
        _write(store, "poweruser-1", 1)

        assert _streams(store.get_category_messages("user")) == ["user-1"]

    def test_category_read_of_the_longer_name_returns_only_its_streams(self, store):
        _write(store, "user-1", 0)
        _write(store, "poweruser-1", 1)

        assert _streams(store.get_category_messages("poweruser")) == ["poweruser-1"]

    def test_category_read_includes_the_stream_named_as_the_category(self, store):
        _write(store, "user", 0)
        _write(store, "users-1", 1)
        _write(store, "user-2", 2)

        assert _streams(store.get_category_messages("user")) == ["user", "user-2"]


class TestConsumerGroups:
    def test_two_members_split_the_category_into_disjoint_halves(self, store):
        streams = [f"user-{i}" for i in range(8)]
        for n, stream_name in enumerate(streams):
            _write(store, stream_name, n)

        member_0 = store.get_category_messages(
            "user", consumer_group_member=0, consumer_group_size=2
        )
        member_1 = store.get_category_messages(
            "user", consumer_group_member=1, consumer_group_size=2
        )

        ids_0 = {row["id"] for row in member_0}
        ids_1 = {row["id"] for row in member_1}
        all_ids = {row["id"] for row in store.get_category_messages("user")}
        assert len(all_ids) == 8
        assert ids_0.isdisjoint(ids_1)
        assert ids_0 | ids_1 == all_ids

    def test_category_read_without_group_arguments_returns_every_stream(self, store):
        for i in range(4):
            _write(store, f"user-{i}", i)

        assert _streams(store.get_category_messages("user")) == [
            "user-0",
            "user-1",
            "user-2",
            "user-3",
        ]

    @pytest.mark.parametrize(
        "group",
        [{"consumer_group_member": 0}, {"consumer_group_size": 2}],
        ids=["member-only", "size-only"],
    )
    def test_a_lone_group_argument_raises_value_error(self, store, group):
        with pytest.raises(ValueError, match="must be given together"):
            store.get_category_messages("user", **group)


class TestLastMessageReads:
    def test_each_scope_returns_its_newest_row(self, store):
        _write(store, "user-1", 0)
        _write(store, "user-1", 1)
        _write(store, "user-2", 2)
        _write(store, "order-1", 3)

        assert store.get_last_stream_message("user-1")["data"] == {"n": 1}
        assert store.get_last_category_message("user")["data"] == {"n": 2}
        assert store.get_last_message()["data"] == {"n": 3}

    def test_last_category_message_leaves_out_other_categories(self, store):
        _write(store, "user-1", 0)
        _write(store, "poweruser-1", 1)
        store.write_message("user:snapshot-1", "SNAPSHOT", {"_version": 0})

        last = store.get_last_category_message("user")

        assert last["stream_name"] == "user-1"
        assert last["data"] == {"n": 0}

    def test_empty_scopes_return_none(self, store):
        assert store.get_last_stream_message("user-1") is None
        assert store.get_last_category_message("user") is None
        assert store.get_last_message() is None


class TestHealth:
    def test_ping_returns_true_for_a_running_database(self, store):
        assert store.ping() is True

    def test_health_reports_the_pool(self, store):
        health = store.health()

        assert health.reachable is True
        assert health.pool is not None
        pool = store.get_connection().connection_pool._connection_pool
        assert health.pool["size"] == pool.maxconn
        assert health.pool["checked_out"] == 0
        assert health.pool["overflow"] == 0
        assert health.pool["checked_in"] >= 1

    def test_pool_stats_are_none_before_first_use(self, test_domain):
        store = MessageDBStore(
            "default", test_domain, dict(test_domain.config["event_store"])
        )

        assert store._pool_stats() is None

    def test_ping_replaces_a_connection_the_server_dropped(self, store):
        assert store.ping() is True
        pool = store.get_connection().connection_pool._connection_pool
        assert len(pool._pool) == 1
        dropped = pool._pool[0]

        admin = _superuser_connection(store.config["database_uri"])
        try:
            with admin.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_terminate_backend(%s)", (dropped.get_backend_pid(),)
                )
            admin.commit()
        finally:
            admin.close()

        assert store.ping() is True
        assert dropped.closed
        assert dropped not in pool._pool


@pytest.mark.no_test_domain
class TestUnreachableDatabase:
    @pytest.fixture
    def unreachable(self):
        domain = Domain(name="Unreachable Message DB")
        domain.config["event_store"]["provider"] = "message_db"
        domain.config["event_store"]["database_uri"] = (
            f"postgresql://message_store@localhost:{MESSAGE_DB_PORT}/missing"
        )
        domain.init(traverse=False)
        return domain.event_store.store

    def test_ping_returns_false(self, unreachable):
        assert unreachable.ping() is False

    def test_health_reports_unreachable_with_no_pool(self, unreachable):
        assert unreachable.health() == EventStoreHealth(reachable=False, pool=None)
