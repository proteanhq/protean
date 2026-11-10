"""Tests for the Alembic-backed schema migrator of the SQLAlchemy providers."""

import configparser
import contextlib
import importlib
import logging
import sys
import textwrap

import pytest
import sqlalchemy

from protean.adapters.repository import schema_migrator
from protean.adapters.repository.schema_migrator import (
    run_migrations,
    write_migrations_folder,
)
from protean.adapters.repository.sqlalchemy import (
    MssqlProvider,
    MysqlProvider,
    PostgresqlProvider,
    SqliteProvider,
    _alembic_extra,
)
from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.exceptions import ConfigurationError
from protean.fields import DateTime, String

alembic_command = pytest.importorskip("alembic.command")
from alembic.config import Config

pytestmark = [pytest.mark.sqlite, pytest.mark.no_test_domain]


@contextlib.contextmanager
def mock_running_thread(ident):
    """Act as if the thread ``ident`` were inside ``run_migrations``."""
    schema_migrator._running_thread = ident
    try:
        yield
    finally:
        schema_migrator._running_thread = None


MIGRATOR_MODULE = "protean.adapters.repository.schema_migrator.alembic_migrator"


class Product(BaseAggregate):
    name = String(max_length=50)
    released_at = DateTime()


@pytest.fixture
def domain(tmp_path):
    domain = Domain(name="Shop")
    domain.config["databases"]["default"] = {
        "provider": "sqlite",
        "database_uri": f"sqlite:///{tmp_path / 'shop.db'}",
    }
    domain.register(Product)
    domain.init(traverse=False)
    with domain.domain_context():
        yield domain


@pytest.fixture
def provider(domain):
    return domain.providers["default"]


def tables(provider) -> set[str]:
    return set(sqlalchemy.inspect(provider._engine).get_table_names())


class _AlembicNotInstalled:
    """A meta path finder that fails ``import alembic`` as an install without it does."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "alembic" or fullname.startswith("alembic."):
            raise ModuleNotFoundError("No module named 'alembic'", name="alembic")


def forget_alembic(monkeypatch):
    for name in [n for n in sys.modules if n == "alembic" or n.startswith("alembic.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.delitem(sys.modules, MIGRATOR_MODULE, raising=False)


def block_alembic(monkeypatch):
    """Make every ``import alembic`` fail, as on an install without it."""
    forget_alembic(monkeypatch)
    monkeypatch.setattr(sys, "meta_path", [_AlembicNotInstalled(), *sys.meta_path])


def write_domain_module(directory, databases_source: str) -> None:
    """Write ``shop.py``, a domain whose databases are set by ``databases_source``."""
    (directory / "shop.py").write_text(
        textwrap.dedent(
            """
            from protean import Domain

            domain = Domain(name="Shop")
            """
        )
        + databases_source,
        encoding="utf-8",
    )


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Run from ``tmp_path`` with a fresh import path and no ``shop`` module."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
    monkeypatch.setattr(sys, "path", sys.path[:])
    monkeypatch.delitem(sys.modules, "shop", raising=False)
    yield tmp_path
    sys.modules.pop("shop", None)


class TestWriteMigrationsFolder:
    def test_writes_without_alembic(self, tmp_path, monkeypatch):
        block_alembic(monkeypatch)
        importlib.reload(schema_migrator)

        schema_migrator.write_migrations_folder(
            tmp_path / "migrations", "domain.py", "default"
        )

        assert (tmp_path / "migrations" / "alembic.ini").is_file()
        assert (tmp_path / "migrations" / "versions").is_dir()

    def test_percent_in_a_value_reads_back_unchanged(self, tmp_path):
        write_migrations_folder(tmp_path / "m", "src/100%/domain.py", "p%1")

        parser = configparser.ConfigParser()
        parser.read(tmp_path / "m" / "alembic.ini", encoding="utf-8")
        assert parser["alembic"]["protean_domain"] == "src/100%/domain.py"
        assert parser["alembic"]["protean_provider"] == "p%1"

    def test_creates_missing_parents(self, tmp_path):
        write_migrations_folder(tmp_path / "a" / "b", "domain.py", "default")

        assert (tmp_path / "a" / "b" / "env.py").is_file()

    def test_refuses_a_file_at_the_path(self, tmp_path):
        target = tmp_path / "migrations"
        target.write_text("mine")

        with pytest.raises(ConfigurationError, match="exists and is not a folder"):
            write_migrations_folder(target, "domain.py", "default")

        assert target.read_text() == "mine"

    def test_refuses_a_dangling_symlink(self, tmp_path):
        target = tmp_path / "migrations"
        target.symlink_to(tmp_path / "nowhere")

        with pytest.raises(ConfigurationError, match="Cannot create migrations in"):
            write_migrations_folder(target, "domain.py", "default")

    def test_records_the_project_root_relative_to_the_folder(self, tmp_path):
        write_migrations_folder(
            tmp_path / "db" / "analytics", "domain.py", "default", tmp_path
        )

        parser = configparser.ConfigParser(defaults={"here": "/x/db/analytics"})
        parser.read(tmp_path / "db" / "analytics" / "alembic.ini", encoding="utf-8")
        assert parser["alembic"]["protean_root"] == "/x/db/analytics/../.."

    @pytest.mark.parametrize("existing", [False, True], ids=["new", "existing-empty"])
    def test_failed_write_leaves_nothing_behind(self, tmp_path, monkeypatch, existing):
        target = tmp_path / "migrations"
        if existing:
            target.mkdir()
        read_template = schema_migrator._template

        def failing_template(name):
            if name == "env.py.tmpl":
                raise OSError(28, "No space left on device")
            return read_template(name)

        monkeypatch.setattr(schema_migrator, "_template", failing_template)

        with pytest.raises(ConfigurationError, match="No space left on device"):
            write_migrations_folder(target, "domain.py", "default")

        if existing:
            assert list(target.iterdir()) == []
        else:
            assert not target.exists()

    def test_failed_write_keeps_another_writers_files(self, tmp_path, monkeypatch):
        target = tmp_path / "migrations"
        read_template = schema_migrator._template

        def racing_template(name):
            # Another process writes into the folder after the emptiness check.
            if name == "env.py.tmpl":
                (target / "env.py").write_text("theirs", encoding="utf-8")
            return read_template(name)

        monkeypatch.setattr(schema_migrator, "_template", racing_template)

        with pytest.raises(ConfigurationError, match="File exists"):
            write_migrations_folder(target, "domain.py", "default")

        assert [p.name for p in target.iterdir()] == ["env.py"]
        assert (target / "env.py").read_text(encoding="utf-8") == "theirs"


class TestMigratingThroughTheProvider:
    def test_stamp_uses_the_attached_provider(self, provider, tmp_path):
        migrator = provider.schema_migrator(tmp_path / "migrations")
        # The recorded domain does not exist. The command still runs, because
        # the provider travels in the Alembic config instead.
        migrator.init("no/such/domain.py")

        alembic_command.stamp(migrator.alembic_config(), "head")

        assert "alembic_version" in tables(provider)

    def test_autogenerate_and_upgrade_create_the_aggregate_table(
        self, provider, tmp_path
    ):
        migrator = provider.schema_migrator(tmp_path / "migrations")
        migrator.init("domain.py")
        config = migrator.alembic_config()

        alembic_command.revision(config, message="add product", autogenerate=True)
        versions = list((tmp_path / "migrations" / "versions").glob("*.py"))
        assert len(versions) == 1
        revision = versions[0].read_text()
        assert "create_table('product'" in revision
        assert "protean.adapters.repository.sqlalchemy.UTCDateTime(" in revision

        alembic_command.upgrade(config, "head")

        assert "product" in tables(provider)

    def test_offline_upgrade_renders_sql(self, provider, tmp_path, capsys):
        migrator = provider.schema_migrator(tmp_path / "migrations")
        migrator.init("domain.py")
        config = migrator.alembic_config()
        alembic_command.revision(config, message="add product", autogenerate=True)
        capsys.readouterr()

        alembic_command.upgrade(config, "head", sql=True)

        assert "CREATE TABLE product" in capsys.readouterr().out
        assert "product" not in tables(provider)

    def test_offline_upgrade_renders_bound_values_inline(
        self, provider, tmp_path, capsys
    ):
        migrator = provider.schema_migrator(tmp_path / "migrations")
        migrator.init("domain.py")
        config = migrator.alembic_config()
        script = alembic_command.revision(config, message="seed")
        path = tmp_path / "migrations" / "versions" / f"{script.revision}_seed.py"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                'def upgrade() -> None:\n    """Upgrade schema."""\n    pass',
                "def upgrade() -> None:\n"
                "    table = sa.table('product', sa.column('name', sa.String))\n"
                "    op.execute(table.insert().values(name='lamp'))",
            ),
            encoding="utf-8",
        )
        capsys.readouterr()

        alembic_command.upgrade(config, "head", sql=True)

        assert "VALUES ('lamp')" in capsys.readouterr().out


class TestRunMigrationsFromAlembicIni:
    def test_does_nothing_outside_an_alembic_run(self):
        assert run_migrations() is None

    def test_does_not_import_alembic_outside_a_run(self, monkeypatch):
        forget_alembic(monkeypatch)

        assert run_migrations() is None
        assert "alembic" not in sys.modules

    def test_refuses_a_run_while_another_thread_runs(self, provider, tmp_path):
        migrator = provider.schema_migrator(tmp_path / "migrations")
        migrator.init("domain.py")

        with mock_running_thread(-1):
            with pytest.raises(ConfigurationError, match="Another thread"):
                alembic_command.current(migrator.alembic_config())

        assert "alembic_version" not in tables(provider)

    def test_loads_the_domain_and_provider_the_ini_names(self, project, capsys):
        tmp_path = project
        write_domain_module(
            tmp_path,
            textwrap.dedent(
                f"""
                domain.config["databases"]["analytics"] = {{
                    "provider": "sqlite",
                    "database_uri": "sqlite:///{tmp_path / "analytics.db"}",
                }}
                """
            ),
        )
        # The default provider's folder sits beside the domain file, so loading
        # the domain during the analytics run imports its env.py.
        write_migrations_folder(tmp_path / "migrations", "shop.py", "default")
        write_migrations_folder(
            tmp_path / "migrations" / "analytics", "shop.py", "analytics"
        )

        config = Config(str(tmp_path / "migrations" / "analytics" / "alembic.ini"))

        script = alembic_command.revision(config, message="start")
        alembic_command.upgrade(config, "head", sql=True)

        # The env.py imported while the domain loads must not start a second
        # run inside this one, which would render the script twice.
        assert capsys.readouterr().out.count("CREATE TABLE alembic_version") == 1

        alembic_command.upgrade(config, "head")

        engine = sqlalchemy.create_engine(f"sqlite:///{tmp_path / 'analytics.db'}")
        try:
            with engine.connect() as connection:
                versions = connection.execute(
                    sqlalchemy.text("SELECT version_num FROM alembic_version")
                ).all()
        finally:
            engine.dispose()
        assert versions == [(script.revision,)]

    def test_ini_without_a_domain(self, tmp_path):
        write_migrations_folder(tmp_path / "m", "domain.py", "default")
        ini = tmp_path / "m" / "alembic.ini"
        ini.write_text(
            ini.read_text(encoding="utf-8").replace("protean_domain = domain.py\n", ""),
            encoding="utf-8",
        )

        with pytest.raises(ConfigurationError, match="no 'protean_domain' option"):
            alembic_command.current(Config(str(ini)))

    def test_ini_naming_an_unknown_provider(self, project):
        write_domain_module(project, "")
        write_migrations_folder(project / "m", "shop.py", "missing")

        with pytest.raises(
            ConfigurationError,
            match=r"Provider 'missing' is not configured\. Configured providers: default, memory\.",
        ):
            alembic_command.current(Config(str(project / "m" / "alembic.ini")))

    def test_ini_without_a_provider(self, project):
        write_domain_module(project, "")
        write_migrations_folder(project / "m", "shop.py", "")

        with pytest.raises(ConfigurationError, match="no 'protean_provider' option"):
            alembic_command.current(Config(str(project / "m" / "alembic.ini")))

    def test_ini_naming_a_domain_that_cannot_be_loaded(self, project):
        write_migrations_folder(project / "m", "nothing_here", "default")

        with pytest.raises(
            ConfigurationError, match="'nothing_here' named in .* cannot be loaded"
        ):
            alembic_command.current(Config(str(project / "m" / "alembic.ini")))

    def test_ini_naming_a_provider_without_the_capability(self, project):
        write_domain_module(project, "")
        write_migrations_folder(project / "m", "shop.py", "default")

        with pytest.raises(ConfigurationError, match="declares SCHEMA_MIGRATIONS"):
            alembic_command.current(Config(str(project / "m" / "alembic.ini")))

    def test_ini_naming_an_unmanaged_provider(self, project):
        write_domain_module(
            project,
            textwrap.dedent(
                """
                domain.config["databases"]["default"] = {
                    "provider": "sqlite",
                    "database_uri": "sqlite:///shop.db",
                    "managed": False,
                }
                """
            ),
        )
        write_migrations_folder(project / "m", "shop.py", "default")
        config = Config(str(project / "m" / "alembic.ini"))

        with pytest.raises(ConfigurationError, match="managed = false"):
            alembic_command.stamp(config, "head")

        if (project / "shop.db").exists():
            engine = sqlalchemy.create_engine(f"sqlite:///{project / 'shop.db'}")
            try:
                assert (
                    "alembic_version"
                    not in sqlalchemy.inspect(engine).get_table_names()
                )
            finally:
                engine.dispose()

    def test_plain_run_configures_logging_from_the_ini(self, project):
        write_domain_module(
            project,
            textwrap.dedent(
                """
                domain.config["databases"]["default"] = {
                    "provider": "sqlite",
                    "database_uri": "sqlite:///shop.db",
                }
                """
            ),
        )
        write_migrations_folder(project / "m", "shop.py", "default")
        alembic_logger = logging.getLogger("alembic")
        sqlalchemy_logger = logging.getLogger("sqlalchemy.engine")
        saved = [
            (alembic_logger, alembic_logger.level, alembic_logger.handlers[:]),
            (sqlalchemy_logger, sqlalchemy_logger.level, sqlalchemy_logger.handlers[:]),
        ]
        root = logging.getLogger()
        root_saved = (root.level, root.handlers[:])
        alembic_logger.setLevel(logging.NOTSET)
        try:
            alembic_command.current(Config(str(project / "m" / "alembic.ini")))

            assert alembic_logger.level == logging.INFO
        finally:
            for logger, level, handlers in saved:
                logger.setLevel(level)
                logger.handlers[:] = handlers
            root.setLevel(root_saved[0])
            root.handlers[:] = root_saved[1]


class TestAlembicMissing:
    @pytest.mark.parametrize(
        "provider_cls, extra",
        [
            (PostgresqlProvider, "protean[postgresql]"),
            (SqliteProvider, "protean[sqlite]"),
            (MssqlProvider, "protean[mssql]"),
            (MysqlProvider, "protean[mysql]"),
        ],
        ids=["db-postgresql", "db-sqlite", "db-mssql", "db-mysql"],
    )
    def test_error_names_the_extra(self, provider_cls, extra, monkeypatch, tmp_path):
        block_alembic(monkeypatch)
        provider = object.__new__(provider_cls)
        provider.name = "default"

        with pytest.raises(ConfigurationError) as exc_info:
            provider.schema_migrator(tmp_path / "migrations")

        assert f'pip install "{extra}"' in str(exc_info.value)
        assert not (tmp_path / "migrations").exists()

    def test_other_missing_modules_are_not_reported_as_alembic(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setitem(sys.modules, MIGRATOR_MODULE, None)
        provider = object.__new__(SqliteProvider)
        provider.name = "default"

        with pytest.raises(ModuleNotFoundError) as exc_info:
            provider.schema_migrator(tmp_path / "migrations")

        assert exc_info.value.name == MIGRATOR_MODULE


class TestAlembicExtra:
    @pytest.mark.parametrize(
        "database", ["postgresql", "sqlite", "mssql", "mysql"], ids=lambda d: f"db-{d}"
    )
    def test_each_sqlalchemy_database_has_its_extra(self, database):
        assert _alembic_extra(database) == f"protean[{database}]"

    def test_unknown_database_gets_the_package_name(self):
        assert _alembic_extra("oracle") == "alembic"
