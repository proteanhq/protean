"""Load the configurations on ``docs/reference/adapters/eventstore/sql.md``."""

import pytest
from sqlalchemy import text

from protean.adapters.event_store.sql.store import SqlEventStore
from protean.core.unit_of_work import UnitOfWork
from tests.docs.support import domain_from_config
from tests.shared import POSTGRES_URI, provider_adapter

SQLITE_CONFIG = "adapters/eventstore/sql/configuration.toml"
POSTGRESQL_CONFIG = "adapters/eventstore/sql/postgresql.toml"
SHARED_CONFIG = "adapters/eventstore/sql/shared.toml"

pytestmark = pytest.mark.no_test_domain


def write_and_read(domain):
    domain.init(traverse=False)
    with domain.domain_context():
        store = domain.event_store._adapter
        try:
            store.create_schema()
            store.write_message("doc_check-1", "Checked", {"n": 1})

            assert type(store) is SqlEventStore
            assert [m["data"] for m in store.get_stream_messages("doc_check-1")] == [
                {"n": 1}
            ]
        finally:
            store.drop_schema()
            store.close()


@pytest.mark.sqlite
def test_sqlite_configuration_shown_writes_and_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("SQL_EVENT_STORE_URL", f"sqlite:///{tmp_path / 'events.db'}")

    write_and_read(domain_from_config(SQLITE_CONFIG, tmp_path))


@pytest.mark.postgresql
def test_postgresql_configuration_shown_writes_and_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("SQL_EVENT_STORE_URL", POSTGRES_URI)
    domain = domain_from_config(POSTGRESQL_CONFIG, tmp_path)
    schema = domain.config["event_store"]["schema"]
    store = SqlEventStore("setup", domain, domain.config["event_store"])
    try:
        # The page says the schema must exist before the tables are created.
        with store.get_connection().begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

        write_and_read(domain)
    finally:
        with store.get_connection().begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        store.close()


@pytest.mark.sqlite
def test_shared_configuration_shown_commits_with_the_unit_of_work(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    domain = domain_from_config(SHARED_CONFIG, tmp_path)
    domain.init(traverse=False)
    with domain.domain_context():
        store = domain.event_store._adapter
        try:
            store.create_schema()
            assert store.get_connection() is provider_adapter(domain)._engine

            with pytest.raises(RuntimeError, match="rolled back"):
                with UnitOfWork():
                    store.write_message("doc_check-1", "Dropped", {})
                    raise RuntimeError("rolled back")
            with UnitOfWork():
                assert store.write_message("doc_check-1", "Checked", {}) is None

            assert [m["type"] for m in store.get_stream_messages("doc_check-1")] == [
                "Checked"
            ]
        finally:
            store.drop_schema()
            store.close()
            provider_adapter(domain).close()


@pytest.mark.parametrize(
    ("config", "documented"),
    [
        (SQLITE_CONFIG, "sqlite:///events.db"),
        (POSTGRESQL_CONFIG, "postgresql://postgres:postgres@localhost:5432/postgres"),
    ],
)
def test_configuration_shown_defaults_to_the_documented_uri(
    tmp_path, monkeypatch, config, documented
):
    monkeypatch.delenv("SQL_EVENT_STORE_URL", raising=False)
    domain = domain_from_config(config, tmp_path)

    assert domain.config["event_store"]["database_uri"] == documented


def test_shared_configuration_shown_defaults_to_the_documented_uri(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    domain = domain_from_config(SHARED_CONFIG, tmp_path)

    assert domain.config["databases"]["default"]["database_uri"] == "sqlite:///app.db"
    assert "database_uri" not in domain.config["event_store"]
