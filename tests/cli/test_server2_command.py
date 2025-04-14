"""Tests for the server2 CLI command"""

import sys
from unittest import mock

import pytest
from typer.testing import CliRunner

from protean.cli import app


@pytest.mark.skipif("fastapi" not in sys.modules, reason="FastAPI not installed")
def test_server2_command_help():
    """Test that the server2 command help is displayed correctly"""
    runner = CliRunner()
    result = runner.invoke(app, ["server2", "--help"])
    assert result.exit_code == 0
    assert "Run FastAPI Server" in result.stdout


@pytest.mark.skipif("fastapi" not in sys.modules, reason="FastAPI not installed")
def test_server2_command_execution():
    """Test that the server2 command executes correctly"""
    runner = CliRunner()

    # Mock the FastAPIServer to prevent actually starting the server
    with mock.patch("protean.server.fastapi_server.FastAPIServer") as mock_server_cls:
        mock_server = mock.MagicMock()
        mock_server_cls.return_value = mock_server

        result = runner.invoke(app, ["server2", "--domain=test_domain"])

        # Verify the command succeeded
        assert result.exit_code == 0

        # Verify the server was initialized with the correct parameters
        mock_server_cls.assert_called_once_with(domain_path="test_domain", debug=False)

        # Verify the server was run with the correct parameters
        mock_server.run.assert_called_once_with(host="0.0.0.0", port=8000)


@pytest.mark.skipif("fastapi" not in sys.modules, reason="FastAPI not installed")
def test_server2_command_with_custom_parameters():
    """Test that the server2 command accepts custom parameters"""
    runner = CliRunner()

    # Mock the FastAPIServer to prevent actually starting the server
    with mock.patch("protean.server.fastapi_server.FastAPIServer") as mock_server_cls:
        mock_server = mock.MagicMock()
        mock_server_cls.return_value = mock_server

        result = runner.invoke(
            app,
            [
                "server2",
                "--domain=test_domain",
                "--host=127.0.0.1",
                "--port=5000",
                "--debug",
            ],
        )

        # Verify the command succeeded
        assert result.exit_code == 0

        # Verify the server was initialized with the correct parameters
        mock_server_cls.assert_called_once_with(domain_path="test_domain", debug=True)

        # Verify the server was run with the correct parameters
        mock_server.run.assert_called_once_with(host="127.0.0.1", port=5000)
