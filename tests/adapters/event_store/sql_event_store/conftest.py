from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from protean import Domain
from protean.adapters.event_store.sql.store import SqlEventStore
from tests.shared import POSTGRES_URI

# The PostgreSQL tests use their own schema, so they never touch the tables
# of the conformance run on the same database.
PG_SCHEMA = "protean_sql_store_tests"

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
