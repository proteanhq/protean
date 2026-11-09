"""Tests for ``protean db init``, which creates a provider's migrations folder."""

import configparser
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app

pytestmark = [pytest.mark.sqlite, pytest.mark.no_test_domain]

runner = CliRunner()

MIGRATOR_MODULE = "protean.adapters.repository.schema_migrator.alembic_migrator"


def write_domain(directory: Path, databases: dict) -> None:
    """Write a ``domain.py`` with one aggregate, adding the given databases."""
    (directory / "domain.py").write_text(
        textwrap.dedent(
            f"""
            from protean import Domain
            from protean.fields import String

            domain = Domain(name="Shop")
            domain.config["databases"].update({databases!r})


            @domain.aggregate
            class Product:
                name = String(max_length=50)
            """
        ),
        encoding="utf-8",
    )


def sqlite(path: Path, **extra) -> dict:
    return {"provider": "sqlite", "database_uri": f"sqlite:///{path}", **extra}


def snapshot(directory: Path) -> dict[str, bytes | None]:
    """Every path under ``directory``, with the bytes of each file."""
    return {
        str(path.relative_to(directory)): (
            path.read_bytes() if path.is_file() else None
        )
        for path in sorted(directory.rglob("*"))
    }


def read_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    assert parser.read(path, encoding="utf-8") == [str(path)]
    return parser


def run_alembic(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", *args],
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
        env={"PROTEAN_NO_AUTO_LOGGING": "1", "PATH": ""},
    )


@pytest.fixture(autouse=True)
def project(tmp_path, monkeypatch):
    """Run each test from ``tmp_path`` and forget the domain module afterwards."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
    monkeypatch.setenv("PROTEAN_NO_AUTO_LOGGING", "1")
    original_path = sys.path[:]
    original_modules = set(sys.modules)

    yield tmp_path

    sys.path[:] = original_path
    for name in set(sys.modules) - original_modules:
        module_file = getattr(sys.modules[name], "__file__", None) or ""
        if module_file.startswith(str(tmp_path)):
            del sys.modules[name]


class TestInitWritesTheFolder:
    def test_writes_the_migrations_folder(self, project):
        write_domain(project, {"default": sqlite(project / "shop.db")})

        result = runner.invoke(app, ["db", "init", "--domain", "domain.py"])

        assert result.exit_code == 0, result.output
        migrations = project / "migrations"
        assert sorted(p.name for p in migrations.iterdir()) == [
            "alembic.ini",
            "env.py",
            "script.py.mako",
            "versions",
        ]
        assert list((migrations / "versions").iterdir()) == []

        alembic_section = read_ini(migrations / "alembic.ini")["alembic"]
        assert alembic_section["protean_domain"] == "domain.py"
        assert alembic_section["protean_provider"] == "default"

    def test_env_py_calls_run_migrations(self, project):
        write_domain(project, {"default": sqlite(project / "shop.db")})

        runner.invoke(app, ["db", "init", "--domain", "domain.py"])

        env_py = (project / "migrations" / "env.py").read_text(encoding="utf-8")
        assert env_py == (
            "from protean.adapters.repository.schema_migrator import run_migrations"
            "\n\nrun_migrations()\n"
        )

    def test_plain_alembic_commands_load_the_domain(self, project):
        write_domain(project, {"default": sqlite(project / "shop.db")})
        assert (
            runner.invoke(app, ["db", "init", "--domain", "domain.py"]).exit_code == 0
        )

        for command in (["history"], ["current"], ["stamp", "head"]):
            completed = run_alembic(project, *command)
            assert completed.returncode == 0, completed.stderr

        # ``current`` and ``stamp`` connect to the provider's database, so the
        # SQLite file exists only when env.py found the domain's provider.
        assert (project / "shop.db").exists()

    def test_an_existing_empty_folder_is_used(self, project):
        write_domain(project, {"default": sqlite(project / "shop.db")})
        (project / "migrations").mkdir()

        result = runner.invoke(app, ["db", "init", "--domain", "domain.py"])

        assert result.exit_code == 0, result.output
        assert (project / "migrations" / "alembic.ini").is_file()

    def test_second_provider_gets_its_own_folder(self, project):
        write_domain(
            project,
            {
                "default": sqlite(project / "shop.db"),
                "analytics": sqlite(project / "analytics.db"),
            },
        )

        result = runner.invoke(
            app,
            [
                "db",
                "init",
                "--domain",
                "domain.py",
                "--provider",
                "analytics",
                "--directory",
                "migrations/analytics",
            ],
        )

        assert result.exit_code == 0, result.output
        ini = read_ini(project / "migrations" / "analytics" / "alembic.ini")
        assert ini["alembic"]["protean_provider"] == "analytics"
        assert not (project / "migrations" / "alembic.ini").exists()


class TestInitRefuses:
    def test_non_empty_folder_is_left_unchanged(self, project):
        write_domain(project, {"default": sqlite(project / "shop.db")})
        migrations = project / "migrations"
        (migrations / "versions").mkdir(parents=True)
        (migrations / "alembic.ini").write_text("[alembic]\nmine = 1\n")
        (migrations / "versions" / "0001_first.py").write_bytes(b"revision = 'x'\n")
        before = snapshot(migrations)

        result = runner.invoke(app, ["db", "init", "--domain", "domain.py"])

        assert result.exit_code != 0
        assert "already exists and is not empty" in result.output
        assert snapshot(migrations) == before

    def test_provider_without_the_capability(self, project):
        write_domain(
            project,
            {
                "default": {"provider": "memory"},
                "analytics": sqlite(project / "analytics.db"),
            },
        )

        result = runner.invoke(app, ["db", "init", "--domain", "domain.py"])

        assert result.exit_code != 0
        assert "Provider 'default' (memory)" in result.output
        assert "SCHEMA_MIGRATIONS" in result.output
        assert "Providers that declare it: analytics." in result.output
        assert not (project / "migrations").exists()

    def test_no_provider_declares_the_capability(self, project):
        write_domain(project, {"default": {"provider": "memory"}})

        result = runner.invoke(app, ["db", "init", "--domain", "domain.py"])

        assert result.exit_code != 0
        assert "SCHEMA_MIGRATIONS" in result.output
        assert "No configured provider declares it." in result.output
        assert not (project / "migrations").exists()

    def test_unmanaged_provider(self, project):
        write_domain(project, {"default": sqlite(project / "shop.db", managed=False)})

        result = runner.invoke(app, ["db", "init", "--domain", "domain.py"])

        assert result.exit_code != 0
        assert "managed = false" in result.output
        assert not (project / "migrations").exists()

    def test_unknown_provider(self, project):
        write_domain(
            project,
            {
                "default": sqlite(project / "shop.db"),
                "analytics": sqlite(project / "analytics.db"),
            },
        )

        result = runner.invoke(
            app, ["db", "init", "--domain", "domain.py", "--provider", "missing"]
        )

        assert result.exit_code != 0
        assert "Provider 'missing' is not configured" in result.output
        assert "Configured providers: analytics, default, memory." in result.output
        assert not (project / "migrations").exists()

    def test_alembic_not_installed(self, project, monkeypatch):
        write_domain(project, {"default": sqlite(project / "shop.db")})
        monkeypatch.setitem(sys.modules, "alembic", None)
        monkeypatch.delitem(sys.modules, "alembic.config", raising=False)
        monkeypatch.delitem(sys.modules, MIGRATOR_MODULE, raising=False)

        result = runner.invoke(app, ["db", "init", "--domain", "domain.py"])

        assert result.exit_code != 0
        assert 'pip install "protean[sqlite]"' in result.output
        assert not (project / "migrations").exists()
