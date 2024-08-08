import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
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

    def test_server_start_successfully(self):
        change_working_directory_to("test7")

        args = ["shell", "--domain", "publishing7.py"]

        # Run the shell command
        result = runner.invoke(app, args)

        # Assertions
        assert result.exit_code == 0

    def test_that_server_processes_messages_on_start(self):
        # Start in non-test mode
        # Ensure messages are processed
        # Manually shutdown with `asyncio.create_task(engine.shutdown())`
        pass

    @pytest.mark.skip(reason="Not implemented")
    def test_debug_mode(self):
        # Test debug mode is saved and correct logger level is set
        pass
