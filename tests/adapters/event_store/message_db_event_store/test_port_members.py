"""The ``EventStorePort`` members of the Message DB event store.

The event-store conformance suite, ``tests/conformance/event_store/``, tests
the Port behaviour both built-in stores share. These tests cover what only
the Message DB store does: its connection pool and an unreachable database.
"""

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


def test_domain_builds_the_store_named_default(store, test_domain):
    assert store.name == "default"
    assert store.config is test_domain.config["event_store"]


class TestHealth:
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
