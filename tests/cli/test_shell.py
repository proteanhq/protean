import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
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

        args = ["shell", "--domain", "publishing7.py"]

        # Run the shell command
        result = runner.invoke(app, args)

        # Assertions
        assert result.exit_code == 0

    def test_shell_command_with_no_explicit_domain_and_domain_py_file(self):
        change_working_directory_to("test10")

        args = ["shell"]

        # Run the shell command
        result = runner.invoke(app, args)

        # Assertions
        assert result.exit_code == 0

    def test_shell_command_with_no_explicit_domain_and_subdomain_py_file(self):
        change_working_directory_to("test11")

        args = ["shell"]

        # Run the shell command
        result = runner.invoke(app, args)

        # Assertions
        assert result.exit_code == 0

    def test_shell_command_with_domain_attribute_name_as_domain(self):
        change_working_directory_to("test1")

        args = ["shell", "--domain", "basic"]

        # Run the shell command
        result = runner.invoke(app, args)

        # Assertions
        assert result.exit_code == 0

    def test_shell_command_with_domain_attribute_name_as_subdomain(self):
        change_working_directory_to("test12")

        args = ["shell", "--domain", "foo12"]

        # Run the shell command
        result = runner.invoke(app, args)

        # Assertions
        assert result.exit_code == 0

    def test_shell_command_raises_no_domain_exception_when_no_domain_is_found(self):
        args = ["shell", "--domain", "foobar"]

        # Run the shell command and expect it to raise an exception
        result = runner.invoke(app, args, catch_exceptions=False)
        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)
        assert "Aborted" in result.output

    def test_shell_command_with_traverse_option(self):
        change_working_directory_to("test7")

        args = ["shell", "--domain", "publishing7.py", "--traverse"]

        # Run the shell command
        result = runner.invoke(app, args)

        assert "Traversing directory to load all modules..." in result.stdout
