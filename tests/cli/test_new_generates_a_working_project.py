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
    "domain.init(traverse=False)\n"
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
        )

        assert completed.returncode == 0, (
            f"`protean new` with {label} generates a project whose domain does "
            f"not initialise:\n{completed.stderr}"
        )
        assert "initialised" in completed.stdout


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
