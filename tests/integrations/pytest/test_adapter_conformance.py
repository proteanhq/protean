"""Tests for the adapter conformance pytest plugin.

Each test directly invokes the plugin hook functions with mock objects,
following the same pattern as ``test_plugin.py``.

The ``TestConformancePluginIntegration`` class runs the conformance suite
in isolated subprocess pytest sessions, verifying that the plugin
fixtures and hooks work end-to-end.
"""

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from protean.integrations.pytest.adapter_conformance import (
    BUILTIN_DB_CONFIGS,
    MARKER_TO_CAPABILITY,
    pytest_addoption,
    pytest_collection_modifyitems,
    pytest_configure,
    resolve_db_config,
)
from protean.port.provider import DatabaseCapabilities


class TestOptionRegistration:
    """Tests for pytest_addoption hook."""

    def test_all_options_registered(self):
        """All four CLI options are registered on the conformance group."""
        parser = mock.MagicMock()
        group = mock.MagicMock()
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        parser.getgroup.assert_called_once_with(
            "protean-conformance", "Protean adapter conformance"
        )
        option_names = [call.args[0] for call in group.addoption.call_args_list]
        assert "--db" in option_names
        assert "--db-provider" in option_names
        assert "--db-uri" in option_names
        assert "--db-extra" in option_names

    def test_db_option_conflict_handled(self):
        """--db conflict (already defined by tests/conftest.py) is swallowed."""
        parser = mock.MagicMock()
        group = mock.MagicMock()
        # First call (--db) raises, rest succeed
        group.addoption.side_effect = [
            ValueError("already defined"),
            None,
            None,
            None,
        ]
        parser.getgroup.return_value = group

        # Should not raise
        pytest_addoption(parser)

        # The remaining three options should still be registered
        assert group.addoption.call_count == 4

    def test_db_default_is_memory(self):
        """--db defaults to MEMORY."""
        parser = mock.MagicMock()
        group = mock.MagicMock()
        parser.getgroup.return_value = group

        pytest_addoption(parser)

        db_call = group.addoption.call_args_list[0]
        assert db_call.kwargs["default"] == "MEMORY"


class TestMarkerRegistration:
    """Tests for pytest_configure hook."""

    def test_capability_markers_registered(self):
        """All capability markers are registered."""
        config = mock.MagicMock()

        pytest_configure(config)

        marker_calls = [call.args[1] for call in config.addinivalue_line.call_args_list]
        for marker_name in MARKER_TO_CAPABILITY:
            assert any(marker_name in m for m in marker_calls)

    def test_database_marker_registered(self):
        """The 'database' marker is registered."""
        config = mock.MagicMock()

        pytest_configure(config)

        marker_calls = [call.args[1] for call in config.addinivalue_line.call_args_list]
        assert any("database" in m for m in marker_calls)

    def test_no_test_domain_marker_registered(self):
        """The 'no_test_domain' marker is registered."""
        config = mock.MagicMock()

        pytest_configure(config)

        marker_calls = [call.args[1] for call in config.addinivalue_line.call_args_list]
        assert any("no_test_domain" in m for m in marker_calls)


class TestBuiltinDbConfigs:
    """Tests for BUILTIN_DB_CONFIGS constant."""

    def test_all_known_providers_present(self):
        """All known providers have an entry."""
        expected = {"MEMORY", "POSTGRESQL", "ELASTICSEARCH", "SQLITE", "MSSQL"}
        assert set(BUILTIN_DB_CONFIGS.keys()) == expected

    def test_each_config_has_provider_key(self):
        """Every config dict has a 'provider' key."""
        for key, config in BUILTIN_DB_CONFIGS.items():
            assert "provider" in config, f"{key} config missing 'provider'"

    def test_memory_is_minimal(self):
        """Memory config is just {'provider': 'memory'}."""
        assert BUILTIN_DB_CONFIGS["MEMORY"] == {"provider": "memory"}


class TestMarkerToCapability:
    """Tests for MARKER_TO_CAPABILITY constant."""

    def test_all_expected_markers_present(self):
        expected = {
            "basic_storage",
            "transactional",
            "atomic_transactions",
            "raw_queries",
            "schema_management",
            "native_json",
            "native_array",
        }
        assert set(MARKER_TO_CAPABILITY.keys()) == expected

    def test_basic_storage_maps_to_composite(self):
        assert (
            MARKER_TO_CAPABILITY["basic_storage"] == DatabaseCapabilities.BASIC_STORAGE
        )

    def test_transactional_maps_to_both_flags(self):
        caps = MARKER_TO_CAPABILITY["transactional"]
        assert DatabaseCapabilities.TRANSACTIONS in caps
        assert DatabaseCapabilities.SIMULATED_TRANSACTIONS in caps


class TestResolveDbConfig:
    """Tests for resolve_db_config function."""

    def test_builtin_memory(self):
        """--db=MEMORY returns built-in memory config."""
        result = resolve_db_config(db_key="MEMORY")
        assert result == {"provider": "memory"}

    def test_builtin_postgresql(self):
        """--db=POSTGRESQL returns built-in postgresql config."""
        result = resolve_db_config(db_key="POSTGRESQL")
        assert result["provider"] == "postgresql"
        assert "database_uri" in result

    def test_custom_provider_takes_priority(self):
        """--db-provider takes priority over --db."""
        result = resolve_db_config(
            db_key="MEMORY",
            db_provider="dynamodb",
            db_uri="dynamodb://localhost:8000",
        )
        assert result == {
            "provider": "dynamodb",
            "database_uri": "dynamodb://localhost:8000",
        }

    def test_custom_provider_with_extras(self):
        """--db-extra JSON is merged into the config."""
        result = resolve_db_config(
            db_provider="dynamodb",
            db_extra='{"region": "us-east-1", "pool_size": 5}',
        )
        assert result["provider"] == "dynamodb"
        assert result["region"] == "us-east-1"
        assert result["pool_size"] == 5

    def test_custom_provider_without_uri(self):
        """--db-provider without --db-uri omits database_uri."""
        result = resolve_db_config(db_provider="dynamodb")
        assert result == {"provider": "dynamodb"}

    def test_unknown_db_key_becomes_provider_name(self):
        """An unknown --db value is lowercased and used as provider name."""
        result = resolve_db_config(db_key="DYNAMODB")
        assert result == {"provider": "dynamodb"}


class TestCollectionModifyItems:
    """Tests for pytest_collection_modifyitems hook."""

    def _make_item(self, markers: list[str] | None = None) -> mock.MagicMock:
        """Build a mock pytest Item with given markers."""
        item = mock.MagicMock(spec=["fixturenames", "get_closest_marker"])
        item.fixturenames = []
        markers = markers or []

        def get_closest_marker(name):
            if name in markers:
                return mock.MagicMock()
            return None

        item.get_closest_marker = get_closest_marker
        return item

    def test_db_fixture_injected_for_basic_storage(self):
        """Tests marked basic_storage get the db fixture."""
        item = self._make_item(markers=["basic_storage"])
        config = mock.MagicMock()

        pytest_collection_modifyitems(config, [item])

        assert "db" in item.fixturenames

    def test_db_fixture_injected_for_database_marker(self):
        """Tests marked 'database' get the db fixture."""
        item = self._make_item(markers=["database"])
        config = mock.MagicMock()

        pytest_collection_modifyitems(config, [item])

        assert "db" in item.fixturenames

    def test_db_fixture_not_injected_for_unmarked(self):
        """Tests without capability markers don't get the db fixture."""
        item = self._make_item(markers=[])
        config = mock.MagicMock()

        pytest_collection_modifyitems(config, [item])

        assert "db" not in item.fixturenames

    def test_db_fixture_not_duplicated(self):
        """If db is already in fixturenames, it's not added again."""
        item = self._make_item(markers=["basic_storage"])
        item.fixturenames = ["db"]
        config = mock.MagicMock()

        pytest_collection_modifyitems(config, [item])

        assert item.fixturenames.count("db") == 1

    def test_capability_annotated_on_item(self):
        """Capability info is stored on the item for the skip fixture."""
        item = self._make_item(markers=["native_json"])
        config = mock.MagicMock()

        pytest_collection_modifyitems(config, [item])

        marker_name, caps = item._database_required_capability
        assert marker_name == "native_json"
        assert caps == DatabaseCapabilities.NATIVE_JSON

    def test_transactional_capability_annotation(self):
        """Transactional marker annotates with both transaction flags."""
        item = self._make_item(markers=["transactional"])
        config = mock.MagicMock()

        pytest_collection_modifyitems(config, [item])

        marker_name, caps = item._database_required_capability
        assert marker_name == "transactional"
        assert DatabaseCapabilities.TRANSACTIONS in caps
        assert DatabaseCapabilities.SIMULATED_TRANSACTIONS in caps

    def test_no_annotation_for_unmarked(self):
        """Unmarked tests don't get capability annotation."""
        item = self._make_item(markers=[])
        config = mock.MagicMock()

        pytest_collection_modifyitems(config, [item])

        assert not hasattr(item, "_database_required_capability")


@pytest.mark.no_test_domain
class TestConformancePluginIntegration:
    """Integration tests running the plugin in isolated subprocess pytest sessions.

    Each test creates a temporary directory with a conftest that loads
    the conformance plugin, then runs pytest as a subprocess against the
    generic test files. This verifies fixtures, markers, and capability-skipping
    work end-to-end.
    """

    def _run_pytest_subprocess(
        self, tmp_path: Path, conftest_content: str, extra_args: list[str]
    ) -> subprocess.CompletedProcess[str]:
        """Run pytest in a subprocess with an isolated conftest."""
        conftest = tmp_path / "conftest.py"
        conftest.write_text(conftest_content)

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "--override-ini=addopts=",
            "--tb=short",
            "-q",
            *extra_args,
        ]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=60,
        )

    def test_plugin_runs_basic_storage_tests(self, tmp_path: Path):
        """The conformance plugin can run basic_storage tests against memory."""
        from protean.testing import get_generic_test_dir

        generic_dir = get_generic_test_dir()
        result = self._run_pytest_subprocess(
            tmp_path,
            'pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]',
            [
                str(generic_dir / "test_crud.py"),
                "--db=MEMORY",
                "-m",
                "basic_storage",
            ],
        )
        assert result.returncode == 0
        assert "passed" in result.stdout

    def test_plugin_skips_unsupported_capabilities(self, tmp_path: Path):
        """Tests for capabilities the provider lacks are skipped."""
        from protean.testing import get_generic_test_dir

        generic_dir = get_generic_test_dir()
        result = self._run_pytest_subprocess(
            tmp_path,
            'pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]',
            [
                str(generic_dir / "test_native_json.py"),
                "--db=MEMORY",
            ],
        )
        # Memory lacks NATIVE_JSON — all tests should be skipped
        assert result.returncode == 0
        assert "skipped" in result.stdout
        assert "failed" not in result.stdout

    def test_plugin_works_with_user_overridden_db_config(self, tmp_path: Path):
        """User can override db_config fixture in their own conftest."""
        from protean.testing import get_generic_test_dir

        generic_dir = get_generic_test_dir()
        conftest = """
import pytest

pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]

@pytest.fixture(scope="session")
def db_config():
    return {"provider": "memory"}
"""
        result = self._run_pytest_subprocess(
            tmp_path,
            conftest,
            [
                str(generic_dir / "test_crud.py"),
                "-m",
                "basic_storage",
            ],
        )
        assert result.returncode == 0
        assert "passed" in result.stdout
