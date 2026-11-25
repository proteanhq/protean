"""What a sql event store without a database_uri accepts and refuses.

Such a store shares the ``default`` database provider's engine.
"""

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError, ProgrammingError

from protean import Domain
from protean.adapters.event_store.sql.store import _on_sqlite_connect
from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ConfigurationError
from protean.fields import String
from tests.shared import POSTGRES_URI, provider_adapter

from .conftest import BACKENDS, PG_SCHEMA, row_count, shared_database


def init_domain(databases: dict[str, Any], event_store: dict[str, Any]) -> Domain:
    domain = Domain(name="SharedConfig")
    domain.config["databases"] = databases
    domain.config["event_store"] = event_store
    domain.init(traverse=False)
    return domain


def close(domain: Domain) -> None:
    domain.event_store._require_adapter().close()
    for name in domain.databases:
        provider_adapter(domain, name).close()


@pytest.mark.no_test_domain
class TestTheDefaultDatabaseMustBeSqlOnAFile:
    def test_a_memory_default_is_refused(self):
        with pytest.raises(ConfigurationError) as exc:
            init_domain({"default": {"provider": "memory"}}, {"provider": "sql"})

        message = str(exc.value)
        assert "without a database_uri" in message
        assert "provider 'memory'" in message
        assert "sqlite or postgresql" in message
        assert "Set database_uri under [event_store]" in message

    @pytest.mark.sqlite
    def test_a_sql_database_under_another_name_is_refused(self, tmp_path):
        databases = {
            "default": {"provider": "memory"},
            "other": shared_database("sqlite", tmp_path),
        }
        with pytest.raises(ConfigurationError, match="provider 'memory'"):
            init_domain(databases, {"provider": "sql"})

    @pytest.mark.sqlite
    @pytest.mark.parametrize(
        "uri",
        [
            "sqlite://",
            "sqlite:///:memory:",
            "sqlite:///file::memory:?uri=true",
            "sqlite:///file:shared?mode=memory&cache=shared&uri=true",
            "sqlite:///file:memdb?vfs=memdb&uri=true",
        ],
    )
    def test_an_in_memory_sqlite_default_is_refused(self, uri):
        with pytest.raises(ConfigurationError, match="in-memory SQLite database"):
            init_domain(
                {"default": {"provider": "sqlite", "database_uri": uri}},
                {"provider": "sql"},
            )

    @pytest.mark.sqlite
    def test_a_schema_on_the_event_store_is_refused(self, tmp_path):
        with pytest.raises(ConfigurationError, match="sets schema without"):
            init_domain(
                {"default": shared_database("sqlite", tmp_path)},
                {"provider": "sql", "schema": "events"},
            )


@pytest.mark.no_test_domain
class TestTheDefaultDatabaseIsolationLevel:
    @pytest.mark.postgresql
    @pytest.mark.parametrize("level", ["SERIALIZABLE", "REPEATABLE READ", "AUTOCOMMIT"])
    @pytest.mark.parametrize("where", ["key", "execution_options"])
    def test_postgresql_refuses_the_unsafe_levels(self, level, where):
        database: dict[str, Any] = {
            "provider": "postgresql",
            "database_uri": POSTGRES_URI,
        }
        if where == "key":
            database["isolation_level"] = level
        else:
            database["execution_options"] = {"isolation_level": level}

        with pytest.raises(ConfigurationError) as exc:
            init_domain({"default": database}, {"provider": "sql"})

        assert f"isolation level '{level}'" in str(exc.value)
        assert "Database 'default'" in str(exc.value)

    @pytest.mark.postgresql
    def test_postgresql_refuses_a_lowercase_unsafe_level(self):
        database = {
            "provider": "postgresql",
            "database_uri": POSTGRES_URI,
            "isolation_level": "repeatable_read",
        }
        with pytest.raises(ConfigurationError, match="'repeatable_read'"):
            init_domain({"default": database}, {"provider": "sql"})

    @pytest.mark.postgresql
    def test_postgresql_refuses_a_level_set_on_the_connection(self):
        database = {
            "provider": "postgresql",
            "database_uri": POSTGRES_URI,
            "connect_args": {
                "options": "-c default_transaction_isolation=serializable"
            },
        }
        with pytest.raises(ConfigurationError) as exc:
            init_domain({"default": database}, {"provider": "sql"})

        assert "runs its connections at isolation level 'serializable'" in str(
            exc.value
        )

    @pytest.mark.postgresql
    def test_postgresql_accepts_read_committed_on_the_connection(self):
        database = {
            "provider": "postgresql",
            "database_uri": POSTGRES_URI,
            "connect_args": {
                "options": "-c default_transaction_isolation=read\\ committed"
            },
        }
        domain = init_domain({"default": database}, {"provider": "sql"})
        try:
            assert domain.event_store.ping() is True
        finally:
            close(domain)

    @pytest.mark.sqlite
    def test_sqlite_refuses_autocommit(self, tmp_path):
        database = {
            **shared_database("sqlite", tmp_path),
            "isolation_level": "AUTOCOMMIT",
        }
        with pytest.raises(ConfigurationError, match="isolation level 'AUTOCOMMIT'"):
            init_domain({"default": database}, {"provider": "sql"})

    @pytest.mark.sqlite
    def test_sqlite_accepts_the_default_level(self, tmp_path):
        domain = init_domain(
            {"default": shared_database("sqlite", tmp_path)}, {"provider": "sql"}
        )
        try:
            assert domain.event_store.ping() is True
        finally:
            close(domain)


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
def test_the_tables_land_in_the_default_database_schema(make_shared_domain, backend):
    domain = make_shared_domain()
    store = domain.event_store._require_adapter()

    expected = PG_SCHEMA if backend == "postgresql" else None
    assert store._messages.schema == expected
    assert store._snapshots.schema == expected
    assert store.get_connection() is provider_adapter(domain, "default")._engine


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
def test_closing_the_store_keeps_the_provider_pool(make_shared_domain, backend):
    domain = make_shared_domain()
    engine = provider_adapter(domain, "default")._engine
    with engine.connect() as conn:
        pooled = conn.connection.dbapi_connection

    domain.event_store._require_adapter().close()

    with engine.connect() as conn:
        assert conn.connection.dbapi_connection is pooled


@pytest.mark.sqlite
@pytest.mark.no_test_domain
class TestSqliteSettingsOnTheSharedEngine:
    @pytest.fixture
    def backend(self) -> str:
        return "sqlite"

    def test_a_shared_connection_runs_wal_with_a_busy_timeout(self, make_shared_domain):
        domain = make_shared_domain()
        engine = provider_adapter(domain, "default")._engine

        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000

    def test_a_memory_event_store_leaves_the_sqlite_provider_alone(
        self, tmp_path: Path
    ):
        domain = init_domain(
            {"default": shared_database("sqlite", tmp_path)}, {"provider": "memory"}
        )
        try:
            engine = provider_adapter(domain, "default")._engine
            with engine.connect() as conn:
                assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "delete"
        finally:
            close(domain)

    def test_a_second_init_installs_the_settings_once(self, make_shared_domain):
        domain = make_shared_domain()
        engine = provider_adapter(domain, "default")._engine
        domain.event_store._initialize()
        assert engine is provider_adapter(domain, "default")._engine

        # A second BEGIN on one connection raises, so the commit proves that
        # one listener emitted it.
        with UnitOfWork():
            domain.event_store._require_adapter().write_message(
                "user-1", "Registered", {}
            )

        assert event.contains(engine, "connect", _on_sqlite_connect)
        assert (
            domain.event_store._require_adapter().get_last_stream_message("user-1")
            is not None
        )


class Ledger(BaseAggregate):
    name = String()


def row_count_or_none(domain: Domain, table: str) -> int | None:
    """Count the rows of ``table``, or return None when it does not exist."""
    try:
        return row_count(domain, table)
    except (OperationalError, ProgrammingError):
        return None


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
def test_setup_and_drop_database_run_on_the_shared_engine(make_shared_domain):
    def register(domain: Domain) -> None:
        domain.register(Ledger)

    domain = make_shared_domain(register)
    domain.drop_database()
    assert row_count_or_none(domain, "messages") is None

    domain.setup_database()

    assert row_count(domain, "messages") == 0
    assert row_count(domain, "ledger") == 0
