"""Tests for CLI top-level exception handler.

Verifies that the ``handle_cli_exceptions`` decorator / ``cli_exception_handler``
context manager logs unhandled exceptions with structured output and preserves
non-zero exit codes.
"""

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


class TestCliExceptionHandler:
    def test_server_command_logs_exception_on_failure(self):
        """When a command raises an unhandled exception, it is logged."""
        change_working_directory_to("test7")

        with patch(
            "protean.cli.derive_domain",
            side_effect=RuntimeError("boom"),
        ):
            with patch("protean.cli._helpers.logger") as mock_logger:
                result = runner.invoke(
                    app,
                    ["server", "--domain", "publishing7.py"],
                )

                assert result.exit_code != 0
                assert isinstance(result.exception, RuntimeError)

                # Check that the exception handler called logger.exception
                mock_logger.exception.assert_called_once()
                call_args = mock_logger.exception.call_args
                assert call_args[0][0] == "cli.command_failed"
                assert call_args[1]["command"] == "server"

    def test_server_exit_code_nonzero_on_failure(self):
        """Unhandled exception produces a non-zero exit code."""
        change_working_directory_to("test7")

        with patch(
            "protean.cli.derive_domain",
            side_effect=RuntimeError("boom"),
        ):
            result = runner.invoke(
                app,
                ["server", "--domain", "publishing7.py"],
            )

            assert result.exit_code != 0
            assert isinstance(result.exception, RuntimeError)

    def test_shell_command_logs_exception_on_failure(self):
        """The exception handler is installed on the shell command."""
        with patch(
            "protean.cli.shell.derive_domain",
            side_effect=RuntimeError("shell boom"),
        ):
            with patch("protean.cli._helpers.logger") as mock_logger:
                result = runner.invoke(app, ["shell", "--domain", "foobar"])

                assert result.exit_code != 0
                assert isinstance(result.exception, RuntimeError)
                mock_logger.exception.assert_called_once()
                assert mock_logger.exception.call_args[1]["command"] == "shell"

    def test_check_command_logs_exception_on_failure(self):
        """The exception handler is installed on the check command."""
        with patch(
            "protean.cli.check.derive_domain",
            side_effect=RuntimeError("check boom"),
        ):
            with patch("protean.cli._helpers.logger") as mock_logger:
                result = runner.invoke(app, ["check", "--domain", "foobar"])

                assert result.exit_code != 0
                assert isinstance(result.exception, RuntimeError)
                mock_logger.exception.assert_called_once()
                assert mock_logger.exception.call_args[1]["command"] == "check"

    def test_abort_is_not_caught(self):
        """typer.Abort passes through the handler without logging."""
        change_working_directory_to("test7")

        with patch("protean.cli._helpers.logger") as mock_logger:
            result = runner.invoke(
                app,
                ["server", "--domain", "foobar"],
            )

            # Abort produces exit code 1 but is NOT a RuntimeError
            assert result.exit_code != 0
            assert not isinstance(result.exception, RuntimeError)
            mock_logger.exception.assert_not_called()

    def test_typer_exit_is_not_caught(self):
        """typer.Exit passes through the handler without logging."""
        change_working_directory_to("test7")

        with patch("protean.cli.Engine") as MockEngine:
            mock_engine = MockEngine.return_value
            mock_engine.exit_code = 42

            result = runner.invoke(
                app,
                ["server", "--domain", "publishing7.py"],
            )

            assert result.exit_code == 42
