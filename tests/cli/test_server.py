import logging
import os
import sys
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.exceptions import NoDomainException
from protean.server.engine import Engine
from tests.shared import change_working_directory_to

runner = CliRunner()


class TestServerCommand:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_server_with_invalid_domain(self):
        """Test that the server command fails when domain is not provided"""
        args = ["server", "--domain", "foobar"]
        result = runner.invoke(app, args)
        assert result.exit_code != 0
        assert isinstance(result.exception, SystemExit)
        assert "Aborted" in result.output

    def test_server_with_valid_domain(self):
        """Test that the server command initializes and runs with a valid domain"""
        change_working_directory_to("test7")

        with patch.object(Engine, "run", return_value=None) as mock_run:
            args = ["server", "--domain", "publishing7.py"]
            result = runner.invoke(app, args)

            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_server_initializes_domain(self):
        """Test that the server command correctly initializes the domain"""
        change_working_directory_to("test7")

        with patch(
            "protean.cli.derive_domain", return_value=MagicMock()
        ) as mock_derive_domain:  # Correct the patch path here
            with patch("protean.server.engine.Engine.run") as mock_engine_run:
                args = ["server", "--domain", "publishing7.py"]
                result = runner.invoke(app, args)

                assert result.exit_code == 0
                mock_derive_domain.assert_called_once_with("publishing7.py")
                mock_engine_run.assert_called_once()

    def test_server_start_successfully(self):
        change_working_directory_to("test7")

        args = ["shell", "--domain", "publishing7.py"]

        # Run the shell command
        result = runner.invoke(app, args)

        # Assertions
        assert result.exit_code == 0

    def test_server_handles_no_domain_exception(self):
        """Test that the server command gracefully handles NoDomainException"""
        with patch(
            "protean.cli.derive_domain",
            side_effect=NoDomainException("Domain not found"),
        ):
            args = ["server", "--domain", "invalid_domain.py"]
            result = runner.invoke(app, args)

            assert result.exit_code != 0
            assert "Error loading Protean domain: Domain not found" in result.output
            assert isinstance(result.exception, SystemExit)

    def test_server_runs_in_test_mode(self):
        """Test that the server runs in test mode when the flag is provided"""
        change_working_directory_to("test7")

        # Mock the Engine class entirely
        with patch("protean.cli.Engine") as MockEngine:
            mock_engine_instance = MockEngine.return_value
            mock_engine_instance.exit_code = 0  # Set the exit code

            args = ["server", "--domain", "publishing7.py", "--test-mode"]
            result = runner.invoke(app, args)

            # Assertions
            assert result.exit_code == 0
            mock_engine_instance.run.assert_called_once()  # Ensure `run` was called
            MockEngine.assert_called_once_with(
                ANY, test_mode=True, debug=False
            )  # Ensure Engine was instantiated with the correct arguments

    def test_server_runs_in_debug_mode(self):
        """Test that the server runs in debug mode and sets the correct logger level"""
        change_working_directory_to("test7")

        # Mock the logger used in the Engine class
        with patch("protean.server.engine.logger") as mock_logger:
            args = ["server", "--domain", "publishing7.py", "--debug"]
            result = runner.invoke(app, args)

            assert result.exit_code == 0
            mock_logger.setLevel.assert_called_once_with(logging.DEBUG)

    def test_server_raises_system_exit_on_error_in_run(self):
        """Test that the server command raises a TyperExit with the correct exit code on error in run"""
        change_working_directory_to("test7")

        with patch("protean.cli.Engine.run", side_effect=SystemExit(1)):
            args = ["server", "--domain", "publishing7.py"]
            result = runner.invoke(app, args)

            assert result.exit_code == 1
            assert isinstance(result.exception, SystemExit)

    def test_server_raises_typer_exit_on_non_zero_exit_code_in_run(self):
        """Test that the server command raises a TyperExit with the correct exit code on non-zero exit code in run"""
        change_working_directory_to("test7")

        # Use a specific non-zero exit code to verify it's passed correctly to typer.Exit
        expected_exit_code = 42

        # Create a mock engine instance with the exit_code property
        mock_engine = MagicMock()
        mock_engine.exit_code = expected_exit_code

        # Patch the Engine class to return our mock instance
        with patch("protean.cli.Engine", return_value=mock_engine):
            args = ["server", "--domain", "publishing7.py"]
            result = runner.invoke(app, args)

            # Verify that the exit code matches exactly what was set in Engine.exit_code
            assert result.exit_code == expected_exit_code
            assert isinstance(result.exception, SystemExit)

    @pytest.mark.skip(reason="Not implemented")
    def test_that_server_processes_messages_on_start(self):
        # Start in non-test mode
        # Ensure messages are processed
        # Manually shutdown with `asyncio.create_task(engine.shutdown())`
        pass

    def test_server_with_max_workers(self):
        """Test that the server command handles the MAX_WORKERS input (future implementation)"""
        # This is a placeholder for when MAX_WORKERS is implemented as a command-line input
        pass
