"""Run the ``protean db`` migration commands on a domain written to a folder.

A test writes ``domain.py`` into a folder, runs a command through Typer's
``CliRunner``, rewrites the model, and runs the next command. Each command loads
the domain from the file again, so it sees the rewritten model. Each loaded
domain is closed after the command, so no connection stays open to the test's
database.

The fresh-database helpers create a database of its own for one test on a
shared server and drop it afterwards.
"""

from __future__ import annotations

import contextlib
import shutil
import sys
import textwrap
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import sqlalchemy
from click.testing import Result
from sqlalchemy.engine import make_url
from typer.testing import CliRunner

from protean.cli import app
from protean.utils.domain_discovery import derive_domain

runner = CliRunner()

MIGRATOR_MODULE = "protean.adapters.repository.schema_migrator.alembic_migrator"


class _AlembicNotInstalled:
    """A meta path finder that fails ``import alembic`` as an install without it does."""

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        if fullname == "alembic" or fullname.startswith("alembic."):
            raise ModuleNotFoundError("No module named 'alembic'", name="alembic")


def block_alembic(monkeypatch: Any) -> None:
    """Make ``import alembic`` fail for the rest of the test."""
    for name in [n for n in sys.modules if n == "alembic" or n.startswith("alembic.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.delitem(sys.modules, MIGRATOR_MODULE, raising=False)
    monkeypatch.setattr(sys, "meta_path", [_AlembicNotInstalled(), *sys.meta_path])


DOMAIN_HEADER = """
from protean import Domain, Index
from protean.fields import Auto, DateTime, Dict, Integer, List, String
from protean.utils.query import Q

domain = Domain(name="Shop")
domain.config["identity_type"] = {identity_type!r}
domain.config["databases"].update({databases!r})
"""

# The model the add-field flow starts from.
PRODUCT = """
@domain.aggregate
class Product:
    name = String(max_length=50)
"""

PRODUCT_WITH_PRICE = """
@domain.aggregate
class Product:
    name = String(max_length=50)
    price = Integer()
"""


def no_change_model(dialect: str) -> str:
    """A model with every index kind ``dialect`` supports and custom column types.

    It has a domain-generated identity, a database-assigned identity, a list, a
    dict, a datetime and a unique field, and a plain, unique, composite, DESC,
    partial and covering index where the dialect supports each.
    """
    indexes = [
        'Index("name")',
        'Index("sku", unique=True)',
        'Index("name", "price", name="ix_product_name_price")',
        'Index("price", desc=["price"], name="ix_product_price_desc")',
    ]
    if dialect in ("sqlite", "postgresql"):
        indexes.append('Index("name", where=Q(price__gt=0), name="ix_product_paid")')
    if dialect in ("postgresql", "mssql"):
        indexes.append(
            'Index("sku", include=["price"], name="ix_product_sku_covering")'
        )
    return f"""
@domain.aggregate(indexes=[{", ".join(indexes)}])
class Product:
    name = String(max_length=50)
    sku = String(max_length=20, unique=True)
    price = Integer()
    tags = List()
    extra = Dict()
    released_at = DateTime()


@domain.aggregate
class Counter:
    id = Auto(increment=True, identifier=True)
    label = String(max_length=20)
"""


# A raw index on ``product.name`` per dialect, an expression index where the
# database has them.
RAW_NAME_INDEX = {
    "sqlite": "CREATE INDEX ix_product_raw ON product (lower(name))",
    "postgresql": "CREATE INDEX ix_product_raw ON product (lower(name))",
    "mysql": "CREATE INDEX ix_product_raw ON product ((lower(name)))",
    "mariadb": "CREATE INDEX ix_product_raw ON product (name(10))",
    "mssql": "CREATE INDEX ix_product_raw ON product (name) WITH (FILLFACTOR = 80)",
}

RAW_PRICE_INDEX = "CREATE INDEX ix_product_raw_price ON product (price)"

OTHER_DIALECT_INDEX = "CREATE INDEX ix_product_other ON product (name)"


def raw_index_model(dialect: str, with_price_index: bool = False) -> str:
    """A ``Product`` with a raw index for ``dialect`` and one for another dialect.

    With ``with_price_index``, it has a second raw index for ``dialect``,
    ``ix_product_raw_price``.
    """
    other = "sqlite" if dialect != "sqlite" else "postgresql"
    indexes = [
        f'Index.from_sql("{dialect}", "{RAW_NAME_INDEX[dialect]}", name="ix_product_raw")',
        f'Index.from_sql("{other}", "{OTHER_DIALECT_INDEX}", name="ix_product_other")',
    ]
    if with_price_index:
        indexes.append(
            f'Index.from_sql("{dialect}", "{RAW_PRICE_INDEX}", name="ix_product_raw_price")'
        )
    return f"""
@domain.aggregate(indexes=[{", ".join(indexes)}])
class Product:
    name = String(max_length=50)
    price = Integer()
"""


def index_names(url: str, table: str) -> set[str]:
    """The names of the indexes on ``table``, read from the database catalog.

    SQLite is read from ``sqlite_master``, because SQLAlchemy skips expression
    indexes when it reflects a SQLite table.
    """
    engine = sqlalchemy.create_engine(url)
    try:
        with engine.connect() as connection:
            if engine.dialect.name == "sqlite":
                rows = connection.execute(
                    sqlalchemy.text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'index' AND tbl_name = :t"
                    ),
                    {"t": table},
                )
                return {row[0] for row in rows}
            return {
                index["name"]
                for index in sqlalchemy.inspect(connection).get_indexes(table)
                if index["name"]
            }
    finally:
        engine.dispose()


def assert_raw_indexes_migrate(
    project: MigrationsProject, url: str, dialect: str
) -> None:
    """Run the raw-index flow and check each step against the database.

    The initial migration creates the raw index for ``dialect`` and not the
    one for another dialect. A second ``migrate`` finds no change. A raw index
    added to the model gets a migration of its own, and its downgrade drops it.
    """
    project.write(raw_index_model(dialect))
    project.run_ok("init")
    project.run_ok("migrate", "-m", "initial")
    project.run_ok("upgrade")
    names = index_names(url, "product")
    assert "ix_product_raw" in names
    assert "ix_product_other" not in names

    result = project.run_ok("migrate", "-m", "nothing")
    assert "No changes detected; no migration written." in result.output

    project.write(raw_index_model(dialect, with_price_index=True))
    result = project.run_ok("migrate", "-m", "price index")
    assert "Wrote migration" in result.output
    project.run_ok("upgrade")
    assert {"ix_product_raw", "ix_product_raw_price"} <= index_names(url, "product")

    project.run_ok("downgrade", "-1")
    names = index_names(url, "product")
    assert "ix_product_raw_price" not in names
    assert "ix_product_raw" in names


class MigrationsProject:
    """A folder holding ``domain.py``, where the ``protean db`` commands run.

    The test must run from ``root``, so the default ``migrations`` folder and a
    relative SQLite URL resolve there.
    """

    def __init__(
        self, root: Path, databases: dict[str, Any], identity_type: str = "string"
    ) -> None:
        self.root = root
        self.databases = databases
        self.identity_type = identity_type

    def write(self, model: str) -> None:
        """Write ``domain.py`` with ``model``, the source of its elements."""
        header = DOMAIN_HEADER.format(
            identity_type=self.identity_type, databases=self.databases
        )
        (self.root / "domain.py").write_text(
            textwrap.dedent(header) + textwrap.dedent(model), encoding="utf-8"
        )
        # A rewrite of the same size within the same second matches the cached
        # bytecode's size and timestamp, so the import would load the old model.
        shutil.rmtree(self.root / "__pycache__", ignore_errors=True)

    def run(self, *args: str) -> Result:
        """Run ``protean db <args> --domain domain.py`` and return the result."""
        self.forget_modules()
        try:
            return runner.invoke(app, ["db", *args, "--domain", "domain.py"])
        finally:
            self._close_loaded_domain()
            self.forget_modules()

    def run_ok(self, *args: str) -> Result:
        """Run a command and fail the test when it does not exit 0."""
        result = self.run(*args)
        assert result.exit_code == 0, result.output
        return result

    @contextlib.contextmanager
    def domain(self) -> Iterator[Any]:
        """Load and initialize the domain, and yield it inside its context."""
        self.forget_modules()
        domain = derive_domain("domain.py")
        assert domain is not None
        domain.init()
        try:
            with domain.domain_context():
                yield domain
        finally:
            domain.close()
            self.forget_modules()

    def add_products(self, *names: str) -> None:
        """Save one ``Product`` per name through the repository."""
        with self.domain() as domain:
            product_cls = domain.registry.aggregates["domain.Product"].cls
            repository = domain.repository_for(product_cls)
            for name in names:
                repository.add(product_cls(name=name))

    def versions(self) -> list[Path]:
        """The migration files in ``migrations/versions``, sorted by file name."""
        return sorted((self.root / "migrations" / "versions").glob("*.py"))

    def forget_modules(self) -> None:
        """Drop every module imported from ``root``, so the next load reads the files."""
        for name, module in list(sys.modules.items()):
            module_file = getattr(module, "__file__", None) or ""
            if module_file.startswith(str(self.root)):
                del sys.modules[name]

    def _close_loaded_domain(self) -> None:
        module = sys.modules.get("domain")
        loaded = getattr(module, "domain", None)
        if loaded is not None:
            loaded.close()


def make_project(
    tmp_path: Path,
    monkeypatch: Any,
    databases: dict[str, Any],
    identity_type: str = "string",
) -> MigrationsProject:
    """A project in ``tmp_path``, which becomes the working folder for the test.

    ``monkeypatch`` restores the working folder, the environment and
    ``sys.path`` afterwards.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
    monkeypatch.setenv("PROTEAN_NO_AUTO_LOGGING", "1")
    monkeypatch.setattr(sys, "path", sys.path[:])
    return MigrationsProject(tmp_path, databases, identity_type)


def migrate_add_field_and_upgrade(project: MigrationsProject) -> None:
    """Run the add-field flow: two rows at head, then a new ``price`` column.

    Leaves the database at head with two migrations applied.
    """
    project.write(PRODUCT)
    project.run_ok("init")
    project.run_ok("migrate", "-m", "initial")
    project.run_ok("upgrade")
    project.add_products("Lamp", "Desk")

    project.write(PRODUCT_WITH_PRICE)
    result = project.run_ok("migrate", "-m", "add price")
    assert "Wrote migration" in result.output
    project.run_ok("upgrade")


def assert_no_change_at_head(project: MigrationsProject, dialect: str) -> None:
    """Bring the database to head for ``no_change_model``, then migrate again."""
    project.write(no_change_model(dialect))
    project.run_ok("init")
    project.run_ok("migrate", "-m", "initial")
    project.run_ok("upgrade")
    written = project.versions()
    assert len(written) == 1

    result = project.run_ok("migrate", "-m", "nothing")

    assert "No changes detected; no migration written." in result.output
    assert project.versions() == written


def columns(url: str, table: str, schema: str | None = None) -> set[str]:
    """The column names of ``table``, reflected from the database."""
    engine = sqlalchemy.create_engine(url)
    try:
        return {
            column["name"]
            for column in sqlalchemy.inspect(engine).get_columns(table, schema=schema)
        }
    finally:
        engine.dispose()


def table_names(url: str, schema: str | None = None) -> set[str]:
    engine = sqlalchemy.create_engine(url)
    try:
        return set(sqlalchemy.inspect(engine).get_table_names(schema=schema))
    finally:
        engine.dispose()


def row_count(url: str, table: str) -> int:
    engine = sqlalchemy.create_engine(url)
    try:
        with engine.connect() as connection:
            quoted = engine.dialect.identifier_preparer.quote_identifier(table)
            return int(
                connection.execute(
                    sqlalchemy.text(f"SELECT COUNT(*) FROM {quoted}")
                ).scalar_one()
            )
    finally:
        engine.dispose()


def _database_name() -> str:
    return f"protean_migrations_{uuid.uuid4().hex[:12]}"


@contextlib.contextmanager
def fresh_database(server_url: str) -> Iterator[str]:
    """Create an empty database on the server of ``server_url``; yield its URL.

    The database is dropped afterwards. Works on PostgreSQL, MySQL, MariaDB and
    SQL Server.
    """
    name = _database_name()
    admin = sqlalchemy.create_engine(server_url, isolation_level="AUTOCOMMIT")
    dialect = admin.dialect.name
    try:
        with admin.connect() as connection:
            connection.execute(sqlalchemy.text(f"CREATE DATABASE {name}"))
        try:
            yield (
                make_url(server_url)
                .set(database=name)
                .render_as_string(hide_password=False)
            )
        finally:
            with admin.connect() as connection:
                if dialect == "postgresql":
                    connection.execute(
                        sqlalchemy.text(f"DROP DATABASE {name} WITH (FORCE)")
                    )
                elif dialect == "mssql":
                    connection.execute(
                        sqlalchemy.text(
                            f"ALTER DATABASE {name} SET SINGLE_USER "
                            "WITH ROLLBACK IMMEDIATE"
                        )
                    )
                    connection.execute(sqlalchemy.text(f"DROP DATABASE {name}"))
                else:
                    connection.execute(sqlalchemy.text(f"DROP DATABASE {name}"))
    finally:
        admin.dispose()
