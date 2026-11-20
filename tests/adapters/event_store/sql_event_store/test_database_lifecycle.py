"""``Domain.setup_database`` and its siblings manage the SQL event store's tables."""

import pytest
from sqlalchemy import inspect

from protean import Domain

from .conftest import sqlite_uri


def tables(store):
    return set(inspect(store.get_connection()).get_table_names())


@pytest.mark.sqlite
@pytest.mark.no_test_domain
class TestDatabaseLifecycle:
    @pytest.fixture
    def domain(self, tmp_path):
        domain = Domain(name="Lifecycle")
        domain.config["event_store"] = {
            "provider": "sql",
            "database_uri": sqlite_uri(tmp_path),
        }
        domain.init(traverse=False)
        with domain.domain_context():
            yield domain
        domain.event_store._adapter.close()

    def test_setup_database_creates_the_event_store_tables(self, domain):
        store = domain.event_store._adapter
        assert tables(store) == set()

        domain.setup_database()

        assert tables(store) == {"messages", "snapshots"}

    def test_truncate_database_clears_the_messages(self, domain):
        store = domain.event_store._adapter
        domain.setup_database()
        store.write_message("user-1", "Registered", {})

        domain.truncate_database()

        assert store.get_all_messages() == []

    def test_drop_database_drops_the_event_store_tables(self, domain):
        store = domain.event_store._adapter
        domain.setup_database()

        domain.drop_database()

        assert tables(store) == set()


@pytest.mark.no_test_domain
def test_a_store_without_schema_management_is_left_alone():
    domain = Domain(name="Memory")
    domain.init(traverse=False)
    with domain.domain_context():
        store = domain.event_store._adapter
        store.write_message("user-1", "Registered", {})

        domain.setup_database()
        domain.drop_database()

        assert len(store.get_all_messages()) == 1


@pytest.mark.no_test_domain
def test_setup_database_before_the_event_store_is_built_skips_it():
    domain = Domain(name="Unbuilt")

    domain._infrastructure.setup_database()

    assert domain.event_store._adapter is None
