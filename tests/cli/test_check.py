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
# Domain with a deprecated aggregate (test28)
_DEPRECATED_DOMAIN = "tests/support/domains/test28/domain28.py:domain"
# Domain with a malformed (duplicate) upcaster chain (test30)
_UPCASTER_ERR_DOMAIN = "tests/support/domains/test30/domain30.py:domain"


@pytest.mark.no_test_domain
class TestCheckMalformedUpcasterChain:
    """A malformed upcaster chain is a structured error (exit 1), not a Python
    traceback (#1109) — the chain build used to crash `protean check`."""

    def test_malformed_chain_json_reports_structured_error(self):
        result = runner.invoke(app, ["check", "-d", _UPCASTER_ERR_DOMAIN, "-f", "json"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "fail"
        assert data["counts"]["errors"] >= 1
        upcaster_errors = [
            e for e in data["errors"] if "upcaster" in e["message"].lower()
        ]
        assert len(upcaster_errors) == 1
        assert upcaster_errors[0]["level"] == "error"

    def test_malformed_chain_rich_output_fails_without_traceback(self):
        result = runner.invoke(app, ["check", "-d", _UPCASTER_ERR_DOMAIN])
        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "Duplicate upcaster" in result.output
        assert "Traceback" not in result.output


@pytest.mark.no_test_domain
class TestCheckDeprecatedElement:
    """A deprecated element surfaces as a DEPRECATED_ELEMENT diagnostic through
    the CLI (the IR wiring landed in #812; this pins the end-to-end path)."""

    def test_deprecated_element_in_json_output(self):
        result = runner.invoke(app, ["check", "-d", _DEPRECATED_DOMAIN, "-f", "json"])
        # Deprecation is info-level only → exit 0.
        assert result.exit_code == 0
        data = json.loads(result.output)
        deprecated = [
            d for d in data["diagnostics"] if d["code"] == "DEPRECATED_ELEMENT"
        ]
        assert len(deprecated) == 1
        diag = deprecated[0]
        assert diag["level"] == "info"
        assert "Order" in diag["element"]
        assert "0.15" in diag["message"]
        assert "1.0" in diag["message"]

    def test_deprecated_element_in_rich_output(self):
        result = runner.invoke(app, ["check", "-d", _DEPRECATED_DOMAIN])
        assert result.exit_code == 0
        assert "DEPRECATED_ELEMENT" in result.output
        assert "Order" in result.output


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

    def test_level_filter_does_not_suppress_exit_code(self):
        """--level only affects display, not the exit code. A domain with
        warnings still exits 2 even when --level=error hides them."""
        result = runner.invoke(
            app,
            ["check", "-d", _DIAG_DOMAIN, "-f", "json", "--level", "error"],
        )
        # test25 has warnings → exit code 2 regardless of display filter
        assert result.exit_code == 2

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


# Domain with warnings, opting out of warning gating (level="error")
_LEVEL_ERROR_DOMAIN = "tests/support/domains/test32/domain32.py:domain"
# Info-only domain gating on info (level="info")
_LEVEL_INFO_DOMAIN = "tests/support/domains/test33/domain33.py:domain"
# Domain with an invalid [lint].level value
_LEVEL_INVALID_DOMAIN = "tests/support/domains/test34/domain34.py:domain"
# Domain with a structural error AND level="error" (error floor invariant)
_LEVEL_ERROR_WITH_ERROR_DOMAIN = "tests/support/domains/test35/domain35.py:domain"
# Domain with a malformed [lint].suppressions value
_BAD_SUPPRESSIONS_DOMAIN = "tests/support/domains/test36/domain36.py:domain"
# Domain with a malformed [lint] value (not a table at all)
_BAD_LINT_TABLE_DOMAIN = "tests/support/domains/test37/domain37.py:domain"


@pytest.mark.no_test_domain
class TestCheckLintLevelExitCode:
    """``[lint].level`` sets the config-driven exit-code severity floor.

    ``--level`` only affects display; ``[lint].level`` decides which severities
    fail CI. The default ("warn") reproduces the historical exit codes, which
    the surrounding suite already exercises (test25 warnings → 2, test27 info
    → 0). These tests cover the two non-default floors and validation.
    """

    def test_default_warn_gates_warnings(self):
        """Unset [lint].level defaults to "warn": warnings still exit 2."""
        result = runner.invoke(app, ["check", "-d", _DIAG_DOMAIN])
        assert result.exit_code == 2

    def test_default_warn_info_only_exits_zero(self):
        """Unset [lint].level: an info-only domain exits 0 (info never gates)."""
        result = runner.invoke(app, ["check", "-d", _INFO_DOMAIN])
        assert result.exit_code == 0

    def test_level_error_opts_out_of_warning_gating(self):
        """[lint].level="error": a domain with warnings now exits 0."""
        result = runner.invoke(app, ["check", "-d", _LEVEL_ERROR_DOMAIN])
        assert result.exit_code == 0

    def test_level_error_still_gates_errors(self):
        """[lint].level="error": a domain that sets the floor to "error" and
        has a structural error still exits 1 — the error floor is invariant."""
        result = runner.invoke(app, ["check", "-d", _LEVEL_ERROR_WITH_ERROR_DOMAIN])
        assert result.exit_code == 1

    def test_malformed_suppressions_exits_with_clean_error(self):
        """A non-integer [lint].suppressions count is a CLI error (exit 1),
        not a traceback — validated before the IR build runs."""
        result = runner.invoke(app, ["check", "-d", _BAD_SUPPRESSIONS_DOMAIN])
        assert result.exit_code == 1
        assert "[lint].suppressions" in result.output
        assert "non-negative integer" in result.output

    def test_malformed_lint_table_exits_with_clean_error(self):
        """A non-table [lint] value (e.g. ``lint = 5``) is a CLI error (exit 1),
        not a bare AttributeError — validated before any [lint] key is read."""
        result = runner.invoke(app, ["check", "-d", _BAD_LINT_TABLE_DOMAIN])
        assert result.exit_code == 1
        assert "[lint]" in result.output
        assert "must be a table" in result.output

    def test_level_info_gates_info(self):
        """[lint].level="info": an info-only domain now exits 2."""
        result = runner.invoke(app, ["check", "-d", _LEVEL_INFO_DOMAIN])
        assert result.exit_code == 2

    def test_invalid_lint_level_exits_with_error(self):
        """An invalid [lint].level value is a CLI error (exit 1)."""
        result = runner.invoke(app, ["check", "-d", _LEVEL_INVALID_DOMAIN])
        assert result.exit_code == 1
        assert "Invalid [lint].level" in result.output
