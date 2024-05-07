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
        assert result.output == "Aborted.\n"

    def test_server_start_successfully(self):
        change_working_directory_to("test7")

        args = ["shell", "--domain", "publishing7.py"]

        # Run the shell command
        result = runner.invoke(app, args)

        # Assertions
        assert result.exit_code == 0

    def test_server_start_failure(self):
        pass

    def test_that_server_processes_messages_on_start(self):
        # Start in non-test mode
        # Ensure messages are processed
        # Manually shutdown with `asyncio.create_task(engine.shutdown())`
        pass

    def test_debug_mode(self):
        # Test debug mode is saved and correct logger level is set
        pass

    def test_that_server_processes_messages_in_test_mode(self):
        pass

    def test_that_server_handles_exceptions_elegantly(self):
        pass

    def test_that_last_read_positions_are_saved(self):
        pass
