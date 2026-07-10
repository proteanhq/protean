"""Tests for CLI global logging flags (--log-level, --log-format, --log-config).

Verifies the Typer callback wires up logging correctly and that the
removed --debug flag is rejected in favour of --log-level DEBUG.
"""

import json
import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from tests.shared import change_working_directory_to

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reset_path():
    """Reset sys.path and cwd after every test run."""
    original_path = sys.path[:]
    cwd = Path.cwd()
    yield
    sys.path[:] = original_path
    os.chdir(cwd)


class TestLogLevelFlag:
    def test_log_level_flag_applies_to_server(self):
        """--log-level DEBUG sets the root logger level to DEBUG."""
        change_working_directory_to("test7")

        with patch("protean.cli.Engine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.exit_code = 0

            result = runner.invoke(
                app,
                ["--log-level", "DEBUG", "server", "--domain", "publishing7.py"],
            )

            assert result.exit_code == 0
            assert logging.getLogger().level == logging.DEBUG

    def test_log_level_warning(self):
        """--log-level WARNING sets the root logger level to WARNING."""
        change_working_directory_to("test7")

        with patch("protean.cli.Engine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.exit_code = 0

            result = runner.invoke(
                app,
                ["--log-level", "WARNING", "server", "--domain", "publishing7.py"],
            )

            assert result.exit_code == 0
            assert logging.getLogger().level == logging.WARNING

    def test_log_level_invalid_value(self):
        """--log-level with an invalid value exits with error."""
        result = runner.invoke(app, ["--log-level", "BOGUS", "server"])

        assert result.exit_code != 0
        assert "Invalid log level" in result.output

    def test_log_level_case_insensitive(self):
        """--log-level accepts lowercase values."""
        change_working_directory_to("test7")

        with patch("protean.cli.Engine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.exit_code = 0

            result = runner.invoke(
                app,
                ["--log-level", "debug", "server", "--domain", "publishing7.py"],
            )

            assert result.exit_code == 0
            assert logging.getLogger().level == logging.DEBUG


class TestLogFormatFlag:
    def test_log_format_json_configures_json(self):
        """--log-format json configures structlog with JSON rendering."""
        import structlog

        change_working_directory_to("test7")

        with patch("protean.cli.Engine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.exit_code = 0

            result = runner.invoke(
                app,
                [
                    "--log-format",
                    "json",
                    "server",
                    "--domain",
                    "publishing7.py",
                ],
            )

            assert result.exit_code == 0
            # Verify structlog's processor chain ends with JSONRenderer
            cfg = structlog.get_config()
            processors = cfg.get("processors", [])
            assert len(processors) > 0, "Expected structlog processors"
            assert isinstance(processors[-1], structlog.processors.JSONRenderer)

    def test_log_format_invalid_value(self):
        """--log-format with an invalid value exits with error."""
        result = runner.invoke(app, ["--log-format", "xml", "server"])

        assert result.exit_code != 0
        assert "Invalid log format" in result.output


class TestLogConfigFlag:
    @pytest.mark.no_test_domain
    def test_log_config_file_applied(self, tmp_path):
        """--log-config with a valid JSON dictConfig applies the config."""
        change_working_directory_to("test7")

        # Provide a dictConfig that includes a handler so Domain.init()
        # sees root.handlers and skips auto-configuration.
        custom_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": "CRITICAL",
                    "stream": "ext://sys.stderr",
                },
            },
            "root": {"level": "CRITICAL", "handlers": ["console"]},
        }
        config_file = tmp_path / "log_config.json"
        config_file.write_text(json.dumps(custom_config))

        with patch("protean.cli.Engine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.exit_code = 0

            result = runner.invoke(
                app,
                [
                    "--log-config",
                    str(config_file),
                    "server",
                    "--domain",
                    "publishing7.py",
                ],
            )

            assert result.exit_code == 0
            assert logging.getLogger().level == logging.CRITICAL

    def test_log_config_nonexistent_file(self):
        """--log-config with a nonexistent file path exits with error."""
        result = runner.invoke(
            app,
            ["--log-config", "/nonexistent/path.json", "server"],
        )

        assert result.exit_code != 0

    def test_log_config_oserror_on_read(self, tmp_path):
        """--log-config prints an OSError message when the file can't be read."""
        # Create a valid file so Typer's exists=True check passes, then
        # patch read_text to simulate a read failure (e.g. permissions).
        config_file = tmp_path / "config.json"
        config_file.write_text("{}")

        with patch.object(
            type(config_file),
            "read_text",
            side_effect=PermissionError("Permission denied"),
        ):
            result = runner.invoke(
                app,
                ["--log-config", str(config_file), "server"],
            )

        assert result.exit_code == 2
        assert "Unable to read log config" in result.output

    def test_log_config_invalid_json(self, tmp_path):
        """--log-config with invalid JSON prints a JSONDecodeError message."""
        config_file = tmp_path / "bad.json"
        config_file.write_text("{ not valid json !!!")

        result = runner.invoke(
            app,
            ["--log-config", str(config_file), "server"],
        )

        assert result.exit_code == 2
        assert "Invalid JSON in log config" in result.output


class TestRemovedDebugFlag:
    def test_debug_flag_rejected(self):
        """--debug was removed; --log-level DEBUG is the supported replacement."""
        change_working_directory_to("test7")

        with patch("protean.cli.Engine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.exit_code = 0

            result = runner.invoke(
                app,
                ["server", "--domain", "publishing7.py", "--debug"],
            )

            assert result.exit_code == 2
            assert "No such option: --debug" in result.output

    def test_env_log_level_debug_replaces_debug_flag(self):
        """PROTEAN_LOG_LEVEL=DEBUG drives the server bootstrap to DEBUG.

        This is the documented multi-worker/reload replacement for the removed
        ``--debug`` flag: the bootstrap must honor the env var rather than
        forcing INFO, so the supervisor's log listener passes worker DEBUG
        records through.
        """
        change_working_directory_to("test7")

        with (
            patch("protean.cli.Engine") as MockEngine,
            patch.dict(os.environ, {"PROTEAN_LOG_LEVEL": "DEBUG"}),
        ):
            mock_engine = MockEngine.return_value
            mock_engine.exit_code = 0

            result = runner.invoke(app, ["server", "--domain", "publishing7.py"])

            assert result.exit_code == 0
            assert logging.getLogger().level == logging.DEBUG

    def test_bootstrap_defaults_to_info_without_env(self, monkeypatch):
        """Without PROTEAN_LOG_LEVEL, the server bootstrap stays at INFO."""
        change_working_directory_to("test7")
        monkeypatch.delenv("PROTEAN_LOG_LEVEL", raising=False)

        with patch("protean.cli.Engine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.exit_code = 0

            result = runner.invoke(app, ["server", "--domain", "publishing7.py"])

            assert result.exit_code == 0
            assert logging.getLogger().level == logging.INFO


class TestGlobalFlagsInHelpText:
    """Verify that global logging flags appear in ``protean --help``.

    Rich/Typer may inject ANSI escape codes into the output, so we strip
    them before matching to avoid false negatives on CI.
    """

    @staticmethod
    def _strip_ansi(text: str) -> str:
        import re

        return re.sub(r"\x1b\[[0-9;]*m", "", text)

    def test_help_shows_log_level(self):
        """protean --help shows --log-level in the output."""
        result = runner.invoke(app, ["--help"])
        assert "--log-level" in self._strip_ansi(result.output)

    def test_help_shows_log_format(self):
        """protean --help shows --log-format in the output."""
        result = runner.invoke(app, ["--help"])
        assert "--log-format" in self._strip_ansi(result.output)

    def test_help_shows_log_config(self):
        """protean --help shows --log-config in the output."""
        result = runner.invoke(app, ["--help"])
        assert "--log-config" in self._strip_ansi(result.output)
