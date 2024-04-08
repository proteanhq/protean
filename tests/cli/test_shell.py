import os
import sys

from pathlib import Path

import pytest

from typer.testing import CliRunner

from protean.cli import app
from protean.exceptions import NoDomainException
from tests.shared import change_working_directory_to

runner = CliRunner()


class TestShellCommand:
    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Reset sys.path after every test run"""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_shell_command_success(self):
        change_working_directory_to("test7")

        args = ["shell", "publishing.py"]

        # Run the shell command
        result = runner.invoke(app, args)

        # Assertions
        print(result.output)
        assert result.exit_code == 0

    def test_shell_command_raises_no_domain_exception_when_no_domain_is_found(self):
        change_working_directory_to("test7")

        args = ["shell", "foobar"]

        # Run the shell command and expect it to raise an exception
        with pytest.raises(NoDomainException):
            runner.invoke(app, args, catch_exceptions=False)
