"""Tests for the Alembic-backed schema migrator of the SQLAlchemy providers."""

import configparser
import importlib
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
from protean.fields import String

alembic_command = pytest.importorskip("alembic.command")
from alembic.config import Config

pytestmark = [pytest.mark.sqlite, pytest.mark.no_test_domain]

MIGRATOR_MODULE = "protean.adapters.repository.schema_migrator.alembic_migrator"


class Product(BaseAggregate):
    name = String(max_length=50)


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


def block_alembic(monkeypatch):
    """Make every ``import alembic`` fail, as on an install without it."""
    monkeypatch.setitem(sys.modules, "alembic", None)
    for name in [n for n in sys.modules if n.startswith("alembic.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.delitem(sys.modules, MIGRATOR_MODULE, raising=False)


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

        with pytest.raises(ConfigurationError, match="already exists"):
            write_migrations_folder(target, "domain.py", "default")

        assert target.read_text() == "mine"


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
        assert "create_table('product'" in versions[0].read_text()

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


class TestRunMigrationsFromAlembicIni:
    def test_does_nothing_outside_an_alembic_run(self):
        assert run_migrations() is None

    def test_does_nothing_without_alembic(self, monkeypatch):
        block_alembic(monkeypatch)

        assert run_migrations() is None

    def test_loads_the_domain_and_provider_the_ini_names(
        self, tmp_path, monkeypatch, capsys
    ):
        (tmp_path / "shop.py").write_text(
            textwrap.dedent(
                f"""
                from protean import Domain

                domain = Domain(name="Shop")
                domain.config["databases"]["analytics"] = {{
                    "provider": "sqlite",
                    "database_uri": "sqlite:///{tmp_path / "analytics.db"}",
                }}
                """
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
        monkeypatch.setattr(sys, "path", sys.path[:])
        monkeypatch.delitem(sys.modules, "shop", raising=False)
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

    def test_ini_naming_an_unknown_provider(self, tmp_path, monkeypatch):
        (tmp_path / "shop.py").write_text(
            textwrap.dedent(
                """
                from protean import Domain

                domain = Domain(name="Shop")
                """
            ),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
        monkeypatch.setattr(sys, "path", sys.path[:])
        monkeypatch.delitem(sys.modules, "shop", raising=False)
        write_migrations_folder(tmp_path / "m", "shop.py", "missing")

        with pytest.raises(
            ConfigurationError,
            match=r"Provider 'missing' named in .* Configured providers: default, memory\.",
        ):
            alembic_command.current(Config(str(tmp_path / "m" / "alembic.ini")))


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
