"""Tests for the ``protean check`` CLI command.

Covers exit codes, output formats, and error handling.
"""

import json

import pytest

from typer.testing import CliRunner

from protean.cli import app

runner = CliRunner()


@pytest.mark.no_test_domain
class TestCheckCleanDomain:
    """A clean domain exits 0 with PASS status."""

    def test_rich_output_exit_code_0(self):
        result = runner.invoke(
            app,
            ["check", "-d", "tests/support/domains/test19/domain19.py:domain"],
        )
        assert result.exit_code == 0
        assert "PASS" in result.output

    def test_json_output_exit_code_0(self):
        result = runner.invoke(
            app,
            [
                "check",
                "-d",
                "tests/support/domains/test19/domain19.py:domain",
                "-f",
                "json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "pass"
        assert data["counts"]["errors"] == 0


@pytest.mark.no_test_domain
class TestCheckDomainLoadFailure:
    """Invalid domain path produces an error and non-zero exit."""

    def test_bad_domain_path(self):
        result = runner.invoke(app, ["check", "-d", "nonexistent.module"])
        assert result.exit_code != 0
        assert "Error" in result.output


@pytest.mark.no_test_domain
class TestCheckJsonStructure:
    """JSON output has the expected structure."""

    def test_json_has_expected_keys(self):
        result = runner.invoke(
            app,
            [
                "check",
                "-d",
                "tests/support/domains/test19/domain19.py:domain",
                "-f",
                "json",
            ],
        )
        data = json.loads(result.output)
        expected_keys = {
            "domain",
            "status",
            "errors",
            "warnings",
            "diagnostics",
            "counts",
        }
        assert set(data.keys()) == expected_keys
        assert set(data["counts"].keys()) == {"errors", "warnings", "diagnostics"}
