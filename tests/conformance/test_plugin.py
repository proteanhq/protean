"""The conformance plugin in ``tests/conformance/conftest.py``.

The pure helpers run in this process. The hooks and fixtures run in a child
pytest session: each test copies the plugin next to a small synthetic suite
under ``tmp_path``, so the child loads the plugin as the suite's conftest and
no other conftest from this repository's test tree. The child gets the
repository root on ``PYTHONPATH`` because the plugin imports ``tests.shared``
and ``tests.conformance.flag_coverage``.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from protean.exceptions import ConfigurationError
from protean.port.broker import BrokerCapabilities
from protean.port.provider import DatabaseCapabilities
from tests.conformance.conftest import (
    BUILTIN_ADAPTER_CONFIGS,
    CONFORMANCE_DIR,
    missing_capability,
    parse_adapter_config,
    port_of,
    resolve_adapter_config,
)
from tests.shared import MESSAGE_DB_URI, POSTGRES_URI, REDIS_URI

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = Path(__file__).parent / "conftest.py"

DATABASE_SUITE = """
import pytest

from protean.port.provider import DatabaseCapabilities as Caps


def test_ungated(adapter):
    assert type(adapter).__name__ == "MemoryProvider"


@pytest.mark.requires(Caps.CRUD)
def test_requires_declared(adapter):
    assert Caps.CRUD in adapter.capabilities


@pytest.mark.requires(Caps.NATIVE_JSON)
def test_requires_undeclared():
    pass


@pytest.mark.requires(Caps.CRUD, Caps.NATIVE_ARRAY)
def test_requires_several():
    pass


@pytest.mark.requires(Caps.BASIC_STORAGE)
def test_requires_tier():
    pass


@pytest.mark.requires_any(Caps.TRANSACTIONS, Caps.SIMULATED_TRANSACTIONS)
def test_requires_any_one_declared():
    pass


@pytest.mark.requires_any(Caps.NATIVE_JSON, Caps.NATIVE_ARRAY)
def test_requires_any_none_declared():
    pass


class TestAdapterWithoutCapabilities:
    @pytest.fixture
    def adapter(self):
        return object()

    @pytest.mark.requires(Caps.CRUD)
    def test_gated(self):
        pass
"""

BROKER_SUITE = """
import pytest

from protean.port.broker import BrokerCapabilities as Caps


def test_ungated(adapter):
    assert type(adapter).__name__ == "InlineBroker"


@pytest.mark.requires(Caps.PUBLISH)
def test_requires_publish():
    pass
"""

CACHE_SUITE = """
def test_ungated(adapter, adapter_config):
    assert type(adapter).__name__ == "MemoryCache"
    assert adapter_config == {"provider": "memory", "TTL": 300}
"""

EVENT_STORE_SUITE = """
def test_ungated(adapter):
    assert type(adapter).__name__ == "MemoryEventStore"
"""

OUTSIDE_SUITE = """
def test_outside():
    pass
"""


@pytest.fixture
def suite(tmp_path: Path) -> Path:
    """A synthetic ``conformance/`` tree with the plugin as its conftest."""
    root = tmp_path / "conformance"
    root.mkdir()
    (root / "__init__.py").write_text("")
    shutil.copy(PLUGIN, root / "conftest.py")
    (root / "test_meta.py").write_text("def test_meta():\n    pass\n")
    for port, source in (
        ("database", DATABASE_SUITE),
        ("broker", BROKER_SUITE),
        ("cache", CACHE_SUITE),
        ("event_store", EVENT_STORE_SUITE),
    ):
        (root / port).mkdir()
        (root / port / "__init__.py").write_text("")
        (root / port / f"test_{port}.py").write_text(source)

    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "test_outside.py").write_text(OUTSIDE_SUITE)
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = --strict-markers\n")
    return tmp_path


def run(suite: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run pytest on ``suite`` in a child process with ``args`` and return it."""
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("PYTEST_")
    }
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(REPO_ROOT), os.environ.get("PYTHONPATH")])
    )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "pytest.ini",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            "-q",
            "-rA",
            "--tb=short",
            *args,
        ],
        check=False,
        cwd=suite,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def collected(result: subprocess.CompletedProcess[str]) -> set[str]:
    """Return the test ids a ``--collect-only -q`` run listed."""
    return {line for line in result.stdout.splitlines() if "::" in line}


def outcomes(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    """Map each test name in a ``-rA`` summary to its outcome, or skip reason."""
    found: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line.startswith("PASSED "):
            found[line.split("::")[-1]] = "passed"
        elif line.startswith("SKIPPED "):
            # SKIPPED [1] path/test_x.py:12: <reason>
            location, reason = line.split(": ", 1)
            found[location] = reason
    return found


# ===================================================================
# Helpers
# ===================================================================


class TestParseAdapterConfig:
    def test_no_value_is_an_empty_object(self):
        assert parse_adapter_config(None) == {}

    def test_a_json_object_is_returned(self):
        assert parse_adapter_config('{"pool_size": 5}') == {"pool_size": 5}

    def test_a_json_array_is_a_usage_error(self):
        with pytest.raises(pytest.UsageError, match="must be a JSON object, got list"):
            parse_adapter_config("[1]")

    def test_malformed_json_is_a_usage_error(self):
        with pytest.raises(pytest.UsageError, match="not valid JSON"):
            parse_adapter_config("{pool_size")


class TestResolveAdapterConfig:
    @pytest.mark.parametrize(
        "port, adapter, expected",
        [
            ("database", "memory", {"provider": "memory"}),
            (
                "database",
                "postgresql",
                {
                    "provider": "postgresql",
                    "database_uri": POSTGRES_URI,
                    "pool_size": 1,
                    "max_overflow": 2,
                },
            ),
            ("broker", "inline", {"provider": "inline"}),
            (
                "broker",
                "redis",
                {"provider": "redis", "URI": f"{REDIS_URI}/8", "TTL": 300},
            ),
            ("cache", "memory", {"provider": "memory", "TTL": 300}),
            (
                "event_store",
                "message_db",
                {"provider": "message_db", "database_uri": MESSAGE_DB_URI},
            ),
        ],
    )
    def test_reads_the_built_in_row(self, port, adapter, expected):
        assert resolve_adapter_config(port, adapter, {}) == expected

    def test_overrides_merge_over_the_row(self):
        config = resolve_adapter_config(
            "database", "postgresql", {"pool_size": 5, "echo": True}
        )

        assert config == {
            "provider": "postgresql",
            "database_uri": POSTGRES_URI,
            "pool_size": 5,
            "max_overflow": 2,
            "echo": True,
        }

    def test_overrides_do_not_change_the_table(self):
        resolve_adapter_config("database", "memory", {"extra": 1})

        assert BUILTIN_ADAPTER_CONFIGS[("database", "memory")] == {"provider": "memory"}

    def test_every_row_names_an_adapter_its_port_registers(self):
        for port, adapter in BUILTIN_ADAPTER_CONFIGS:
            assert resolve_adapter_config(port, adapter, {})["provider"] == adapter

    def test_unknown_adapter_raises_the_registry_error(self):
        with pytest.raises(
            ConfigurationError,
            match=r"Unknown broker 'nosuch'\. Available: inline, redis, redis_pubsub",
        ):
            resolve_adapter_config("broker", "nosuch", {})


class TestPortOf:
    @pytest.mark.parametrize("port", ["database", "broker", "cache", "event_store"])
    def test_a_file_in_a_port_folder_has_that_port(self, port):
        assert port_of(CONFORMANCE_DIR / port / "test_x.py") == port

    def test_a_file_at_the_top_of_the_folder_has_no_port(self):
        assert port_of(CONFORMANCE_DIR / "test_plugin.py") is None

    def test_a_file_in_an_unknown_folder_has_no_port(self):
        assert port_of(CONFORMANCE_DIR / "queue" / "test_x.py") is None

    def test_a_file_outside_the_folder_has_no_port(self):
        assert port_of(REPO_ROOT / "tests" / "database" / "test_x.py") is None


class TestMissingCapability:
    def test_an_adapter_without_capabilities_declares_none(self):
        reason = missing_capability("memory", None, [(DatabaseCapabilities.CRUD,)], [])

        assert reason == "memory declares no capabilities"

    def test_names_the_first_flag_the_adapter_lacks(self):
        declared = DatabaseCapabilities.CRUD
        reason = missing_capability(
            "memory",
            declared,
            [(DatabaseCapabilities.CRUD, DatabaseCapabilities.NATIVE_JSON)],
            [],
        )

        assert reason == "memory does not declare NATIVE_JSON"

    def test_a_tier_needs_every_one_of_its_flags(self):
        declared = BrokerCapabilities.PUBLISH | BrokerCapabilities.SUBSCRIBE
        reason = missing_capability(
            "inline", declared, [(BrokerCapabilities.SIMPLE_QUEUING,)], []
        )

        assert reason == "inline does not declare SIMPLE_QUEUING"

    def test_declared_flags_give_no_reason(self):
        declared = DatabaseCapabilities.CRUD | DatabaseCapabilities.FILTER
        reason = missing_capability(
            "memory",
            declared,
            [(DatabaseCapabilities.CRUD,)],
            [(DatabaseCapabilities.FILTER, DatabaseCapabilities.NATIVE_JSON)],
        )

        assert reason is None

    def test_requires_any_with_none_declared_names_each_flag(self):
        reason = missing_capability(
            "memory",
            DatabaseCapabilities.CRUD,
            [],
            [(DatabaseCapabilities.NATIVE_JSON, DatabaseCapabilities.NATIVE_ARRAY)],
        )

        assert reason == "memory does not declare NATIVE_JSON or NATIVE_ARRAY"


# ===================================================================
# Hooks and fixtures, in a child session
# ===================================================================


class TestRunWithoutOptions:
    def test_each_test_runs_on_its_folders_memory_adapter_or_skips(self, suite):
        result = run(suite, "conformance")

        assert result.returncode == 0, result.stdout + result.stderr
        found = outcomes(result)
        passed = {name for name, outcome in found.items() if outcome == "passed"}
        assert passed == {
            "test_meta",
            "test_ungated",
            "test_requires_declared",
            "test_requires_tier",
            "test_requires_any_one_declared",
            "test_requires_publish",
        }
        # Every port folder's test_ungated passed: one PASSED line per folder.
        assert result.stdout.count("::test_ungated") == 4
        assert sorted(reason for reason in found.values() if reason != "passed") == [
            "memory declares no capabilities",
            "memory does not declare NATIVE_ARRAY",
            "memory does not declare NATIVE_JSON",
            "memory does not declare NATIVE_JSON or NATIVE_ARRAY",
        ]

    def test_markers_are_registered_under_strict_markers(self, suite):
        result = run(suite, "conformance", "--markers")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "@pytest.mark.requires(*flags)" in result.stdout
        assert "@pytest.mark.requires_any(*flags)" in result.stdout


class TestPortOption:
    def test_deselects_other_ports_and_keeps_outside_tests(self, suite):
        result = run(
            suite, "conformance", "outside", "--collect-only", "--port", "broker"
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert collected(result) == {
            "conformance/broker/test_broker.py::test_ungated",
            "conformance/broker/test_broker.py::test_requires_publish",
            "outside/test_outside.py::test_outside",
        }

    def test_runs_the_port_on_the_named_adapter(self, suite):
        result = run(suite, "conformance", "--port", "broker", "--adapter", "inline")

        assert result.returncode == 0, result.stdout + result.stderr
        assert outcomes(result) == {
            "test_ungated": "passed",
            "test_requires_publish": "passed",
        }

    def test_an_unknown_port_is_a_usage_error(self, suite):
        result = run(suite, "conformance", "--port", "queue")

        assert result.returncode == 4
        assert "invalid choice: 'queue'" in result.stderr


class TestAdapterOption:
    def test_an_unknown_adapter_raises_the_registry_error(self, suite):
        result = run(suite, "conformance/broker", "--adapter", "nosuch")

        assert result.returncode == 1
        assert (
            "ConfigurationError: Unknown broker 'nosuch'. "
            "Available: inline, redis, redis_pubsub."
        ) in result.stdout


class TestAdapterConfigOption:
    def test_merges_over_the_built_in_row(self, suite):
        (suite / "conformance" / "cache" / "test_cache.py").write_text(
            "def test_config(adapter_config):\n"
            "    assert adapter_config == "
            "{'provider': 'memory', 'TTL': 5, 'extra': True}\n"
        )

        result = run(
            suite,
            "conformance/cache",
            "--adapter-config",
            '{"TTL": 5, "extra": true}',
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert outcomes(result) == {"test_config": "passed"}

    def test_a_value_that_is_not_an_object_is_a_usage_error(self, suite):
        result = run(suite, "conformance", "--adapter-config", '"memory"')

        assert result.returncode == 4
        assert "--adapter-config must be a JSON object, got str" in result.stderr


class TestCapabilityOption:
    def test_keeps_only_tests_that_name_the_flag(self, suite):
        result = run(
            suite,
            "conformance",
            "outside",
            "--collect-only",
            "--capability",
            "NATIVE_ARRAY",
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert collected(result) == {
            "conformance/database/test_database.py::test_requires_several",
            "conformance/database/test_database.py::test_requires_any_none_declared",
            "outside/test_outside.py::test_outside",
        }

    def test_a_test_naming_several_flags_is_kept_for_each(self, suite):
        crud = collected(
            run(
                suite,
                "conformance",
                "outside",
                "--collect-only",
                "--capability",
                "CRUD",
            )
        )

        assert "conformance/database/test_database.py::test_requires_several" in crud

    def test_a_tier_is_matched_by_its_own_name(self, suite):
        result = run(
            suite,
            "conformance",
            "outside",
            "--collect-only",
            "--capability",
            "BASIC_STORAGE",
        )

        assert collected(result) == {
            "conformance/database/test_database.py::test_requires_tier",
            "outside/test_outside.py::test_outside",
        }

    def test_none_keeps_only_tests_without_a_marker(self, suite):
        result = run(
            suite, "conformance", "outside", "--collect-only", "--capability", "none"
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert collected(result) == {
            "conformance/test_meta.py::test_meta",
            "conformance/database/test_database.py::test_ungated",
            "conformance/broker/test_broker.py::test_ungated",
            "conformance/cache/test_cache.py::test_ungated",
            "conformance/event_store/test_event_store.py::test_ungated",
            "outside/test_outside.py::test_outside",
        }
