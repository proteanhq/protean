"""Tests for ``protean db check`` on SQLite.

The aggregate ``Order`` has the table ``order``, a reserved word, so each
statement and each line of output has to handle a quoted name.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy

from tests.support.migrations import (
    MigrationsProject,
    block_alembic,
    make_project,
    no_change_model,
    raw_index_model,
)

pytestmark = [pytest.mark.sqlite, pytest.mark.no_test_domain]

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

ORDER_WITH_LONGER_NAME = """
@domain.aggregate
class Order:
    name = String(max_length=100)
"""

ORDER_WITH_RAW_INDEX = """
@domain.aggregate(indexes=[
    Index.from_sql(
        "sqlite",
        'CREATE INDEX ix_order_raw ON "order" (lower(name))',
        name="ix_order_raw",
    ),
])
class Order:
    name = String(max_length=50)
"""

PRODUCT_MODEL = """

@domain.aggregate
class Product:
    title = String(max_length=50)
"""


MATCHES = "The database matches the table definitions."


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def database(tmp_path) -> Path:
    return tmp_path / "shop.db"


@pytest.fixture
def project(tmp_path, monkeypatch, database) -> Iterator[MigrationsProject]:
    """A project in ``tmp_path`` whose default provider is a SQLite file."""
    project = make_project(
        tmp_path,
        monkeypatch,
        {"default": {"provider": "sqlite", "database_uri": sqlite_url(database)}},
    )

    yield project

    project.forget_modules()


def start_at_head(project: MigrationsProject, model: str) -> None:
    """Write ``model``, create the migrations folder and bring the database to head."""
    project.write(model)
    project.run_ok("init")
    project.run_ok("migrate", "-m", "initial")
    project.run_ok("upgrade")


def execute(database: Path, statement: str) -> None:
    engine = sqlalchemy.create_engine(sqlite_url(database))
    try:
        with engine.begin() as connection:
            connection.execute(sqlalchemy.text(statement))
    finally:
        engine.dispose()


def schema_state(database: Path) -> tuple[list[str], dict[str, list[str]]]:
    """The ``alembic_version`` rows and the column names of every table."""
    engine = sqlalchemy.create_engine(sqlite_url(database))
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
                table: [column["name"] for column in inspector.get_columns(table)]
                for table in inspector.get_table_names()
            }
    finally:
        engine.dispose()
    return versions, tables


def one_line(text: str) -> str:
    """``text`` with its line breaks and runs of spaces made single spaces."""
    return " ".join(text.split())


class TestCheckReportsAgreement:
    def test_an_unchanged_model_exits_0(self, project):
        start_at_head(project, ORDER)

        result = project.run("check")

        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == MATCHES
        assert result.stderr == ""

    def test_a_table_the_domain_does_not_declare_is_ignored(self, project, database):
        start_at_head(project, ORDER)
        execute(database, "CREATE TABLE legacy (id INTEGER PRIMARY KEY, code TEXT)")

        result = project.run("check")

        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == MATCHES

    @pytest.mark.parametrize(
        "model", [no_change_model("sqlite"), raw_index_model("sqlite")]
    )
    def test_declared_and_raw_indexes_report_no_difference(self, project, model):
        start_at_head(project, model)

        result = project.run("check")

        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == MATCHES


class TestCheckReportsDifferences:
    def test_a_field_without_a_migration(self, project):
        start_at_head(project, ORDER)
        project.write(ORDER_WITH_DISCOUNT)

        result = project.run("check")

        assert result.exit_code == 1, result.output
        assert result.stdout.splitlines() == ["add_column order.discount"]
        assert result.stderr == ""

    def test_a_column_added_by_hand(self, project, database):
        start_at_head(project, ORDER)
        execute(database, 'ALTER TABLE "order" ADD COLUMN extra VARCHAR(10)')

        result = project.run("check")

        assert result.exit_code == 1, result.output
        assert result.stdout.splitlines() == ["remove_column order.extra"]

    def test_a_longer_column(self, project):
        start_at_head(project, ORDER)
        project.write(ORDER_WITH_LONGER_NAME)

        result = project.run("check")

        assert result.exit_code == 1, result.output
        assert result.stdout.splitlines() == ["modify_type order.name"]

    def test_a_raw_index_the_table_lacks(self, project):
        start_at_head(project, ORDER)
        project.write(ORDER_WITH_RAW_INDEX)

        result = project.run("check")

        assert result.exit_code == 1, result.output
        assert result.stdout.splitlines() == ["add_index order.ix_order_raw"]

    def test_a_table_without_a_migration(self, project):
        start_at_head(project, ORDER)
        project.write(ORDER + PRODUCT_MODEL)

        result = project.run("check")

        assert result.exit_code == 1, result.output
        assert result.stdout.splitlines() == ["add_table product"]

    def test_the_lines_are_sorted(self, project, database):
        start_at_head(project, ORDER)
        execute(database, 'ALTER TABLE "order" ADD COLUMN extra VARCHAR(10)')
        project.write(ORDER_WITH_DISCOUNT)

        result = project.run("check")

        assert result.exit_code == 1, result.output
        assert result.stdout.splitlines() == [
            "add_column order.discount",
            "remove_column order.extra",
        ]


class TestCheckWritesNothing:
    def test_the_version_columns_and_folder_stay(self, project, database):
        start_at_head(project, ORDER)
        execute(database, 'ALTER TABLE "order" ADD COLUMN extra VARCHAR(10)')
        project.write(ORDER_WITH_DISCOUNT)
        before = schema_state(database)
        written = project.versions()
        assert before[0] != []

        result = project.run("check")

        assert result.exit_code == 1, result.output
        assert schema_state(database) == before
        assert project.versions() == written


class TestCheckRefusesADatabaseBehindHead:
    def test_one_migration_behind(self, project):
        start_at_head(project, ORDER)
        project.write(ORDER_WITH_DISCOUNT)
        project.run_ok("migrate", "-m", "add discount")
        project.run_ok("upgrade")
        project.run_ok("downgrade", "-1")

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "protean db upgrade" in one_line(result.stderr)
        assert result.stdout == ""

    def test_a_database_never_upgraded(self, project, database):
        project.write(ORDER)
        project.run_ok("init")
        project.run_ok("migrate", "-m", "initial")

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "protean db upgrade" in one_line(result.stderr)
        assert result.stdout == ""
        assert schema_state(database)[0] == []

    def test_an_empty_folder_and_an_empty_database_report_each_table(self, project):
        project.write(ORDER)
        project.run_ok("init")

        result = project.run("check")

        assert result.exit_code == 1, result.output
        assert result.stdout.splitlines() == ["add_table order"]


class TestCheckEnvironmentErrors:
    def test_a_provider_without_migrations(self, project):
        start_at_head(project, ORDER)
        project.databases = {"default": {"provider": "memory"}}
        project.write(ORDER)

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "SCHEMA_MIGRATIONS" in one_line(result.stderr)
        assert result.stdout == ""

    def test_an_unmanaged_provider(self, project, database):
        start_at_head(project, ORDER)
        project.databases = {
            "default": {
                "provider": "sqlite",
                "database_uri": sqlite_url(database),
                "managed": False,
            }
        }
        project.write(ORDER)

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "managed = false" in one_line(result.stderr)
        assert result.stdout == ""

    def test_a_domain_that_does_not_load(self, project):
        start_at_head(project, ORDER)

        (project.root / "domain.py").unlink()

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "Error loading Protean domain" in one_line(result.stderr)
        assert result.stdout == ""

    def test_alembic_not_installed(self, project, monkeypatch):
        start_at_head(project, ORDER)
        block_alembic(monkeypatch)

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert 'pip install "protean[sqlite]"' in one_line(result.stderr)
        assert result.stdout == ""

    def test_a_missing_migrations_folder(self, project):
        project.write(ORDER)

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "No migrations found in 'migrations'" in one_line(result.stderr)
        assert result.stdout == ""

    def test_a_database_that_cannot_be_opened(self, project, tmp_path):
        start_at_head(project, ORDER)
        unreachable = tmp_path / "missing-folder" / "shop.db"
        project.databases = {
            "default": {"provider": "sqlite", "database_uri": sqlite_url(unreachable)}
        }
        project.write(ORDER)

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "Could not connect to database" in one_line(result.stderr)
        assert result.stdout == ""
