"""Tests for ``protean db migrate``, ``upgrade`` and ``downgrade`` on SQLite."""

import os
import re
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.support.migrations import (
    PRODUCT,
    PRODUCT_WITH_PRICE,
    MigrationsProject,
    assert_no_change_at_head,
    assert_raw_indexes_migrate,
    columns,
    make_project,
    migrate_add_field_and_upgrade,
    raw_index_model,
    row_count,
    table_names,
)

pytestmark = [pytest.mark.sqlite, pytest.mark.no_test_domain]

# Rich styles Click usage errors and draws them in a panel that wraps to the
# terminal width, so a match on the raw output depends on colour and width.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_PANEL_RE = re.compile(r"[\s\u2500-\u257f]+")


def plain(output: str) -> str:
    """Return ``output`` without ANSI codes, panel borders or line breaks."""
    return _PANEL_RE.sub(" ", _ANSI_RE.sub("", output))


PRODUCT_WITH_LONGER_NAME = """
@domain.aggregate
class Product:
    name = String(max_length=100)
"""

SHOP_PRODUCT = """
@domain.aggregate(provider="shop")
class Product:
    name = String(max_length=50)
"""

# Each index kind a SQLite table copy would lose, on a ``name`` of ``max_length``.
COPIED_INDEXES_MODEL = """
@domain.aggregate(indexes=[
    Index("price", desc=["price"], name="ix_product_price_desc"),
    Index.from_sql(
        "sqlite",
        "CREATE INDEX ix_product_raw ON product (lower(name))",
        name="ix_product_raw",
    ),
    Index.from_sql(
        "sqlite",
        "CREATE INDEX ix_product_raw_price ON product (price)",
        name="ix_product_raw_price",
    ),
])
class Product:
    name = String(max_length={max_length})
    price = Integer()
"""

# A ``name`` of ``max_length``, with or without a named DESC index.
DESC_INDEX_MODEL = """
@domain.aggregate(indexes=[{index}])
class Product:
    name = String(max_length={max_length})
    price = Integer()
"""
DESC_INDEX = 'Index("price", desc=["price"], name="ix_product_price_desc")'

WITH_EVENT_SOURCED_LEDGER = """
@domain.aggregate
class Product:
    name = String(max_length=50)


@domain.aggregate(event_sourced=True)
class Ledger:
    title = String(max_length=50)
"""


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


def run_alembic(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PROTEAN_NO_AUTO_LOGGING": "1"}
    env.pop("PROTEAN_DOMAIN", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", *args],
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def index_sql(database: Path) -> dict[str, str]:
    """The ``CREATE INDEX`` statement of each named index, from ``sqlite_master``."""
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
        ).fetchall()
    finally:
        connection.close()
    return dict(rows)


def start_at_head(project: MigrationsProject, model: str) -> None:
    """Write ``model``, create the migrations folder and bring the database to head."""
    project.write(model)
    project.run_ok("init")
    project.run_ok("migrate", "-m", "initial")
    project.run_ok("upgrade")


class TestMigrateAndUpgrade:
    def test_a_new_field_becomes_a_column_and_the_rows_stay(self, project, database):
        migrate_add_field_and_upgrade(project)

        assert columns(sqlite_url(database), "product") == {
            "id",
            "name",
            "price",
            "_version",
        }
        assert row_count(sqlite_url(database), "product") == 2

    def test_migrate_reports_the_file_it_wrote(self, project):
        project.write(PRODUCT)
        project.run_ok("init")

        result = project.run_ok("migrate", "-m", "initial")

        [written] = project.versions()
        assert result.output.replace("\n", "") == f"Wrote migration {written}."

    def test_a_longer_field_alters_the_column_in_batch_mode(self, project, database):
        start_at_head(project, PRODUCT)
        project.add_products("Lamp", "Desk")
        project.write(PRODUCT_WITH_LONGER_NAME)

        project.run_ok("migrate", "-m", "longer name")
        project.run_ok("upgrade")

        latest = next(v for v in project.versions() if "longer_name" in v.name)
        source = latest.read_text(encoding="utf-8")
        assert "batch_alter_table" in source
        assert "sa.String(length=100)" in source
        assert row_count(sqlite_url(database), "product") == 2

    def test_upgrade_reports_the_revision(self, project):
        project.write(PRODUCT)
        project.run_ok("init")
        project.run_ok("migrate", "-m", "initial")

        result = project.run_ok("upgrade")

        assert "Upgraded the database to head." in result.output

    def test_an_event_sourced_aggregate_gets_no_table(self, project, database):
        project.write(WITH_EVENT_SOURCED_LEDGER)
        project.run_ok("init")
        project.run_ok("migrate", "-m", "initial")
        project.run_ok("upgrade")

        [initial] = project.versions()
        source = initial.read_text(encoding="utf-8")
        assert "op.create_table('product'" in source
        assert "ledger" not in source
        assert "ledger" not in table_names(sqlite_url(database))

    def test_migrate_needs_a_message(self, project):
        project.write(PRODUCT)
        project.run_ok("init")

        result = project.run("migrate")

        assert result.exit_code == 2
        assert "Missing option '--message'" in plain(result.output)
        assert project.versions() == []

    def test_migrate_refuses_a_blank_message(self, project):
        project.write(PRODUCT)
        project.run_ok("init")

        result = project.run("migrate", "-m", "  ")

        assert result.exit_code == 2
        assert "describe what the migration changes" in plain(result.output)
        assert project.versions() == []

    def test_the_provider_comes_from_the_folder(self, project, tmp_path):
        shop = tmp_path / "shop.db"
        project.databases = {
            "default": {"provider": "memory"},
            "shop": {"provider": "sqlite", "database_uri": sqlite_url(shop)},
        }
        project.write(SHOP_PRODUCT)
        project.run_ok("init", "--provider", "shop", "--directory", "migrations/shop")

        project.run_ok("migrate", "-m", "initial", "--directory", "migrations/shop")
        project.run_ok("upgrade", "--directory", "migrations/shop")

        assert "product" in table_names(sqlite_url(shop))


class TestMigrateFindsNoChange:
    def test_an_unchanged_model_writes_no_file(self, project):
        assert_no_change_at_head(project, "sqlite")

    def test_a_table_the_domain_does_not_own_is_left_alone(self, project, database):
        start_at_head(project, PRODUCT)
        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE legacy (id INTEGER PRIMARY KEY)")
            connection.commit()
        finally:
            connection.close()

        result = project.run_ok("migrate", "-m", "nothing")
        project.run_ok("upgrade")

        assert "No changes detected; no migration written." in result.output
        assert len(project.versions()) == 1
        assert "legacy" in table_names(sqlite_url(database))


class TestRawIndexes:
    def test_raw_indexes_are_created_and_compared(self, project, database):
        assert_raw_indexes_migrate(project, sqlite_url(database), "sqlite")

    def test_the_initial_migration_holds_the_raw_index_sql(self, project):
        project.write(raw_index_model("sqlite"))
        project.run_ok("init")
        project.run_ok("migrate", "-m", "initial")

        [initial] = project.versions()
        source = initial.read_text(encoding="utf-8")
        assert "CREATE INDEX ix_product_raw ON product (lower(name))" in source
        assert "ix_product_other" not in source


class TestATableCopyKeepsItsIndexes:
    """On SQLite, a column change copies the table, and the copy is built from
    reflection, which leaves out expression indexes and DESC order."""

    def test_upgrade_and_downgrade_keep_every_index(self, project, database):
        start_at_head(project, COPIED_INDEXES_MODEL.format(max_length=50))
        before = index_sql(database)
        assert {"ix_product_price_desc", "ix_product_raw", "ix_product_raw_price"} <= (
            before.keys()
        )
        project.write(COPIED_INDEXES_MODEL.format(max_length=100))

        project.run_ok("migrate", "-m", "longer name")
        project.run_ok("upgrade")

        latest = next(v for v in project.versions() if "longer_name" in v.name)
        assert "batch_alter_table" in latest.read_text(encoding="utf-8")
        assert index_sql(database) == before
        result = project.run_ok("migrate", "-m", "nothing")
        assert "No changes detected; no migration written." in result.output

        project.run_ok("downgrade", "-1")

        assert index_sql(database) == before

    def test_downgrade_restores_an_index_the_model_no_longer_declares(
        self, project, database
    ):
        """The downgrade rebuilds the index from the database, not the model."""
        start_at_head(project, DESC_INDEX_MODEL.format(index=DESC_INDEX, max_length=50))
        before = index_sql(database)
        assert "DESC" in before["ix_product_price_desc"]
        project.write(DESC_INDEX_MODEL.format(index="", max_length=100))

        project.run_ok("migrate", "-m", "drop index")
        project.run_ok("upgrade")

        assert "ix_product_price_desc" not in index_sql(database)

        project.run_ok("downgrade", "-1")

        assert index_sql(database) == before

    def test_only_the_dropped_column_rebuilds_the_indexes(self, project, database):
        """Adding a column runs without a copy; dropping it in the downgrade copies."""
        start_at_head(project, raw_index_model("sqlite"))
        project.write(
            raw_index_model("sqlite").replace(
                "price = Integer()", "price = Integer()\n    stock = Integer()"
            )
        )

        project.run_ok("migrate", "-m", "add stock")
        project.run_ok("upgrade")

        latest = next(v for v in project.versions() if "add_stock" in v.name)
        upgrade, downgrade = latest.read_text(encoding="utf-8").split("def downgrade")
        assert "DROP INDEX IF EXISTS" not in upgrade
        assert "DROP INDEX IF EXISTS ix_product_raw" in downgrade
        assert "ix_product_raw" in index_sql(database)

        project.run_ok("downgrade", "-1")

        assert "ix_product_raw" in index_sql(database)


class TestDowngrade:
    def test_minus_one_undoes_the_last_migration(self, project, database):
        migrate_add_field_and_upgrade(project)

        result = project.run_ok("downgrade", "-1")

        assert "Downgraded the database to -1." in result.output
        assert columns(sqlite_url(database), "product") == {"id", "name", "_version"}
        assert row_count(sqlite_url(database), "product") == 2

    def test_sql_prints_the_script_without_connecting(self, project, tmp_path):
        start_at_head(project, PRODUCT)
        unreachable = tmp_path / "missing-folder" / "shop.db"
        project.databases = {
            "default": {"provider": "sqlite", "database_uri": sqlite_url(unreachable)}
        }
        project.write(PRODUCT)

        result = project.run_ok("downgrade", "head:base", "--sql")

        assert "DROP TABLE product" in result.output
        assert "Downgraded" not in result.output
        assert not unreachable.parent.exists()

    def test_sql_without_a_range_is_refused(self, project):
        start_at_head(project, PRODUCT)

        result = project.run("downgrade", "-1", "--sql")

        assert result.exit_code != 0
        assert "Error: downgrade with --sql requires <fromrev>:<torev>" in result.output

    def test_upgrade_sql_prints_the_script(self, project, database):
        project.write(PRODUCT)
        project.run_ok("init")
        project.run_ok("migrate", "-m", "initial")

        result = project.run_ok("upgrade", "--sql")

        assert "CREATE TABLE product" in result.output
        assert "Upgraded" not in result.output
        assert "product" not in table_names(sqlite_url(database))


class TestTheCommandsCheckTheProvider:
    @pytest.mark.parametrize(
        "command",
        [("migrate", "-m", "initial"), ("upgrade",), ("downgrade", "-1")],
    )
    def test_a_provider_without_migrations_is_refused(self, project, command):
        project.write(PRODUCT)
        project.run_ok("init")
        project.databases = {"default": {"provider": "memory"}}
        project.write(PRODUCT)

        result = project.run(*command)

        assert result.exit_code != 0
        assert "Provider 'default' (memory)" in result.output
        assert "SCHEMA_MIGRATIONS" in result.output
        assert project.versions() == []

    @pytest.mark.parametrize(
        "command",
        [("migrate", "-m", "initial"), ("upgrade",), ("downgrade", "-1")],
    )
    def test_a_missing_migrations_folder_is_reported(self, project, command):
        project.write(PRODUCT)

        result = project.run(*command)

        assert result.exit_code != 0
        assert "No migrations found in 'migrations'" in result.output
        assert "protean db init" in result.output
        assert not (project.root / "migrations").exists()


class TestPlainAlembic:
    def test_alembic_upgrade_head_runs_the_written_migrations(self, project, database):
        project.write(PRODUCT_WITH_PRICE)
        project.run_ok("init")
        project.run_ok("migrate", "-m", "initial")

        completed = run_alembic(project.root, "upgrade", "head")

        assert completed.returncode == 0, completed.stderr
        assert columns(sqlite_url(database), "product") == {
            "id",
            "name",
            "price",
            "_version",
        }

    def test_alembic_sql_runs_without_connecting(self, project, tmp_path):
        project.write(PRODUCT)
        project.run_ok("init")
        project.run_ok("migrate", "-m", "initial")
        unreachable = tmp_path / "missing-folder" / "shop.db"
        project.databases = {
            "default": {"provider": "sqlite", "database_uri": sqlite_url(unreachable)}
        }
        project.write(PRODUCT)

        completed = run_alembic(project.root, "upgrade", "head", "--sql")

        assert completed.returncode == 0, completed.stderr
        assert "CREATE TABLE product" in completed.stdout
        assert not unreachable.parent.exists()
