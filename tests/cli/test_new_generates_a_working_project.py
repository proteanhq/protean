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

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app

# These generate and start their own projects; the autouse domain fixture would
# build an unrelated Domain per test for nothing.
pytestmark = pytest.mark.no_test_domain

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


def _subprocess_env(project: Path) -> dict[str, str]:
    """Env for running the generated project uninstalled.

    The project is not pip-installed, so its ``src/`` goes on ``PYTHONPATH``.
    ``VIRTUAL_ENV`` is dropped so it cannot point the child at a different
    interpreter or source tree than ``sys.executable``. ``PROTEAN_ENV`` and
    ``PROTEAN_DEBUG`` are dropped too: Protean's pytest plugin only sets
    ``PROTEAN_ENV`` with ``setdefault``, so a value already exported in the
    parent shell would otherwise leak into the generated project's own test
    run and make it non-deterministic.
    """
    src = str(project / "src")
    existing = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "PYTHONPATH": src + os.pathsep + existing if existing else src,
    }
    env.pop("VIRTUAL_ENV", None)
    env.pop("PROTEAN_ENV", None)
    env.pop("PROTEAN_DEBUG", None)
    return env


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
            [sys.executable, "-m", "pytest", "-q", "tests"],
            cwd=project,
            env=_subprocess_env(project),
            capture_output=True,
            text=True,
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
            [sys.executable, "-m", "pytest", "-q", "tests"],
            cwd=project,
            env=_subprocess_env(project),
            capture_output=True,
            text=True,
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
            # `from ..pkg`) or absolute into this package
            # (`import scaffolded.example.handlers`).
            if re.match(r"\s*from\s+\.", line)
            or re.match(r"\s*import\s+scaffolded\.example\.\w", line)
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
            env=_subprocess_env(project),
            capture_output=True,
            text=True,
        )

        assert completed.returncode == 0, (
            "`protean check` must pass on a freshly generated project:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )


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

        # `.select(group=...)` is how ProviderRegistry discovers plugins.
        registered = {
            ep.name for ep in entry_points().select(group="protean.providers")
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
