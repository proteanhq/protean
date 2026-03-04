"""Tests for CLI `protean ir show` command."""

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from tests.shared import change_working_directory_to

runner = CliRunner()


class TestIRShowJSON:
    """Tests for `protean ir show --format json`."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_json_output_is_valid(self):
        change_working_directory_to("test7")
        result = runner.invoke(app, ["ir", "show", "-d", "publishing7.py"])
        assert result.exit_code == 0
        ir = json.loads(result.output)
        assert isinstance(ir, dict)

    def test_json_output_has_top_level_keys(self):
        change_working_directory_to("test7")
        result = runner.invoke(app, ["ir", "show", "-d", "publishing7.py"])
        ir = json.loads(result.output)
        assert "$schema" in ir
        assert "ir_version" in ir
        assert "checksum" in ir
        assert "clusters" in ir
        assert "domain" in ir
        assert "elements" in ir

    def test_json_is_default_format(self):
        change_working_directory_to("test7")
        result = runner.invoke(app, ["ir", "show", "-d", "publishing7.py"])
        # Should parse as JSON without --format flag
        ir = json.loads(result.output)
        assert ir["domain"]["name"] == "TEST7"


class TestIRShowSummary:
    """Tests for `protean ir show --format summary`."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_summary_output_contains_domain_name(self):
        change_working_directory_to("test7")
        result = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "-f", "summary"]
        )
        assert result.exit_code == 0
        assert "Domain:" in result.output

    def test_summary_output_contains_ir_version(self):
        change_working_directory_to("test7")
        result = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "-f", "summary"]
        )
        assert "IR Version:" in result.output

    def test_summary_output_contains_checksum(self):
        change_working_directory_to("test7")
        result = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "-f", "summary"]
        )
        assert "Checksum:" in result.output

    def test_summary_output_contains_element_counts(self):
        change_working_directory_to("test7")
        result = runner.invoke(
            app, ["ir", "show", "-d", "publishing7.py", "-f", "summary"]
        )
        assert "Element Counts" in result.output


class TestIRShowErrors:
    """Tests for error handling in `protean ir show`."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        original_path = sys.path[:]
        cwd = Path.cwd()
        yield
        sys.path[:] = original_path
        os.chdir(cwd)

    def test_invalid_domain_aborts(self):
        change_working_directory_to("test7")
        result = runner.invoke(app, ["ir", "show", "-d", "nonexistent_domain.py"])
        assert result.exit_code != 0
