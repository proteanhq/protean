"""What the SQL event store accepts and refuses when it is built."""

import importlib

import pytest
from sqlalchemy import text

import protean.adapters.event_store
import protean.adapters.event_store.sql
from protean import Domain
from protean.adapters.event_store.sql.store import SqlEventStore, _lock_key
from protean.exceptions import ConfigurationError
from protean.infra.registry import event_stores
from tests.shared import POSTGRES_URI, module_unavailable

from .conftest import PG_SCHEMA, backend_config, sqlite_uri


def build(test_domain, **config):
    return SqlEventStore("default", test_domain, {"provider": "sql", **config})


@pytest.mark.sqlite
class TestDatabaseUri:
    def test_a_missing_database_uri_on_a_memory_default_is_refused(self, test_domain):
        with pytest.raises(
            ConfigurationError,
            match="without a database_uri, so it shares the 'default' database",
        ):
            build(test_domain)

    @pytest.mark.parametrize("uri", ["not a url", "postgresql://h:port/db"])
    def test_an_unparseable_database_uri_is_refused(self, test_domain, uri):
        with pytest.raises(ConfigurationError, match="cannot be parsed"):
            build(test_domain, database_uri=uri)

    def test_another_database_is_refused_with_the_supported_schemes(self, test_domain):
        with pytest.raises(
            ConfigurationError,
            match=r"'mysql\+pymysql://'.*supports sqlite and postgresql",
        ):
            build(test_domain, database_uri="mysql+pymysql://u:p@h/db")

    @pytest.mark.parametrize(
        "uri",
        [
            "sqlite://",
            "sqlite:///:memory:",
            "sqlite:///file::memory:?uri=true",
            "sqlite:///file:events?mode=memory&uri=true",
        ],
    )
    def test_an_in_memory_sqlite_database_is_refused(self, test_domain, uri):
        with pytest.raises(ConfigurationError, match="in-memory SQLite"):
            build(test_domain, database_uri=uri)

    def test_a_sqlite_file_is_accepted(self, test_domain, tmp_path):
        store = build(test_domain, database_uri=sqlite_uri(tmp_path))
        try:
            assert store.ping() is True
        finally:
            store.close()

    def test_a_schema_on_sqlite_is_refused(self, test_domain, tmp_path):
        with pytest.raises(ConfigurationError, match="sets schema on SQLite"):
            build(test_domain, database_uri=sqlite_uri(tmp_path), schema="events")

    def test_pool_keys_reach_the_sqlite_file_pool(self, test_domain, tmp_path):
        store = build(
            test_domain,
            database_uri=sqlite_uri(tmp_path),
            pool_size=3,
            max_overflow=1,
            pool_recycle=60,
        )
        try:
            assert store.ping() is True
            assert store.get_connection().pool.size() == 3
        finally:
            store.close()

    def test_sqlite_connections_run_wal_with_a_busy_timeout(
        self, test_domain, tmp_path
    ):
        store = build(test_domain, database_uri=sqlite_uri(tmp_path))
        try:
            with store.get_connection().connect() as conn:
                assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
                assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
        finally:
            store.close()


@pytest.mark.postgresql
class TestPostgresqlSchema:
    def test_the_schema_defaults_to_public(self, test_domain):
        store = build(test_domain, database_uri=POSTGRES_URI)
        try:
            assert store._messages.schema == "public"
        finally:
            store.close()

    @pytest.mark.parametrize("schema", ["", "  ", 5])
    def test_a_schema_that_is_not_a_name_is_refused(self, test_domain, schema):
        with pytest.raises(ConfigurationError, match=f"has schema {schema!r}"):
            build(test_domain, database_uri=POSTGRES_URI, schema=schema)


@pytest.mark.postgresql
class TestPostgresqlEngineDefaults:
    def test_the_engine_gets_the_database_provider_pool_defaults(self, test_domain):
        store = build(test_domain, database_uri=POSTGRES_URI)
        try:
            pool = store.get_connection().pool
            assert pool.size() == 5
            assert pool._max_overflow == 10
            assert pool._pre_ping is True
            assert pool._recycle == 1800
        finally:
            store.close()

    def test_the_config_overrides_a_default(self, test_domain):
        store = build(test_domain, database_uri=POSTGRES_URI, pool_recycle=60)
        try:
            assert store.get_connection().pool._recycle == 60
        finally:
            store.close()

    @pytest.mark.parametrize(
        "unset",
        [
            {"isolation_level": None},
            {"execution_options": {"isolation_level": None}},
            {},
        ],
    )
    def test_a_server_default_level_does_not_change_read_committed(
        self, test_domain, unset
    ):
        store = build(
            test_domain,
            database_uri=POSTGRES_URI,
            **unset,
            connect_args={
                "options": "-c default_transaction_isolation=repeatable\\ read"
            },
        )
        try:
            with store.get_connection().begin() as conn:
                level = conn.exec_driver_sql("SHOW transaction_isolation").scalar()
            assert level == "read committed"
        finally:
            store.close()

    def test_a_driver_autocommit_still_holds_the_lock_to_the_commit(
        self, make_store, tmp_path, monkeypatch
    ):
        config = backend_config("postgresql", tmp_path)
        store = make_store({**config, "connect_args": {"autocommit": True}})
        held: list[bool] = []

        def check_lock() -> None:
            with store.get_connection().connect() as other:
                keys = (
                    other.execute(
                        text(
                            "SELECT (classid::bigint << 32) | objid::bigint "
                            "FROM pg_locks WHERE locktype = 'advisory' AND granted"
                        )
                    )
                    .scalars()
                    .all()
                )
            signed = [key - 2**64 if key >= 2**63 else key for key in keys]
            held.append(_lock_key(PG_SCHEMA, "user") in signed)

        monkeypatch.setattr(store, "_on_lock_taken", check_lock)
        store.write_message("user-1", "Registered", {})

        assert held == [True]


class TestIsolationLevel:
    @pytest.mark.parametrize(
        "level",
        [
            pytest.param(level, marks=pytest.mark.postgresql)
            for level in (
                "AUTOCOMMIT",
                "REPEATABLE READ",
                "serializable",
                "REPEATABLE_READ",
            )
        ],
    )
    @pytest.mark.parametrize("where", ["key", "execution_options"])
    def test_postgresql_refuses_the_unsafe_levels(self, test_domain, level, where):
        config = (
            {"isolation_level": level}
            if where == "key"
            else {"execution_options": {"isolation_level": level}}
        )
        with pytest.raises(ConfigurationError, match=f"isolation level '{level}'"):
            build(test_domain, database_uri=POSTGRES_URI, **config)

    @pytest.mark.sqlite
    @pytest.mark.parametrize("level", ["REPEATABLE READ", "READ COMMITTED", 5])
    def test_sqlite_refuses_a_level_it_does_not_run(self, test_domain, tmp_path, level):
        with pytest.raises(ConfigurationError, match="sqlite does not run this level"):
            build(test_domain, database_uri=sqlite_uri(tmp_path), isolation_level=level)

    @pytest.mark.sqlite
    @pytest.mark.parametrize("options", ["x", ["isolation_level"], "", [], None])
    def test_execution_options_that_are_not_a_table_are_refused(
        self, test_domain, tmp_path, options
    ):
        with pytest.raises(
            ConfigurationError, match="Set execution_options to a table"
        ):
            build(
                test_domain,
                database_uri=sqlite_uri(tmp_path),
                execution_options=options,
            )

    @pytest.mark.postgresql
    def test_postgresql_accepts_read_committed(self, test_domain):
        store = build(
            test_domain, database_uri=POSTGRES_URI, isolation_level="READ COMMITTED"
        )
        store.close()

    @pytest.mark.sqlite
    @pytest.mark.parametrize("where", ["key", "execution_options"])
    def test_sqlite_refuses_autocommit(self, test_domain, tmp_path, where):
        config = (
            {"isolation_level": "AUTOCOMMIT"}
            if where == "key"
            else {"execution_options": {"isolation_level": "autocommit"}}
        )
        with pytest.raises(ConfigurationError, match="isolation level"):
            build(test_domain, database_uri=sqlite_uri(tmp_path), **config)

    @pytest.mark.sqlite
    def test_sqlite_accepts_serializable(self, test_domain, tmp_path):
        store = build(
            test_domain,
            database_uri=sqlite_uri(tmp_path),
            isolation_level="SERIALIZABLE",
        )
        store.close()


@pytest.mark.postgresql
class TestPostgresqlDriver:
    def test_a_url_without_a_driver_gets_psycopg_3(self, test_domain):
        store = build(test_domain, database_uri=POSTGRES_URI)
        assert store.get_connection().url.drivername == "postgresql+psycopg"

    def test_a_url_that_names_a_driver_keeps_it(self, test_domain):
        uri = POSTGRES_URI.replace("postgresql://", "postgresql+psycopg2://")
        store = build(test_domain, database_uri=uri)
        assert store.get_connection().url.drivername == "postgresql+psycopg2"

    def test_no_driver_is_refused_naming_the_event_store(self, test_domain):
        with module_unavailable("psycopg", "psycopg2"):
            with pytest.raises(
                ConfigurationError,
                match=r"Event store 'default' uses a 'postgresql://' URL, and no "
                "PostgreSQL driver",
            ):
                build(test_domain, database_uri=POSTGRES_URI)


@pytest.mark.sqlite
class TestRegistration:
    def test_a_domain_with_provider_sql_uses_the_store(self, tmp_path):
        domain = Domain(name="Registered")
        domain.config["event_store"] = {
            "provider": "sql",
            "database_uri": sqlite_uri(tmp_path),
        }
        domain.init(traverse=False)
        with domain.domain_context():
            store = domain.event_store._adapter
            try:
                assert isinstance(store, SqlEventStore)
            finally:
                store.close()

    @pytest.mark.parametrize("uri", ["mysql+pymysql://u:p@h/db", "sqlite://"])
    def test_a_domain_with_an_unsupported_database_fails_to_init(self, uri):
        domain = Domain(name="Refused")
        domain.config["event_store"] = {"provider": "sql", "database_uri": uri}
        with pytest.raises(ConfigurationError, match="Event store 'default'"):
            domain.init(traverse=False)

    def test_without_sqlalchemy_the_store_names_the_extras(self):
        with module_unavailable(
            "sqlalchemy",
            reload=(
                "protean.adapters.event_store.sql.store",
                "protean.adapters.event_store.sql.schema",
            ),
        ):
            with pytest.raises(
                ImportError, match=r'protean\[sqlite\]".*protean\[postgresql\]'
            ):
                importlib.import_module("protean.adapters.event_store.sql.store")
            with pytest.raises(
                ConfigurationError, match=r"protean\[sqlite\].*protean\[postgresql\]"
            ):
                event_stores.get("sql")

    def test_registering_needs_no_sqlalchemy(self, monkeypatch):
        # The import below binds a new package to the parent's ``sql``
        # attribute. Setting the attribute to itself makes monkeypatch put the
        # original back after the test.
        monkeypatch.setattr(
            protean.adapters.event_store, "sql", protean.adapters.event_store.sql
        )
        with module_unavailable(
            "sqlalchemy", reload=("protean.adapters.event_store.sql",)
        ):
            package = importlib.import_module("protean.adapters.event_store.sql")
            package.register()
        assert event_stores.get("sql") is SqlEventStore
