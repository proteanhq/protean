import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from protean import Domain
from protean.adapters.event_store.sql.store import SqlEventStore
from tests.shared import POSTGRES_URI, provider_adapter

# The PostgreSQL tests use their own schema, so they never touch the tables
# of the conformance run on the same database. The name holds the process id,
# so two test runs on one database do not drop each other's tables.
PG_SCHEMA = f"protean_sql_store_tests_{os.getpid()}"

BACKENDS = [
    pytest.param("sqlite", marks=pytest.mark.sqlite),
    pytest.param("postgresql", marks=pytest.mark.postgresql),
]


def sqlite_uri(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'events.db'}"


def backend_config(backend: str, tmp_path: Path) -> dict[str, Any]:
    if backend == "sqlite":
        return {"provider": "sql", "database_uri": sqlite_uri(tmp_path)}
    return {"provider": "sql", "database_uri": POSTGRES_URI, "schema": PG_SCHEMA}


@pytest.fixture
def make_store(
    test_domain: Domain,
) -> Iterator[Callable[[dict[str, Any]], SqlEventStore]]:
    """Build stores from a config, each with its tables, and close them after."""
    stores: list[SqlEventStore] = []

    def make(config: dict[str, Any]) -> SqlEventStore:
        store = SqlEventStore("default", test_domain, config)
        if config.get("schema"):
            with store.get_connection().begin() as conn:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{config["schema"]}"'))
        store.create_schema()
        stores.append(store)
        return store

    yield make

    if stores:
        stores[0].drop_schema()
        schema = stores[0].config.get("schema")
        if schema:
            with stores[0].get_connection().begin() as conn:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}"'))
    for store in stores:
        store.close()


@pytest.fixture(params=BACKENDS)
def backend(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def config(backend: str, tmp_path: Path) -> dict[str, Any]:
    return backend_config(backend, tmp_path)


@pytest.fixture
def store(make_store, config) -> SqlEventStore:
    return make_store(config)


def shared_database(backend: str, tmp_path: Path) -> dict[str, Any]:
    """The ``default`` database a shared store uses, on ``backend``."""
    if backend == "sqlite":
        return {
            "provider": "sqlite",
            "database_uri": f"sqlite:///{tmp_path / 'shared.db'}",
        }
    return {"provider": "postgresql", "database_uri": POSTGRES_URI, "schema": PG_SCHEMA}


def _create_pg_schema() -> None:
    engine = create_engine(POSTGRES_URI)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{PG_SCHEMA}"'))
    finally:
        engine.dispose()


def _drop_pg_schema() -> None:
    engine = create_engine(POSTGRES_URI)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{PG_SCHEMA}" CASCADE'))
    finally:
        engine.dispose()


@pytest.fixture
def make_shared_domain(backend: str, tmp_path: Path) -> Iterator[Callable[..., Domain]]:
    """Build a domain whose sql event store shares ``default`` on ``backend``.

    ``register`` receives the domain before ``init()``. Other keyword arguments
    go into the domain's config, and a table updates the table already there. The domain's context stays active until the
    test ends, and the tables of the provider and the store exist.
    """
    domains: list[Domain] = []
    contexts: list[Any] = []

    def make(register: Callable[[Domain], None] | None = None, **config: Any) -> Domain:
        if backend == "postgresql":
            _create_pg_schema()
        domain = Domain(name=f"Shared{len(domains)}")
        domain.config["databases"]["default"] = shared_database(backend, tmp_path)
        domain.config["event_store"] = {"provider": "sql"}
        domain.config["command_processing"] = "sync"
        domain.config["event_processing"] = "sync"
        for key, value in config.items():
            current = domain.config.get(key)
            if isinstance(current, dict) and isinstance(value, dict):
                current.update(value)
            else:
                domain.config[key] = value
        if register is not None:
            register(domain)
        domain.init(traverse=False)
        context = domain.domain_context()
        context.push()
        contexts.append(context)
        domains.append(domain)
        provider_adapter(domain, "default").create_schema()
        domain.event_store._require_adapter().create_schema()
        return domain

    yield make

    for context in reversed(contexts):
        context.pop()
    for domain in domains:
        domain.event_store._require_adapter().close()
        provider_adapter(domain, "default").close()
    if domains and backend == "postgresql":
        _drop_pg_schema()


def row_count(domain: Domain, table: str) -> int:
    """Count the rows of ``table`` in ``default`` on a connection of its own."""
    provider = provider_adapter(domain, "default")
    schema = provider._metadata.schema
    name = f'"{schema}"."{table}"' if schema else f'"{table}"'
    with provider._engine.connect() as conn:
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {name}")).scalar_one())
