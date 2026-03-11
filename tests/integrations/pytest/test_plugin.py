"""Tests for the Protean pytest plugin.

Each test directly invokes the plugin hook functions with mock objects,
so the tests work regardless of whether the ``pytest11`` entry point is
installed.
"""

import os
from unittest import mock

from protean.integrations.pytest.plugin import pytest_addoption, pytest_configure


class TestPluginHooks:
    """Tests for plugin auto-configuration hooks."""

    def test_protean_env_set_by_default(self):
        """pytest_configure sets PROTEAN_ENV=test when no --protean-env is passed."""
        config = mock.MagicMock()
        config.getoption.return_value = "test"

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROTEAN_ENV", None)
            pytest_configure(config)
            assert os.environ.get("PROTEAN_ENV") == "test"

    def test_protean_env_option_registered(self):
        """pytest_addoption registers --protean-env and --update-snapshots."""
        parser = mock.MagicMock()
        pytest_addoption(parser)

        calls = parser.addoption.call_args_list
        option_names = [call.args[0] for call in calls]
        assert "--protean-env" in option_names
        assert "--update-snapshots" in option_names

    def test_standard_markers_registered(self):
        """pytest_configure registers standard markers."""
        config = mock.MagicMock()
        config.getoption.return_value = "test"

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PROTEAN_ENV", None)
            pytest_configure(config)

        marker_calls = [call.args for call in config.addinivalue_line.call_args_list]
        marker_lines = [args[1] for args in marker_calls if args[0] == "markers"]
        marker_names = [m.split(":")[0].strip() for m in marker_lines]

        assert "domain" in marker_names
        assert "application" in marker_names
        assert "integration" in marker_names
        assert "slow" in marker_names

    def test_update_snapshots_sets_module_flag(self):
        """pytest_configure propagates --update-snapshots to protean.testing."""
        import protean.testing as testing_mod

        config = mock.MagicMock()

        def _getoption(name, default=None):
            if name == "--update-snapshots":
                return True
            return default or "test"

        config.getoption.side_effect = _getoption

        original = testing_mod._update_snapshots
        try:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PROTEAN_ENV", None)
                pytest_configure(config)
            assert testing_mod._update_snapshots is True
        finally:
            testing_mod._update_snapshots = original

    def test_protean_env_respects_existing(self):
        """Plugin uses setdefault — doesn't overwrite pre-existing PROTEAN_ENV."""
        config = mock.MagicMock()
        config.getoption.return_value = "test"

        with mock.patch.dict(os.environ, {"PROTEAN_ENV": "staging"}):
            pytest_configure(config)
            assert os.environ["PROTEAN_ENV"] == "staging"
