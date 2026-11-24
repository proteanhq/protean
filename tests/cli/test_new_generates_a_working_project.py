"""A scaffolded project must actually start.

The existing template tests assert on the *text* of the generated
`domain.toml` with regexes. That is why a template emitting keys no adapter
reads, and even a `domain.toml` that was not valid TOML, shipped: nothing ever
loaded the file it produced.

These tests generate a project and initialise its domain, which is the first
thing a user does. Only the choices whose adapters need no live service are
exercised; the rest are covered by the config-shape test at the bottom, which
compares scaffolded keys against what each adapter actually reads.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.cli.dx import app as dx_app
from tests.support.project_tests import passed_count, project_env, run_tests_in

# These generate and start their own projects; the autouse domain fixture would
# build an unrelated Domain per test for nothing.
pytestmark = pytest.mark.no_test_domain

# Real test files that the tests below copy into a generated project and run.
_CHECKS = Path(__file__).parent / "project_checks"

# Choices whose provider can start with nothing else running.
OFFLINE_CHOICES: list[tuple[str, list[str]]] = [
    ("defaults", []),
    ("memory database", ["-d", "database=memory"]),
    ("sqlite database", ["-d", "database=sqlite"]),
    ("redis broker", ["-d", "broker=redis"]),
    ("redis-pubsub broker", ["-d", "broker=redis-pubsub"]),
    ("redis cache", ["-d", "cache=redis"]),
]

_INIT = (
    "import sys; sys.path.insert(0, 'src')\n"
    "from {pkg}.domain import {pkg} as domain\n"
    "domain.init()\n"
    "print('initialised')\n"
)

_INIT_REVERSED = (
    "import os; _listdir = os.listdir; "
    "os.listdir = lambda *args, **kwargs: list(reversed(_listdir(*args, **kwargs)))\n"
    "import sys; sys.path.insert(0, 'src')\n"
    "from {pkg}.domain import {pkg} as domain\n"
    "domain.init()\n"
    "print('initialised')\n"
)


def _generate(tmp_path: Path, extra: list[str], name: str = "scaffolded") -> Path:
    """Run `protean new` and return the generated project root."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    result = CliRunner().invoke(
        app,
        ["new", name, "-o", str(out), "--defaults", "--skip-setup", *extra],
    )
    assert result.exit_code == 0, f"protean new failed: {result.output}"
    return out / name


class TestGeneratedProjectStarts:
    @pytest.mark.parametrize(
        ("label", "extra"), OFFLINE_CHOICES, ids=[c[0] for c in OFFLINE_CHOICES]
    )
    def test_domain_initialises(self, tmp_path, label, extra):
        """The generated domain must load its own config and initialise."""
        project = _generate(tmp_path, extra)

        completed = subprocess.run(
            [sys.executable, "-c", _INIT.format(pkg="scaffolded")],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, (
            f"`protean new` with {label} generates a project whose domain does "
            f"not initialise:\n{completed.stderr}"
        )
        assert "initialised" in completed.stdout

    def test_domain_initialises_with_reverse_discovery_order(self, tmp_path):
        """Package discovery must not depend on filesystem enumeration order."""
        project = _generate(tmp_path, [])

        completed = subprocess.run(
            [sys.executable, "-c", _INIT_REVERSED.format(pkg="scaffolded")],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, (
            "The generated domain must initialise when module discovery order "
            f"is reversed:\n{completed.stderr}"
        )
        assert "initialised" in completed.stdout

    @pytest.mark.parametrize(
        ("label", "extra"),
        [
            ("memory database", []),
            ("sqlite database", ["-d", "database=sqlite"]),
        ],
        # Ids must not be a bare provider keyword (e.g. "sqlite"): the repo's
        # conftest skips any item whose keywords contain one unless its --flag
        # is passed, and the generated sqlite project needs no live service.
        ids=["memory database", "sqlite database"],
    )
    def test_generated_test_suite_runs_and_passes(self, tmp_path, label, extra):
        """The scaffold ships tests that actually run and pass.

        A fresh project's suite used to be empty: nothing ran, so nothing
        could fail. The scaffold now includes a write-path and a
        read-path test for the example slice; run the generated suite the way a
        user would (`pytest`, driven by the project's own `testpaths`) and
        require both to pass.

        Run it against a real on-disk database too, not just the in-memory
        provider that auto-materializes tables. The read-path test persists an
        aggregate and its projection, so a scaffold that never creates its
        schema would fail here with "no such table" the moment a user picks a
        real database.
        """
        project = _generate(tmp_path, extra)

        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:randomly", "-q", "tests"],
            cwd=project,
            env=project_env(project),
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, (
            f"The generated project's own test suite ({label}) does not pass:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )

        match = re.search(r"(\d+) passed", completed.stdout)
        assert match, f"no pass count in pytest output:\n{completed.stdout}"
        assert int(match.group(1)) >= 2, (
            "The scaffold must ship at least two passing tests so a fresh "
            f"project is not green on nothing:\n{completed.stdout}"
        )

    def test_generated_suite_passes_without_the_example(self, tmp_path):
        """An `include_example=false` project still ships a passing test.

        Opting out of the example used to leave the tests tree empty, so
        `pytest` collected nothing and exited 5 ("no tests ran") on first run.
        The always-generated smoke test keeps the opt-out project green.
        """
        project = _generate(tmp_path, ["-d", "include_example=false"])

        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:randomly", "-q", "tests"],
            cwd=project,
            env=project_env(project),
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, (
            "An opt-out project's own test suite does not pass:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )

        match = re.search(r"(\d+) passed", completed.stdout)
        assert match, f"no pass count in pytest output:\n{completed.stdout}"
        assert int(match.group(1)) >= 1, (
            "An opt-out project must still ship at least one passing test so "
            f"`pytest` does not exit 5 on nothing:\n{completed.stdout}"
        )

    @pytest.mark.parametrize(
        ("label", "extra"),
        [
            ("memory database", []),
            ("sqlite database", ["-d", "database=sqlite"]),
        ],
        # Ids must not be a bare provider keyword; see
        # test_generated_test_suite_runs_and_passes.
        ids=["memory database", "sqlite database"],
    )
    def test_generated_tests_do_not_see_each_others_data(self, tmp_path, label, extra):
        """Data one generated test writes is gone before the next test runs.

        The first test persists an aggregate, the second runs after it in file
        order and requires the repository to be empty. It passes only if the
        generated conftest resets the stores after every test. The third
        requires exactly one domain context on the stack, so a context held
        open for the whole session, under the per-test one, fails it.
        """
        project = _generate(tmp_path, extra)

        completed = run_tests_in(
            project, [_CHECKS / "test_isolation.py"], "tests/scaffolded/application"
        )

        assert completed.returncode == 0, (
            f"Generated tests ({label}) leak data into each other:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
        assert passed_count(completed) == 3, completed.stdout

    def test_generated_suite_drops_the_schema_at_session_end(self, tmp_path):
        """The generated session fixture drops the tables it created.

        The sqlite file the scaffold's `domain.toml` points at holds the
        example tables while the suite runs. After the session ends, none of
        them is left behind.
        """
        project = _generate(tmp_path, ["-d", "database=sqlite"])
        db_file = project / "scaffolded.db"

        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:randomly", "-q", "tests"],
            cwd=project,
            env=project_env(project),
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
        # The example tests write to the tables, so a run that passed them
        # had tables while it ran.
        assert re.search(r"\b[1-9]\d* passed\b", completed.stdout), completed.stdout

        assert db_file.exists(), "the suite did not use the scaffold's sqlite file"
        with sqlite3.connect(db_file) as conn:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            ]
        assert tables == [], f"tables left after the session: {tables}"

    def test_generated_conftest_uses_domain_fixture(self, tmp_path):
        """The rendered conftest uses the documented DomainFixture recipe."""
        project = _generate(tmp_path, [])
        tests_dir = project / "tests" / "scaffolded"
        conftest = (tests_dir / "conftest.py").read_text(encoding="utf-8")

        assert "from protean.integrations.pytest import DomainFixture" in conftest
        for leftover in ("load_config(", "run_around_tests", "_data_reset("):
            assert leftover not in conftest, (
                f"the generated conftest still carries {leftover!r}"
            )

        example_tests = (tests_dir / "application" / "test_example.py").read_text(
            encoding="utf-8"
        )
        assert "bootstrap_domain" not in example_tests

    def test_example_package_init_has_no_submodule_imports(self, tmp_path):
        """The rendered example `__init__.py` must stay side-effect free.

        A non-jinja `__init__.py` doing `from .handlers import *` (a module that
        does not exist) used to sit beside the empty `__init__.py.jinja`. The
        jinja version wins the copier collision, but the dead file was a
        hazard; guard that the rendered initializer imports no submodule.
        """
        project = _generate(tmp_path, [])
        init = project / "src" / "scaffolded" / "example" / "__init__.py"

        assert init.exists(), "the example package initializer was not generated"
        offending = [
            line
            for line in init.read_text().splitlines()
            # Any submodule import: relative (`from .x`, `from . import x`,
            # `from ..pkg`) or absolute into this package, either form
            # (`import scaffolded.example.handlers`,
            # `from scaffolded.example import handlers`,
            # `from scaffolded.example.handlers import X`).
            if re.match(r"\s*from\s+\.", line)
            or re.match(r"\s*import\s+scaffolded\.example\.\w", line)
            or re.match(r"\s*from\s+scaffolded\.example\b", line)
        ]
        assert not offending, (
            "the example `__init__.py` must not import from submodules; a "
            f"relative import during traversal risks a cycle: {offending}"
        )

    def test_generated_project_passes_check(self, tmp_path):
        """`protean check` exits 0 on a fresh default project."""
        project = _generate(tmp_path, [])

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "protean",
                "check",
                "-d",
                "src/scaffolded/domain.py:scaffolded",
            ],
            cwd=project,
            env=project_env(project),
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, (
            "`protean check` must pass on a freshly generated project:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )


class TestGeneratedSharedValueObjects:
    def test_shared_value_objects_enforce_their_rules(self, tmp_path):
        """The generated `shared/value_objects.py` rejects a bad email and adds
        and subtracts money exactly, in one currency only."""
        project = _generate(tmp_path, [])

        result = run_tests_in(
            project, [_CHECKS / "test_shared_value_objects.py"], "tests/scaffolded"
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert passed_count(result) == 6, result.stdout


class TestCommandsFindTheGeneratedDomain:
    """Commands run from the project root find `src/<package>/domain.py`."""

    @pytest.mark.parametrize(
        "command",
        [["db", "setup"], ["server", "--test-mode"]],
        ids=["db setup", "server test mode"],
    )
    def test_command_runs_without_a_domain_option(self, tmp_path, command):
        """No `--domain` and no `src` on `PYTHONPATH`: discovery must find the
        domain under `src/` and put `src` on the import path itself."""
        project = _generate(tmp_path, ["-d", "database=sqlite"])

        completed = _run_protean(project, *command)

        assert completed.returncode == 0, (
            f"`protean {' '.join(command)}` with no --domain fails in a "
            f"generated project:\n{completed.stdout}\n{completed.stderr}"
        )


def _env_without_src(project: Path) -> dict[str, str]:
    """`project_env` with the project's `src/` taken back off `PYTHONPATH`.

    A command run this way must find the domain through discovery alone, as it
    does when a developer runs it from the project root. `PROTEAN_DOMAIN` is
    dropped so a value exported in the parent shell cannot point it elsewhere.
    """
    env = project_env(project)
    env["PYTHONPATH"] = os.pathsep.join(
        entry
        for entry in env["PYTHONPATH"].split(os.pathsep)
        if entry != str(project / "src")
    )
    env.pop("PROTEAN_DOMAIN", None)
    return env


def _run_protean(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run `python -m protean <args>` from *project*'s root with no `--domain`."""
    return subprocess.run(
        [sys.executable, "-m", "protean", *args],
        cwd=project,
        env=_env_without_src(project),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


_MIGRATION_PATHS = [
    "migrations/alembic.ini",
    "migrations/env.py",
    "migrations/script.py.mako",
    "migrations/versions/",
]


class TestSqlProjectGetsMigrations:
    """A SQL project starts with the folder `protean db init` writes."""

    def test_folder_is_written_with_no_migration(self, tmp_path):
        project = _generate(tmp_path, ["-d", "database=sqlite"])
        migrations = project / "migrations"

        for name in ("alembic.ini", "env.py", "script.py.mako"):
            assert (migrations / name).is_file(), f"migrations/{name} is missing"
        assert (migrations / "versions").is_dir()
        assert list((migrations / "versions").iterdir()) == []

    def test_folder_equals_what_db_init_writes(self, tmp_path):
        """Each file is byte-for-byte what `protean db init` writes from the
        project root with its default `--domain` and provider."""
        scaffolded = _generate(tmp_path / "scaffolded", ["-d", "database=sqlite"])
        initialised = _generate(tmp_path / "initialised", ["-d", "database=sqlite"])
        shutil.rmtree(initialised / "migrations")

        completed = _run_protean(initialised, "db", "init")
        assert completed.returncode == 0, completed.stdout + completed.stderr

        for name in ("alembic.ini", "env.py", "script.py.mako"):
            assert (scaffolded / "migrations" / name).read_bytes() == (
                initialised / "migrations" / name
            ).read_bytes(), f"migrations/{name} differs from `protean db init`"
        assert list((scaffolded / "migrations" / "versions").iterdir()) == []
        assert list((initialised / "migrations" / "versions").iterdir()) == []

    def test_dry_run_lists_the_migrations_folder(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        result = CliRunner().invoke(
            app,
            [
                "new",
                "scaffolded",
                "-o",
                str(out),
                "-d",
                "database=sqlite",
                "--defaults",
                "--skip-setup",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output

        listed = result.output.splitlines()
        for path in _MIGRATION_PATHS:
            assert path in listed, f"--dry-run does not list {path}"
        assert not (out / "scaffolded").exists()

    def test_dry_run_lists_the_same_paths_an_apply_creates(self, tmp_path):
        from protean.scaffold import create_project

        dry_out = tmp_path / "dry"
        dry_out.mkdir()
        listed = create_project(
            "scaffolded",
            output_folder=str(dry_out),
            data={"database": "sqlite"},
            dry_run=True,
            defaults=True,
        )
        apply_out = tmp_path / "apply"
        apply_out.mkdir()
        created = create_project(
            "scaffolded",
            output_folder=str(apply_out),
            data={"database": "sqlite"},
            defaults=True,
        )

        assert set(_MIGRATION_PATHS) <= set(listed)
        assert set(listed) == set(created)

    def test_default_project_gets_no_migrations_folder(self, tmp_path):
        """`--defaults` with no `database` answer resolves to memory."""
        project = _generate(tmp_path, [])
        assert (project / "src").is_dir()
        assert not (project / "migrations").exists()

    def test_migrate_upgrade_and_check_run_from_the_project_root(self, tmp_path):
        project = _generate(tmp_path, ["-d", "database=sqlite"])

        for command in (
            ["db", "migrate", "-m", "initial"],
            ["db", "upgrade"],
            ["db", "check"],
        ):
            completed = _run_protean(project, *command)
            assert completed.returncode == 0, (
                f"`protean {' '.join(command)}` fails in a generated SQLite "
                f"project:\n{completed.stdout}\n{completed.stderr}"
            )

        revisions = list((project / "migrations" / "versions").glob("*.py"))
        assert len(revisions) == 1, revisions
        assert "op.create_table" in revisions[0].read_text(encoding="utf-8")


class TestGeneratedProjectIsDxManaged:
    """A generated project is dx-managed from birth.

    `protean new` writes the same managed-block AGENTS.md that `protean dx
    install` writes, plus the CLAUDE.md bridge and the dx state file, so a fresh
    project passes `protean dx check` with no manual step. It writes only this
    universal baseline; `.mcp.json` and the per-editor files stay `dx install`
    choices.
    """

    def test_agents_md_is_written_and_non_empty(self, tmp_path):
        """`protean new` writes AGENTS.md at the project root."""
        project = _generate(tmp_path, [])
        agents = project / "AGENTS.md"
        assert agents.exists(), "protean new must write AGENTS.md at the project root"
        assert agents.read_text(encoding="utf-8").strip(), "AGENTS.md is empty"

    def test_agents_md_equals_a_dx_install(self, tmp_path):
        """The scaffold and `dx install` write byte-identical AGENTS.md.

        Both go through the same dx renderers at the same pack version, so a
        scaffolded project's AGENTS.md must equal what `protean dx install` writes
        into a bare directory. This replaces the old byte-identity to `docs
        generate --type=agents`: the scaffold now ships the richer managed-block
        form, not the bare diagnostics rules.
        """
        project = _generate(tmp_path, [])

        installed_dir = tmp_path / "dx-installed"
        installed_dir.mkdir()
        result = CliRunner().invoke(dx_app, ["install", "-p", str(installed_dir)])
        assert result.exit_code == 0, result.output

        scaffolded = (project / "AGENTS.md").read_text(encoding="utf-8")
        from_install = (installed_dir / "AGENTS.md").read_text(encoding="utf-8")
        assert scaffolded == from_install
        # The managed-block form, not the bare generator output.
        assert "<!-- PROTEAN:BEGIN protean -->" in scaffolded
        assert "# Protean agent guidance" in scaffolded

    def test_ships_the_claude_bridge_and_dx_state(self, tmp_path):
        """The scaffold writes the CLAUDE.md bridge and records the dx state."""
        project = _generate(tmp_path, [])

        claude = project / "CLAUDE.md"
        assert claude.read_text(encoding="utf-8") == (
            "<!-- PROTEAN:BEGIN protean -->\n@AGENTS.md\n<!-- PROTEAN:END protean -->\n"
        )

        state_file = project / ".protean" / "dx-state.json"
        assert state_file.exists(), "protean new must write the dx state file"
        entries = json.loads(state_file.read_text(encoding="utf-8"))["entries"]
        assert set(entries) == {"AGENTS.md", "CLAUDE.md"}

    def test_ships_only_the_baseline_not_the_optional_files(self, tmp_path):
        """`.mcp.json` and the per-editor files stay `dx install` choices."""
        project = _generate(tmp_path, [])
        for rel in (
            ".mcp.json",
            ".cursor/rules/protean.mdc",
            ".github/copilot-instructions.md",
            "opencode.json",
        ):
            assert not (project / rel).exists(), (
                f"protean new must not write the optional dx file {rel}"
            )

    def test_dx_check_passes_on_a_fresh_project(self, tmp_path):
        """`protean dx check` exits 0 on a freshly scaffolded project.

        The baseline is present and no optional file was installed, so a clean
        scaffold reports up to date with no manual `dx install` step.
        """
        project = _generate(tmp_path, [])
        result = CliRunner().invoke(dx_app, ["check", "-p", str(project)])
        assert result.exit_code == 0, result.output
        assert "Up to date" in result.output

    def test_dry_run_writes_no_baseline_files(self, tmp_path):
        """A --dry-run touches nothing: no AGENTS.md, CLAUDE.md, or state file."""
        out = tmp_path / "out"
        out.mkdir(parents=True, exist_ok=True)
        result = CliRunner().invoke(
            app,
            [
                "new",
                "scaffolded",
                "-o",
                str(out),
                "--defaults",
                "--skip-setup",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, f"protean new --dry-run failed: {result.output}"
        project = out / "scaffolded"
        assert not (project / "AGENTS.md").exists()
        assert not (project / "CLAUDE.md").exists()
        assert not (project / ".protean" / "dx-state.json").exists()

    def test_dry_run_lists_the_same_files_an_apply_creates(self, tmp_path):
        """The dry-run file list is the exact set an apply creates.

        A dry run renders through the same path into a temp dir, so its returned
        list must equal what an apply into a real target returns. Comparing the
        whole sets catches a divergence (an extra or missing file, or a different
        relative-path form) that a membership check would miss, and confirms the
        baseline dx files (CLAUDE.md, the state file) are in both.
        """
        from protean.scaffold import create_project

        dry_out = tmp_path / "dry"
        dry_out.mkdir(parents=True, exist_ok=True)
        listed = create_project(
            "scaffolded", output_folder=str(dry_out), dry_run=True, defaults=True
        )

        apply_out = tmp_path / "apply"
        apply_out.mkdir(parents=True, exist_ok=True)
        created = create_project(
            "scaffolded", output_folder=str(apply_out), defaults=True
        )

        assert set(listed) == set(created)
        assert {"AGENTS.md", "CLAUDE.md", ".protean/dx-state.json"} <= set(listed)
        # A dry run touches nothing at the target.
        assert not (dry_out / "scaffolded").exists()


class TestGeneratedConfigIsValidToml:
    @pytest.mark.parametrize(
        ("label", "extra"), OFFLINE_CHOICES, ids=[c[0] for c in OFFLINE_CHOICES]
    )
    def test_domain_toml_parses(self, tmp_path, label, extra):
        """Guards the specific break: `${VAR|default}` must be quoted.

        Substitution runs over already-parsed strings, so an unquoted
        `${...}` is not valid TOML and the file cannot be read at all.
        """
        project = _generate(tmp_path, extra)
        config = project / "src" / "scaffolded" / "domain.toml"

        with config.open("rb") as handle:
            tomllib.load(handle)  # raises TOMLDecodeError if malformed

    def test_every_env_substitution_is_quoted(self, tmp_path):
        """Catch the unquoted form directly, so the message names the cause."""
        project = _generate(tmp_path, [])
        text = (project / "src" / "scaffolded" / "domain.toml").read_text()

        unquoted = [
            line
            for line in text.splitlines()
            if "${" in line
            and not line.lstrip().startswith("#")
            # A quoted value has a quote between `=` and `${`.
            and not any(q in line.split("${", 1)[0].split("=", 1)[-1] for q in "\"'")
        ]
        assert not unquoted, (
            "Environment substitutions must sit inside a TOML string; these do "
            f"not, so the file will not parse: {unquoted}"
        )


class TestScaffoldedKeysMatchWhatAdaptersRead:
    """The scaffold and the adapters have drifted repeatedly.

    `[event_stores.default]` (plural, never read) was fixed in 0.17; Redis
    `redis_url` vs `URI`, the cache's `ttl` vs `TTL`, Elasticsearch's
    `host`/`port` vs `database_uri`, a stray `database` key that SQLAlchemy
    rejected, and `provider = "sqlalchemy"` (not a registered provider) were
    all still shipping. Each is the same failure: a key nothing reads.
    """

    def test_redis_sections_use_the_key_the_adapter_reads(self, tmp_path):
        project = _generate(tmp_path, ["-d", "broker=redis", "-d", "cache=redis"])
        text = (project / "src" / "scaffolded" / "domain.toml").read_text()

        assert "redis_url" not in text, (
            "The Redis broker and cache read `conn_info['URI']`; `redis_url` is "
            "silently ignored."
        )
        assert 'URI = "${REDIS_URL' in text

    def test_no_stray_database_key(self, tmp_path):
        """SQLAlchemy forwards unknown `[databases.*]` keys to create_engine()."""
        project = _generate(tmp_path, ["-d", "database=sqlite"])
        config = project / "src" / "scaffolded" / "domain.toml"

        with config.open("rb") as handle:
            parsed = tomllib.load(handle)

        for name, section in parsed.get("databases", {}).items():
            assert "database" not in section, (
                f"[databases.{name}] carries a `database` key, which SQLAlchemy "
                "rejects with TypeError when it reaches create_engine()."
            )

    def test_every_database_provider_is_registered(self, tmp_path):
        """`sqlalchemy` is the library, not a provider name."""
        from importlib.metadata import entry_points

        # `.select(group=...)` is how the provider registry discovers plugins.
        registered = {
            ep.name for ep in entry_points().select(group="protean.databases")
        }
        assert registered, "no provider entry points found"

        project = _generate(tmp_path, [])
        config = project / "src" / "scaffolded" / "domain.toml"
        with config.open("rb") as handle:
            parsed = tomllib.load(handle)

        for name, section in parsed.get("databases", {}).items():
            provider = section.get("provider")
            assert provider in registered, (
                f"[databases.{name}] names provider {provider!r}, which is not "
                f"registered. Known: {sorted(registered)}"
            )

    def test_no_orphaned_logging_toml(self, tmp_path):
        """`logging.toml` shipped for months with nothing reading it.

        `[logging]` in `domain.toml` is the one mechanism Protean reads
        (`Domain.configure_logging`); a second, unread config file at the
        project root is a bug, not an alternative.
        """
        project = _generate(tmp_path, [])

        assert not (project / "logging.toml").exists(), (
            "logging.toml is generated but nothing reads it; [logging] in "
            "domain.toml is the only config Domain.configure_logging loads."
        )

    def test_commented_logging_keys_are_all_read_by_the_framework(self, tmp_path):
        """Every key the scaffold shows a user in the commented `[logging]`
        block must be a key some adapter actually reads, so uncommenting it
        has an effect."""
        # Union across every site that reads `domain.toml`'s `[logging]` table.
        known_logging_keys = {
            # Domain.configure_logging (src/protean/domain/__init__.py)
            "level",
            "format",
            "log_dir",
            "log_file_prefix",
            "max_bytes",
            "backup_count",
            "redact",
            "per_logger",
            # src/protean/utils/logging.py
            "slow_handler_threshold_ms",
            # SQLAlchemy adapter (get_logging_config_value)
            "slow_query_threshold_ms",
            "slow_query_truncate_chars",
        }

        project = _generate(tmp_path, [])
        text = (project / "src" / "scaffolded" / "domain.toml").read_text()

        match = re.search(
            r"^# \[logging\]\n(.*?)(?=\n\n|\Z)", text, re.MULTILINE | re.DOTALL
        )
        assert match, "domain.toml no longer ships a commented [logging] block"

        parsed_keys = set()
        for line in match.group(1).splitlines():
            if line.strip().startswith("# ["):
                # The `[logging.per_logger]` subtable header; its body holds
                # logger *names*, not [logging] keys.
                break
            if line.strip() == "#":
                # A blank comment line, e.g. a separator between keys.
                continue
            key_match = re.match(r"# (\w+) = ", line)
            if key_match:
                parsed_keys.add(key_match.group(1))

        assert parsed_keys, "no keys parsed out of the commented [logging] block"
        assert parsed_keys <= known_logging_keys, (
            f"domain.toml's commented [logging] block names keys nothing "
            f"reads: {parsed_keys - known_logging_keys}"
        )
