"""What the SQL event store accepts and refuses when it is built."""

import importlib

import pytest

import protean.adapters.event_store
import protean.adapters.event_store.sql
from protean import Domain
from protean.adapters.event_store.sql.store import SqlEventStore
from protean.exceptions import ConfigurationError
from protean.infra.registry import event_stores
from tests.shared import POSTGRES_URI, module_unavailable

from .conftest import sqlite_uri


def build(test_domain, **config):
    return SqlEventStore("default", test_domain, {"provider": "sql", **config})


@pytest.mark.sqlite
class TestDatabaseUri:
    def test_a_missing_database_uri_is_refused(self, test_domain):
        with pytest.raises(ConfigurationError, match="without a database_uri"):
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

    def test_engine_keys_sqlite_has_no_pool_for_are_dropped(
        self, test_domain, tmp_path
    ):
        store = build(
            test_domain,
            database_uri=sqlite_uri(tmp_path),
            pool_size=3,
            max_overflow=1,
            pool_recycle=60,
        )
        try:
            assert store.ping() is True
        finally:
            store.close()


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
            with pytest.raises(ConfigurationError, match=r"protean\[sqlite\]"):
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
