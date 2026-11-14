"""Tests for ``protean db check`` on SQLite.

The aggregate ``Order`` has the table ``order``, a reserved word, so each
statement and each line of output has to handle a quoted name.
"""

import re
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy

from protean.adapters.repository.memory import MemoryProvider
from protean.adapters.repository.sqlalchemy import SAProvider
from protean.port.provider import BaseProvider
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

ORDER_WITH_STATUS = """
@domain.aggregate
class Order:
    name = String(max_length=50)
    status = String(max_length=10)
"""

ORDER_WITH_UNIQUE_FIELDS = """
@domain.aggregate
class Order:
    name = String(max_length=50, unique=True)
    status = String(max_length=10, unique=True)
"""

SHOP_ORDER = """
@domain.aggregate(provider="shop")
class Order:
    name = String(max_length=50)
"""

SHOP_ORDER_WITH_DISCOUNT = """
@domain.aggregate(provider="shop")
class Order:
    name = String(max_length=50)
    discount = Integer()
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


def schema_state(
    database: Path,
) -> tuple[list[str], dict[str, list[tuple[str, str, bool]]], list[str]]:
    """The ``alembic_version`` rows, the columns of every table and the indexes.

    A column is its name, type and nullability. The indexes are read from
    ``sqlite_master``, because SQLAlchemy skips expression indexes when it
    reflects a SQLite table.
    """
    engine = sqlalchemy.create_engine(sqlite_url(database))
    try:
        with engine.connect() as connection:
            inspector = sqlalchemy.inspect(connection)
            tables = {
                table: [
                    (column["name"], str(column["type"]), column["nullable"])
                    for column in inspector.get_columns(table)
                ]
                for table in inspector.get_table_names()
            }
            versions = (
                [
                    row[0]
                    for row in connection.execute(
                        sqlalchemy.text("SELECT version_num FROM alembic_version")
                    )
                ]
                if "alembic_version" in tables
                else []
            )
            indexes = sorted(
                row[0]
                for row in connection.execute(
                    sqlalchemy.text(
                        "SELECT name FROM sqlite_master WHERE type = 'index'"
                    )
                )
            )
    finally:
        engine.dispose()
    return versions, tables, indexes


def revision_id(path: Path) -> str:
    """The revision a migration file declares."""
    found = re.search(
        r"^revision: str = '(\w+)'$", path.read_text("utf-8"), re.MULTILINE
    )
    assert found is not None
    return found.group(1)


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
    # SQLAlchemy warns that it skips an expression index when it reflects a
    # SQLite table; ``check`` hides that warning as ``migrate`` does.
    @pytest.mark.filterwarnings(
        "error:Skipped unsupported reflection:sqlalchemy.exc.SAWarning"
    )
    def test_declared_and_raw_indexes_report_no_difference(self, project, model):
        start_at_head(project, model)

        result = project.run("check")

        assert result.exit_code == 0, result.output
        assert result.stdout.strip() == MATCHES
        assert result.stderr == ""

    def test_a_second_provider_through_directory(self, project, tmp_path):
        shop = tmp_path / "shop-orders.db"
        project.databases = {
            "default": {"provider": "memory"},
            "shop": {"provider": "sqlite", "database_uri": sqlite_url(shop)},
        }
        project.write(SHOP_ORDER)
        project.run_ok("init", "--provider", "shop", "--directory", "migrations/shop")
        project.run_ok("migrate", "-m", "initial", "--directory", "migrations/shop")
        project.run_ok("upgrade", "--directory", "migrations/shop")

        result = project.run("check", "--directory", "migrations/shop")

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
        # ``compare_metadata`` reports the column before the raw index is
        # added, so only the sort puts ``add_index`` first.
        start_at_head(project, ORDER)
        execute(database, 'ALTER TABLE "order" ADD COLUMN extra VARCHAR(10)')
        project.write(ORDER_WITH_RAW_INDEX)

        result = project.run("check")

        assert result.exit_code == 1, result.output
        assert result.stdout.splitlines() == [
            "add_index order.ix_order_raw",
            "remove_column order.extra",
        ]

    def test_an_unnamed_constraint_names_its_columns(self, project):
        start_at_head(project, ORDER_WITH_STATUS)
        project.write(ORDER_WITH_UNIQUE_FIELDS)

        result = project.run("check")

        assert result.exit_code == 1, result.output
        assert result.stdout.splitlines() == [
            "add_constraint order.name",
            "add_constraint order.status",
        ]

    def test_a_field_without_a_migration_for_a_second_provider(self, project, tmp_path):
        shop = tmp_path / "shop-orders.db"
        project.databases = {
            "default": {"provider": "memory"},
            "shop": {"provider": "sqlite", "database_uri": sqlite_url(shop)},
        }
        project.write(SHOP_ORDER)
        project.run_ok("init", "--provider", "shop", "--directory", "migrations/shop")
        project.run_ok("migrate", "-m", "initial", "--directory", "migrations/shop")
        project.run_ok("upgrade", "--directory", "migrations/shop")
        project.write(SHOP_ORDER_WITH_DISCOUNT)

        result = project.run("check", "--directory", "migrations/shop")

        assert result.exit_code == 1, result.output
        assert result.stdout.splitlines() == ["add_column order.discount"]


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
    def test_one_migration_behind(self, project, database):
        start_at_head(project, ORDER)
        project.write(ORDER_WITH_DISCOUNT)
        project.run_ok("migrate", "-m", "add discount")
        project.run_ok("upgrade")
        project.run_ok("downgrade", "-1")
        before = schema_state(database)

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "Run `protean db upgrade` first." in one_line(result.stderr)
        assert result.stdout == ""
        assert schema_state(database) == before

    def test_a_database_never_upgraded(self, project, database):
        project.write(ORDER)
        project.run_ok("init")
        project.run_ok("migrate", "-m", "initial")

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "protean db upgrade" in one_line(result.stderr)
        assert result.stdout == ""
        assert schema_state(database)[0] == []

    def test_a_revision_the_folder_does_not_have(self, project):
        start_at_head(project, ORDER)
        for path in project.versions():
            path.unlink()

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "which the migrations folder does not have" in one_line(result.stderr)
        assert "protean db upgrade" not in one_line(result.stderr)

    def test_two_heads_name_upgrade_heads(self, project):
        start_at_head(project, ORDER)
        (initial,) = project.versions()
        project.write(ORDER_WITH_DISCOUNT)
        project.run_ok("migrate", "-m", "add discount")
        (added,) = set(project.versions()) - {initial}
        # A copy of the new revision under another id also follows the initial
        # one, so the folder has two heads and the database is at neither.
        added.with_name("ffffffffffff_copy.py").write_text(
            added.read_text(encoding="utf-8").replace(
                f"revision: str = {revision_id(added)!r}",
                "revision: str = 'ffffffffffff'",
            ),
            encoding="utf-8",
        )

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "Run `protean db upgrade heads` first." in one_line(result.stderr)

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

    def test_a_failed_connection_hides_the_password(self, project, monkeypatch):
        start_at_head(project, ORDER)
        project.databases = {
            "default": {
                "provider": "memory",
                "database_uri": "postgresql://shop:s3cret@db.internal:5432/shop",
            }
        }
        project.write(ORDER)
        monkeypatch.setattr(MemoryProvider, "is_alive", lambda self: False)

        result = project.run("check")

        assert result.exit_code == 2, result.output
        stderr = one_line(result.stderr)
        assert "postgresql://shop:***@db.internal:5432/shop" in stderr
        assert "s3cret" not in result.output

    def test_a_domain_that_raises_on_import(self, project):
        start_at_head(project, ORDER)
        with (project.root / "domain.py").open("a", encoding="utf-8") as file:
            file.write("\ndef broken(:\n")

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "Error loading Protean domain: SyntaxError" in one_line(result.stderr)
        assert result.stdout == ""

    def test_a_revision_file_that_does_not_compile(self, project):
        start_at_head(project, ORDER)
        (revision,) = project.versions()
        with revision.open("a", encoding="utf-8") as file:
            file.write("\ndef broken(:\n")

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "Cannot compare the database with the migrations in 'migrations'" in (
            one_line(result.stderr)
        )
        assert result.stdout == ""

    def test_an_env_py_that_does_not_run_the_comparison(self, project):
        start_at_head(project, ORDER)
        (project.root / "migrations" / "env.py").write_text(
            "# Runs nothing.\n", encoding="utf-8"
        )
        shutil.rmtree(project.root / "migrations" / "__pycache__", ignore_errors=True)
        project.write(ORDER_WITH_DISCOUNT)

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "did not run Protean's migration environment" in one_line(result.stderr)
        assert result.stdout == ""

    def test_a_provider_that_does_not_implement_migrations(self, project, monkeypatch):
        start_at_head(project, ORDER)
        # An adapter that declares SCHEMA_MIGRATIONS and keeps the default
        # ``_schema_migrator``.
        monkeypatch.setattr(
            SAProvider, "_schema_migrator", BaseProvider._schema_migrator
        )

        result = project.run("check")

        assert result.exit_code == 2, result.output
        assert "does not implement schema migrations" in one_line(result.stderr)
        assert result.stdout == ""
