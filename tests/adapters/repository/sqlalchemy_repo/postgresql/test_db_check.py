"""``protean db check`` against PostgreSQL.

Each test creates a database of its own on the test server and drops it after.
PostgreSQL stores a primary key column NOT NULL while the model declares it
nullable, so an unchanged model passes only when ``check`` drops that
difference as ``migrate`` does.
"""

from collections.abc import Iterator

import pytest
import sqlalchemy

from tests.shared import POSTGRES_URI
from tests.support.migrations import (
    MigrationsProject,
    fresh_database,
    make_project,
    no_change_model,
)

pytestmark = [pytest.mark.postgresql, pytest.mark.no_test_domain]

ORDER = """
@domain.aggregate
class Order:
    name = String(max_length=50)
"""

ORDER_WITH_DISCOUNT = """
@domain.aggregate
class Order:
    name = String(max_length=50)
    discount = Integer()
"""

MATCHES = "The database matches the table definitions."


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


def start_at_head(project: MigrationsProject, model: str) -> None:
    project.write(model)
    project.run_ok("init")
    project.run_ok("migrate", "-m", "initial")
    project.run_ok("upgrade")


def execute(url: str, statement: str) -> None:
    engine = sqlalchemy.create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(sqlalchemy.text(statement))
    finally:
        engine.dispose()


def test_an_unchanged_model_exits_0(project):
    start_at_head(project, ORDER)

    result = project.run("check")

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == MATCHES


def test_an_unchanged_model_with_every_index_kind_exits_0(project):
    start_at_head(project, no_change_model("postgresql"))

    result = project.run("check")

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == MATCHES


def test_an_unchanged_model_in_a_custom_schema_exits_0(project, database):
    execute(database, "CREATE SCHEMA custom")
    project.databases = postgresql(database, schema="custom")
    start_at_head(project, ORDER)

    result = project.run("check")

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == MATCHES


def test_a_field_without_a_migration(project):
    start_at_head(project, ORDER)
    project.write(ORDER_WITH_DISCOUNT)

    result = project.run("check")

    assert result.exit_code == 1, result.output
    assert result.stdout.splitlines() == ["add_column order.discount"]


def test_a_column_added_by_hand(project, database):
    start_at_head(project, ORDER)
    execute(database, 'ALTER TABLE "order" ADD COLUMN extra VARCHAR(10)')

    result = project.run("check")

    assert result.exit_code == 1, result.output
    assert result.stdout.splitlines() == ["remove_column order.extra"]


def schema_state(url: str) -> tuple[list[str], dict[str, list[tuple]], list[str]]:
    """The ``alembic_version`` rows, the columns of each table and the indexes."""
    engine = sqlalchemy.create_engine(url)
    try:
        with engine.connect() as connection:
            versions = [
                row[0]
                for row in connection.execute(
                    sqlalchemy.text("SELECT version_num FROM alembic_version")
                )
            ]
            inspector = sqlalchemy.inspect(connection)
            tables = {
                table: [
                    (column["name"], str(column["type"]), column["nullable"])
                    for column in inspector.get_columns(table)
                ]
                for table in inspector.get_table_names()
            }
            indexes = sorted(
                row[0]
                for row in connection.execute(
                    sqlalchemy.text(
                        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
                    )
                )
            )
    finally:
        engine.dispose()
    return versions, tables, indexes


def test_a_check_that_finds_a_difference_writes_nothing(project, database):
    start_at_head(project, ORDER)
    execute(database, 'ALTER TABLE "order" ADD COLUMN extra VARCHAR(10)')
    project.write(ORDER_WITH_DISCOUNT)
    before = schema_state(database)
    assert before[0] != []

    result = project.run("check")

    assert result.exit_code == 1, result.output
    assert schema_state(database) == before
