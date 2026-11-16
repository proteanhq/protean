"""``protean db migrate``, ``upgrade`` and ``downgrade`` against PostgreSQL.

Each test creates a database of its own on the test server and drops it after.
"""

from collections.abc import Iterator

import pytest
import sqlalchemy

from tests.shared import POSTGRES_URI
from tests.support.migrations import (
    PRODUCT,
    MigrationsProject,
    assert_no_change_at_head,
    assert_raw_indexes_migrate,
    columns,
    fresh_database,
    make_project,
    migrate_add_field_and_upgrade,
    row_count,
    table_names,
)

pytestmark = [pytest.mark.postgresql, pytest.mark.no_test_domain]

# Nothing listens on port 1, so a connection attempt fails at once.
UNREACHABLE_URI = "postgresql://postgres:postgres@localhost:1/postgres"


@pytest.fixture
def database() -> Iterator[str]:
    with fresh_database(POSTGRES_URI) as url:
        yield url


def postgresql(url: str, **extra: str) -> dict:
    return {"default": {"provider": "postgresql", "database_uri": url, **extra}}


@pytest.fixture
def project(tmp_path, monkeypatch, database) -> Iterator[MigrationsProject]:
    project = make_project(tmp_path, monkeypatch, postgresql(database), "uuid")
    yield project
    project.forget_modules()


def test_a_new_field_becomes_a_column_and_the_rows_stay(project, database):
    migrate_add_field_and_upgrade(project)

    assert columns(database, "product") == {"id", "name", "price", "_version"}
    assert row_count(database, "product") == 2


def test_an_unchanged_model_writes_no_file(project):
    assert_no_change_at_head(project, "postgresql")


def test_an_unchanged_model_in_a_custom_schema_writes_no_file(project, database):
    engine = sqlalchemy.create_engine(database)
    try:
        with engine.begin() as connection:
            connection.execute(sqlalchemy.text("CREATE SCHEMA custom"))
    finally:
        engine.dispose()
    project.databases = postgresql(database, schema="custom")

    assert_no_change_at_head(project, "postgresql")

    assert {"product", "counter", "alembic_version"} <= table_names(
        database, schema="custom"
    )
    assert table_names(database, schema="public") == set()


def test_raw_indexes_are_created_and_compared(project, database):
    assert_raw_indexes_migrate(project, database, "postgresql")


def test_upgrade_sql_runs_while_the_database_is_unreachable(project):
    project.write(PRODUCT)
    project.run_ok("init")
    project.run_ok("migrate", "-m", "initial")
    project.databases = postgresql(UNREACHABLE_URI)
    project.write(PRODUCT)

    result = project.run_ok("upgrade", "base:head", "--sql")

    assert "CREATE TABLE public.product" in result.output
    assert "Upgraded" not in result.output
