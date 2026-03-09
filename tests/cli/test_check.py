"""Tests for the ``protean check`` CLI command.

Covers exit codes, output formats, error handling, --level filter, and --quiet mode.
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
            "diagnostics",
            "counts",
        }
        assert set(data.keys()) == expected_keys
        assert set(data["counts"].keys()) == {"errors", "warnings", "infos"}


# Domain with diagnostics at multiple levels (test25)
_DIAG_DOMAIN = "tests/support/domains/test25/domain25.py:domain"
# Domain with a structural error (test26)
_ERR_DOMAIN = "tests/support/domains/test26/domain26.py:domain"
# Domain with only info-level diagnostics (test27)
_INFO_DOMAIN = "tests/support/domains/test27/domain27.py:domain"


@pytest.mark.no_test_domain
class TestCheckRichOutput:
    """Rich (default) output covers error, warning, and info display paths."""

    def test_rich_output_with_warnings_and_info(self):
        """Rich output for a domain with warnings and info diagnostics."""
        result = runner.invoke(
            app,
            ["check", "-d", _DIAG_DOMAIN],
        )
        assert result.exit_code == 2
        # Warning section markers
        assert "WARN" in result.output
        assert "warning(s)" in result.output
        assert "!" in result.output
        # Info section markers
        assert "info(s)" in result.output
        assert "·" in result.output

    def test_rich_output_with_errors(self):
        """Rich output for a domain with structural errors."""
        result = runner.invoke(
            app,
            ["check", "-d", _ERR_DOMAIN],
        )
        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "error(s)" in result.output
        assert "✗" in result.output

    def test_rich_output_info_only_shows_info_message(self):
        """Rich output for a domain with only info diagnostics."""
        result = runner.invoke(
            app,
            ["check", "-d", _INFO_DOMAIN],
        )
        assert result.exit_code == 0
        assert "INFO" in result.output
        assert "All checks passed with informational findings." in result.output

    def test_rich_output_clean_domain_shows_pass_message(self):
        result = runner.invoke(
            app,
            ["check", "-d", "tests/support/domains/test19/domain19.py:domain"],
        )
        assert result.exit_code == 0
        assert "All checks passed." in result.output


@pytest.mark.no_test_domain
class TestCheckLevelFilter:
    """The --level flag filters diagnostics by severity threshold."""

    def test_level_warning_excludes_info(self):
        result = runner.invoke(
            app,
            ["check", "-d", _DIAG_DOMAIN, "-f", "json", "--level", "warning"],
        )
        data = json.loads(result.output)
        levels = {d["level"] for d in data["diagnostics"]}
        assert "info" not in levels
        # Warnings should still be present
        assert data["counts"]["warnings"] > 0
        assert data["counts"]["infos"] == 0

    def test_level_error_excludes_warnings_and_info(self):
        result = runner.invoke(
            app,
            ["check", "-d", _DIAG_DOMAIN, "-f", "json", "--level", "error"],
        )
        data = json.loads(result.output)
        assert data["diagnostics"] == []
        assert data["counts"]["warnings"] == 0
        assert data["counts"]["infos"] == 0

    def test_level_info_shows_all(self):
        result = runner.invoke(
            app,
            ["check", "-d", _DIAG_DOMAIN, "-f", "json", "--level", "info"],
        )
        data = json.loads(result.output)
        levels = {d["level"] for d in data["diagnostics"]}
        assert "warning" in levels
        assert "info" in levels

    def test_invalid_level_exits_with_error(self):
        result = runner.invoke(
            app,
            ["check", "-d", _DIAG_DOMAIN, "--level", "critical"],
        )
        assert result.exit_code != 0
        assert "Invalid --level" in result.output


@pytest.mark.no_test_domain
class TestCheckQuietMode:
    """The --quiet flag shows only a summary line."""

    def test_quiet_clean_domain(self):
        result = runner.invoke(
            app,
            ["check", "-d", "tests/support/domains/test19/domain19.py:domain", "-q"],
        )
        assert result.exit_code == 0
        assert "TEST19" in result.output
        assert "pass" in result.output
        assert "errors=0" in result.output

    def test_quiet_domain_with_warnings(self):
        result = runner.invoke(
            app,
            ["check", "-d", _DIAG_DOMAIN, "-q"],
        )
        assert result.exit_code == 2
        assert "warn" in result.output

    def test_quiet_suppresses_details(self):
        """Quiet mode should not show individual diagnostic messages."""
        result = runner.invoke(
            app,
            ["check", "-d", _DIAG_DOMAIN, "-q"],
        )
        # Should not contain diagnostic detail markers
        assert "✗" not in result.output
        assert "!" not in result.output
        assert "·" not in result.output
