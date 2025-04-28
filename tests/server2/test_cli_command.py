import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from protean.cli import app as cli_app
from protean.utils.domain_discovery import derive_domain
from tests.shared import change_working_directory_to


class TestServerCliCommand:
    """Test suite for the server2 CLI command."""

    @pytest.fixture
    def runner(self):
        """CLI runner fixture."""
        return CliRunner()

    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    @pytest.mark.fastapi
    def test_server2_help_command(self, runner):
        """Test the help command for server2."""
        result = runner.invoke(cli_app, ["server2", "--help"])
        assert result.exit_code == 0
        assert "Run the FastAPI server for Protean applications" in result.stdout

    @pytest.mark.fastapi
    @patch("protean.cli.server2.ProteanFastAPIServer")
    def test_server2_command_with_defaults(self, mock_server, runner):
        change_working_directory_to("test7")

        # Set up the mock
        mock_instance = mock_server.return_value

        # Derive the domain for crosscheck
        domain = derive_domain("publishing7.py")

        # Run the command with early exit to avoid actually starting the server
        with patch.object(mock_instance, "run"):
            args = ["server2", "--domain", "publishing7.py"]
            result = runner.invoke(cli_app, args)

            assert result.exit_code == 0

            # Verify the command tried to start with default settings
            mock_server.assert_called_once_with(
                domain=domain,
                debug=False,
                enable_cors=True,
                cors_origins=None,
            )
            mock_instance.run.assert_called_once()

    @pytest.mark.fastapi
    @patch("protean.cli.server2.ProteanFastAPIServer")
    def test_server2_command_with_custom_args(self, mock_server, runner):
        change_working_directory_to("test7")

        mock_instance = mock_server.return_value

        domain = derive_domain("publishing7.py")

        # Run the command with early exit to avoid actually starting the server
        with patch.object(mock_instance, "run") as mock_run:
            args = [
                "server2",
                "--domain",
                "publishing7.py",
                "--host",
                "127.0.0.1",
                "--port",
                "5000",
                "--debug",
            ]
            result = runner.invoke(cli_app, args, catch_exceptions=True)

            assert result.exit_code == 0

            # Verify the command tried to start with custom settings
            mock_server.assert_called_once_with(
                domain=domain,
                debug=True,
                enable_cors=True,
                cors_origins=None,
            )
            mock_instance.run.assert_called_once_with(host="127.0.0.1", port=5000)

    @pytest.mark.fastapi
    @patch("protean.cli.server2.ProteanFastAPIServer")
    def test_server2_command_disable_cors(self, mock_server, runner, test_domain):
        change_working_directory_to("test7")

        mock_instance = mock_server.return_value

        domain = derive_domain("publishing7.py")

        # Run the command with early exit to avoid actually starting the server
        with patch.object(mock_instance, "run"):
            result = runner.invoke(
                cli_app,
                ["server2", "--domain", "publishing7.py", "--no-cors"],
                catch_exceptions=True,
            )

            assert result.exit_code == 0

        # Verify CORS was disabled
        mock_server.assert_called_once_with(
            domain=domain,
            debug=False,
            enable_cors=False,
            cors_origins=None,
        )

    @pytest.mark.fastapi
    @patch("protean.cli.server2.ProteanFastAPIServer")
    def test_server2_command_with_cors_origins(self, mock_server, runner):
        """Test the server2 command with custom CORS origins."""
        change_working_directory_to("test7")

        mock_instance = mock_server.return_value

        domain = derive_domain("publishing7.py")

        # Run the command with early exit to avoid actually starting the server
        with patch.object(mock_instance, "run"):
            result = runner.invoke(
                cli_app,
                [
                    "server2",
                    "--domain",
                    "publishing7.py",
                    "--cors-origins",
                    "http://localhost:3000,https://example.com",
                ],
                catch_exceptions=True,
            )

            assert result.exit_code == 0

        # Verify CORS origins were set correctly
        mock_server.assert_called_once_with(
            domain=domain,
            debug=False,
            enable_cors=True,
            cors_origins=["http://localhost:3000", "https://example.com"],
        )

    @pytest.mark.fastapi
    def test_server2_command_cors_origins_with_cors_disabled(self, runner):
        """Test that specifying CORS origins when CORS is disabled raises an error."""
        result = runner.invoke(
            cli_app,
            [
                "server2",
                "--domain",
                "publishing7.py",
                "--no-cors",
                "--cors-origins",
                "http://localhost:3000",
            ],
            catch_exceptions=True,
        )

        assert result.exit_code != 0
        assert "Cannot specify CORS origins when CORS is disabled" in result.stdout

    @pytest.mark.fastapi
    def test_server2_command_domain_error(self, runner):
        # Run the command
        result = runner.invoke(cli_app, ["server2", "--domain", "nonexistent.py"])

        # Verify error handling
        assert result.exit_code != 0
        assert (
            "Error loading Protean domain: Could not import 'nonexistent'"
            in result.stdout
        )
