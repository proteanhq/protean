"""Tests for the ``protean check`` CLI command.

Covers exit codes, output formats, error handling, --level filter, and --quiet mode.
"""

import json
import os
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import protean
from protean.cli import app
from protean.cli.check import (
    _element_module_map,
    _escape_annotation,
    _escape_property,
    _format_sarif,
    _resolve_sarif_location,
    _workspace_relative_uri,
)
from protean.utils import fqn

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
    traceback — the chain build used to crash `protean check`."""

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
    the CLI; this pins the end-to-end path."""

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


_CLEAN_DOMAIN = "tests/support/domains/test19/domain19.py:domain"
# Two bare aggregates → a code that repeats across two elements (test38)
_DEDUP_DOMAIN = "tests/support/domains/test38/domain38.py:domain"
# Published event with no external brokers → a warning whose ``element`` is the
# domain name, which does not resolve to a source file (test39)
_DOMAIN_SCOPED_DOMAIN = "tests/support/domains/test39/domain39.py:domain"


class _EmptyRegistryDomain:
    """Minimal stand-in for a domain with no registered elements.

    ``_format_sarif`` only reads ``domain._domain_registry._elements`` (via
    ``_element_module_map``); an empty registry keeps these descriptor-shaping
    unit tests hermetic — no real ``Domain`` is constructed or activated."""

    class _domain_registry:
        _elements: dict = {}


@pytest.mark.no_test_domain
class TestCheckSarifOutput:
    """``--format sarif`` emits a pinned SARIF 2.1.0 document."""

    def test_sarif_well_formed(self):
        """A run with diagnostics produces a valid SARIF 2.1.0 shell with the
        pinned schema, protean driver, and one deduplicated rule per ruleId."""
        result = runner.invoke(app, ["check", "-d", _DIAG_DOMAIN, "-f", "sarif"])
        data = json.loads(result.output)

        assert data["version"] == "2.1.0"
        assert data["$schema"] == (
            "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/"
            "Schemata/sarif-schema-2.1.0.json"
        )
        run = data["runs"][0]
        driver = run["tool"]["driver"]
        assert driver["name"] == "protean"
        assert driver["version"] == protean.__version__
        assert driver["informationUri"] == "https://docs.protean.io/reference/cli/check"

        # Dedup invariant: one reportingDescriptor per unique ruleId.
        rule_ids = {r["ruleId"] for r in run["results"]}
        assert len(rule_ids) > 0, "Expected SARIF results but got none"
        assert len(driver["rules"]) == len(rule_ids)
        descriptor_ids = {r["id"] for r in driver["rules"]}
        for res in run["results"]:
            assert res["ruleId"] in descriptor_ids

    def test_sarif_dedup_collapses_repeated_codes(self):
        """test38's two bare aggregates each emit AGGREGATE_WITHOUT_COMMAND_HANDLER,
        so the code genuinely repeats across results — yet it collapses to a
        single reportingDescriptor whose shortDescription is the first occurrence."""
        result = runner.invoke(app, ["check", "-d", _DEDUP_DOMAIN, "-f", "sarif"])
        run = json.loads(result.output)["runs"][0]

        code = "AGGREGATE_WITHOUT_COMMAND_HANDLER"
        repeated = [r for r in run["results"] if r["ruleId"] == code]
        # The code must actually repeat, or the dedup path is never exercised.
        assert len(repeated) == 2, "Expected the code to repeat across two elements"

        descriptors = [r for r in run["tool"]["driver"]["rules"] if r["id"] == code]
        assert len(descriptors) == 1, "Repeated code must collapse to one descriptor"
        # First occurrence wins: the descriptor keeps the first result's message.
        assert (
            descriptors[0]["shortDescription"]["text"] == repeated[0]["message"]["text"]
        )

        # And no descriptor is duplicated overall.
        descriptor_ids = [r["id"] for r in run["tool"]["driver"]["rules"]]
        assert len(descriptor_ids) == len(set(descriptor_ids))

    def test_sarif_empty_domain(self):
        """A clean domain yields empty results and rules, exit 0."""
        result = runner.invoke(app, ["check", "-d", _CLEAN_DOMAIN, "-f", "sarif"])
        assert result.exit_code == 0
        run = json.loads(result.output)["runs"][0]
        assert run["results"] == []
        assert run["tool"]["driver"]["rules"] == []

    def test_sarif_diagnostics_path_has_metadata_and_safe_location(self):
        """A warning diagnostic surfaces with mapped level, a non-empty
        fullDescription (from #774 rule.rationale), and a location that is either
        a real path or [] — never a KeyError."""
        result = runner.invoke(app, ["check", "-d", _DIAG_DOMAIN, "-f", "sarif"])
        run = json.loads(result.output)["runs"][0]
        warnings = [r for r in run["results"] if r["level"] == "warning"]
        assert len(warnings) > 0, "Expected a warning-level SARIF result"
        for res in warnings:
            locations = res["locations"]
            assert isinstance(locations, list)
            for loc in locations:
                uri = loc["physicalLocation"]["artifactLocation"]["uri"]
                assert isinstance(uri, str) and uri

        descriptors = {r["id"]: r for r in run["tool"]["driver"]["rules"]}
        # At least one warning descriptor carries a rationale from #774.
        rationales = [
            descriptors[r["ruleId"]]["fullDescription"]["text"] for r in warnings
        ]
        assert any(text for text in rationales), (
            "Expected a non-empty fullDescription from #774 rule.rationale"
        )

    def test_sarif_resolvable_element_yields_physical_location(self):
        """test28's DEPRECATED_ELEMENT points at the registered ``Order``
        aggregate, whose FQN resolves to a real source file."""
        result = runner.invoke(app, ["check", "-d", _DEPRECATED_DOMAIN, "-f", "sarif"])
        run = json.loads(result.output)["runs"][0]
        deprecated = [r for r in run["results"] if r["ruleId"] == "DEPRECATED_ELEMENT"]
        assert len(deprecated) == 1
        loc = deprecated[0]["locations"]
        assert len(loc) == 1
        uri = loc[0]["physicalLocation"]["artifactLocation"]["uri"]
        assert uri.endswith("domain28.py")
        # GitHub Code Scanning resolves the uri against the workspace root, so it
        # must be workspace-relative, not an absolute filesystem path.
        assert not os.path.isabs(uri)
        assert not uri.startswith("/")

    def test_sarif_validator_errors_path(self):
        """A validator-error run (test30) emits error results with no location
        and no physicalLocation, and does not raise on missing rule metadata."""
        result = runner.invoke(
            app, ["check", "-d", _UPCASTER_ERR_DOMAIN, "-f", "sarif"]
        )
        assert result.exit_code == 1
        run = json.loads(result.output)["runs"][0]
        assert len(run["results"]) > 0, "Expected error results"
        for res in run["results"]:
            assert res["level"] == "error"
            assert res["locations"] == []
        # Descriptors for validator errors carry no #774 metadata.
        for descriptor in run["tool"]["driver"]["rules"]:
            assert descriptor["fullDescription"]["text"] == ""
            assert descriptor["help"]["text"] == ""

    def test_sarif_level_mapping_info_becomes_note(self):
        """An info diagnostic maps to SARIF ``note`` (never ``info``)."""
        result = runner.invoke(app, ["check", "-d", _INFO_DOMAIN, "-f", "sarif"])
        run = json.loads(result.output)["runs"][0]
        levels = {r["level"] for r in run["results"]}
        assert len(run["results"]) > 0, "Expected info-level results"
        assert "note" in levels
        assert "info" not in levels

    def test_sarif_exit_code_matches_rich(self):
        """The new format does not alter the exit-code block: a warning domain
        exits 2 under both rich and sarif — and the output really is SARIF (an
        unimplemented format would degrade to rich and pass this vacuously)."""
        rich = runner.invoke(app, ["check", "-d", _DIAG_DOMAIN])
        sarif = runner.invoke(app, ["check", "-d", _DIAG_DOMAIN, "-f", "sarif"])
        assert sarif.exit_code == rich.exit_code == 2
        # Assert the SARIF branch actually ran, not the rich fallback.
        assert json.loads(sarif.output)["version"] == "2.1.0"

    def test_sarif_ignores_level_filter(self):
        """SARIF is machine-consumed (Code Scanning upload); a display --level
        must not strip findings. test25 warnings/info survive --level error."""
        unfiltered = runner.invoke(app, ["check", "-d", _DIAG_DOMAIN, "-f", "sarif"])
        filtered = runner.invoke(
            app, ["check", "-d", _DIAG_DOMAIN, "-f", "sarif", "--level", "error"]
        )
        unfiltered_ids = {
            r["ruleId"] for r in json.loads(unfiltered.output)["runs"][0]["results"]
        }
        filtered_ids = {
            r["ruleId"] for r in json.loads(filtered.output)["runs"][0]["results"]
        }
        assert len(unfiltered_ids) > 0, "Expected findings to survive the filter"
        assert filtered_ids == unfiltered_ids

    def test_sarif_domain_scoped_diagnostic_has_no_location(self):
        """A diagnostic whose element is the domain name (not a class FQN) does
        not resolve to a file, so its result carries an empty locations list."""
        result = runner.invoke(
            app, ["check", "-d", _DOMAIN_SCOPED_DOMAIN, "-f", "sarif"]
        )
        run = json.loads(result.output)["runs"][0]
        scoped = [
            r for r in run["results"] if r["ruleId"] == "PUBLISHED_NO_EXTERNAL_BROKER"
        ]
        assert len(scoped) == 1, "Expected the domain-scoped diagnostic"
        assert scoped[0]["locations"] == []

    def test_sarif_help_text_merges_suggestion_distinct_from_fix(self):
        """When a diagnostic's suggestion differs from its rule.fix, the
        descriptor help text carries both (fixture diagnostics always have
        suggestion == fix, so this is asserted on a synthetic result)."""
        derived = _EmptyRegistryDomain()
        result = {
            "errors": [],
            "diagnostics": [
                {
                    "code": "X_RULE",
                    "element": "not.registered.Elem",
                    "level": "warning",
                    "message": "something is off",
                    "rule": {"rationale": "why", "fix": "do the fix"},
                    "suggestion": "a different suggestion",
                }
            ],
        }
        sarif = _format_sarif(result, derived)
        descriptor = sarif["runs"][0]["tool"]["driver"]["rules"][0]
        assert descriptor["help"]["text"] == "do the fix\na different suggestion"

    def test_sarif_help_text_no_duplication_when_suggestion_equals_fix(self):
        """When suggestion == fix (the common case) the help text is just the fix,
        with no duplicated line."""
        derived = _EmptyRegistryDomain()
        result = {
            "errors": [],
            "diagnostics": [
                {
                    "code": "X_RULE",
                    "element": "not.registered.Elem",
                    "level": "warning",
                    "message": "something is off",
                    "rule": {"rationale": "why", "fix": "do the fix"},
                    "suggestion": "do the fix",
                }
            ],
        }
        sarif = _format_sarif(result, derived)
        descriptor = sarif["runs"][0]["tool"]["driver"]["rules"][0]
        assert descriptor["help"]["text"] == "do the fix"

    def test_resolve_location_unknown_fqn_returns_none(self):
        """An FQN absent from the module map (validator errors, domain-scoped
        diagnostics) resolves to None, never raising."""
        assert _resolve_sarif_location("no.Such.Element", {}) is None

    def test_resolve_location_unresolvable_module_returns_none(self):
        """A mapped module that find_spec cannot locate degrades to None."""
        assert _resolve_sarif_location("x.Y", {"x.Y": "no_such_module_zzz"}) is None

    def test_resolve_location_find_spec_error_returns_none(self):
        """A module name whose parent package cannot be imported makes find_spec
        raise (ModuleNotFoundError); the failure degrades to None, never raises."""
        assert (
            _resolve_sarif_location("x.Y", {"x.Y": "no_such_parent_zzz.child"}) is None
        )

    def test_resolve_location_spec_without_origin_returns_none(self, monkeypatch):
        """A module whose spec has no origin (e.g. a namespace package) resolves
        to None rather than emitting a location with a null uri."""
        import importlib.util

        monkeypatch.setattr(
            importlib.util, "find_spec", lambda _m: SimpleNamespace(origin=None)
        )
        assert _resolve_sarif_location("x.Y", {"x.Y": "some_module"}) is None

    def test_element_module_map_skips_internal_elements(self):
        """Internal (platform-generated) elements are excluded from the module
        map, so they never surface a SARIF location."""

        class _Public:
            pass

        class _Internal:
            pass

        domain = SimpleNamespace(
            _domain_registry=SimpleNamespace(
                _elements={
                    "AGGREGATE": {
                        "pub": SimpleNamespace(cls=_Public, internal=False),
                        "int": SimpleNamespace(cls=_Internal, internal=True),
                    }
                }
            )
        )
        module_map = _element_module_map(domain)
        assert fqn(_Public) in module_map
        assert fqn(_Internal) not in module_map

    def test_workspace_relative_uri_resolves_against_github_workspace(
        self, monkeypatch
    ):
        """When GITHUB_WORKSPACE is set, the emitted path is relative to it — not
        the process's current directory — so a step that ``cd``s into a
        subdirectory still maps onto the checked-out repo."""
        monkeypatch.setenv("GITHUB_WORKSPACE", "/workspace/repo")
        assert (
            _workspace_relative_uri("/workspace/repo/src/protean/foo.py")
            == "src/protean/foo.py"
        )

    def test_workspace_relative_uri_falls_back_to_absolute_on_valueerror(
        self, monkeypatch
    ):
        """When a relative path is impossible (e.g. a different drive on Windows,
        which raises ValueError), the absolute origin is returned unchanged."""
        monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)

        def _raise(*_a, **_k):
            raise ValueError("path on mount 'C:' can't be relative to 'D:'")

        monkeypatch.setattr(os.path, "relpath", _raise)
        assert _workspace_relative_uri("/abs/origin.py") == "/abs/origin.py"


@pytest.mark.no_test_domain
class TestCheckGithubAnnotations:
    """``--format github-annotations`` emits workflow-command lines."""

    def test_annotation_levels(self):
        """Warnings map to ::warning, info to ::notice."""
        result = runner.invoke(
            app, ["check", "-d", _DIAG_DOMAIN, "-f", "github-annotations"]
        )
        lines = [ln for ln in result.output.splitlines() if ln]
        assert len(lines) > 0, "Expected annotation lines"
        assert any(ln.startswith("::warning") for ln in lines)
        assert any(ln.startswith("::notice") for ln in lines)
        for ln in lines:
            assert ln.startswith(("::warning", "::notice", "::error"))

    def test_annotation_error_level(self):
        """Validator errors map to ::error with no file= parameter."""
        result = runner.invoke(
            app, ["check", "-d", _UPCASTER_ERR_DOMAIN, "-f", "github-annotations"]
        )
        lines = [ln for ln in result.output.splitlines() if ln]
        assert len(lines) > 0, "Expected annotation lines"
        for ln in lines:
            assert ln.startswith("::error")
            # The command head (between the two ``::``) carries no file= param.
            assert ln.split("::", 2)[1] == "error"

    def test_annotation_resolvable_element_includes_file(self):
        """A diagnostic on a registered element carries file= before the second
        ``::`` separator."""
        result = runner.invoke(
            app, ["check", "-d", _DEPRECATED_DOMAIN, "-f", "github-annotations"]
        )
        lines = [ln for ln in result.output.splitlines() if ln]
        deprecated = [ln for ln in lines if "DEPRECATED_ELEMENT" in ln]
        assert len(deprecated) == 1
        head = deprecated[0].split("::", 2)[1]
        assert " file=" in head
        assert head.startswith("notice")

    def test_annotation_empty_domain(self):
        """A clean domain produces no annotation lines, exit 0."""
        result = runner.invoke(
            app, ["check", "-d", _CLEAN_DOMAIN, "-f", "github-annotations"]
        )
        assert result.exit_code == 0
        assert result.output.strip() == ""

    def test_annotation_exit_code_matches_rich(self):
        """The new format shares the exit-code block with rich, and the output
        really is annotation lines (an unimplemented format would degrade to rich
        and pass this vacuously)."""
        rich = runner.invoke(app, ["check", "-d", _DIAG_DOMAIN])
        gha = runner.invoke(
            app, ["check", "-d", _DIAG_DOMAIN, "-f", "github-annotations"]
        )
        assert gha.exit_code == rich.exit_code == 2
        lines = [ln for ln in gha.output.splitlines() if ln]
        assert lines and all(ln.startswith("::") for ln in lines)

    def test_annotation_ignores_level_filter(self):
        """--level must not strip machine-consumed annotation lines."""
        unfiltered = runner.invoke(
            app, ["check", "-d", _DIAG_DOMAIN, "-f", "github-annotations"]
        )
        filtered = runner.invoke(
            app,
            [
                "check",
                "-d",
                _DIAG_DOMAIN,
                "-f",
                "github-annotations",
                "--level",
                "error",
            ],
        )
        unfiltered_lines = [ln for ln in unfiltered.output.splitlines() if ln]
        filtered_lines = [ln for ln in filtered.output.splitlines() if ln]
        assert len(unfiltered_lines) > 0
        assert filtered_lines == unfiltered_lines

    def test_annotation_domain_scoped_diagnostic_has_no_file(self):
        """A diagnostic whose element does not resolve emits no file= parameter."""
        result = runner.invoke(
            app, ["check", "-d", _DOMAIN_SCOPED_DOMAIN, "-f", "github-annotations"]
        )
        lines = [ln for ln in result.output.splitlines() if ln]
        scoped = [ln for ln in lines if "PUBLISHED_NO_EXTERNAL_BROKER" in ln]
        assert len(scoped) == 1
        head = scoped[0].split("::", 2)[1]
        assert " file=" not in head
        assert head == "warning"

    def test_annotation_resolvable_element_uses_relative_file(self):
        """The file= path is workspace-relative, not absolute, so GitHub can map
        it to the PR diff."""
        result = runner.invoke(
            app, ["check", "-d", _DEPRECATED_DOMAIN, "-f", "github-annotations"]
        )
        line = next(
            ln for ln in result.output.splitlines() if "DEPRECATED_ELEMENT" in ln
        )
        head = line.split("::", 2)[1]
        path = head.split(" file=", 1)[1]
        assert not os.path.isabs(path)
        assert not path.startswith("/")


class TestEscapeAnnotation:
    """``_escape_annotation`` escapes %, CR, LF in the order that avoids
    double-escaping. Fixtures cannot easily carry these bytes in a diagnostic
    message, so the escaping branch is unit-tested directly."""

    def test_percent_escaped(self):
        assert _escape_annotation("100%") == "100%25"

    def test_carriage_return_escaped(self):
        assert _escape_annotation("a\rb") == "a%0Db"

    def test_newline_escaped(self):
        assert _escape_annotation("a\nb") == "a%0Ab"

    def test_all_three(self):
        assert _escape_annotation("a%\r\nb") == "a%25%0D%0Ab"

    def test_percent_escaped_before_newline(self):
        """A literal ``%0A`` in the input must not be double-escaped: because
        ``%`` is replaced first, the input's ``%`` becomes ``%25`` and the
        digits are untouched — the result is ``%250A``, not ``%25%0A``."""
        assert _escape_annotation("%0A") == "%250A"
        # The wrong order (\n first) would turn a real newline into %0A and then
        # re-escape its % to %250A; assert a real newline is NOT double-escaped.
        assert _escape_annotation("\n") == "%0A"


class TestEscapeProperty:
    """``_escape_property`` escapes a ``file=`` value with the two extra
    delimiters (``:`` and ``,``) that would otherwise corrupt the annotation."""

    def test_comma_escaped(self):
        assert _escape_property("a,b") == "a%2Cb"

    def test_colon_escaped(self):
        assert _escape_property("C:/x") == "C%3A/x"

    def test_inherits_message_escapes(self):
        # % / CR / LF still escaped, and % first (no double-escaping).
        assert _escape_property("a%\r\nb") == "a%25%0D%0Ab"

    def test_windows_path_and_comma_together(self):
        assert (
            _escape_property("C:\\proj\\a,b\\model.py") == "C%3A\\proj\\a%2Cb\\model.py"
        )
