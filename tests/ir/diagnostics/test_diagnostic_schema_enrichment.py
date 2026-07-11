"""Diagnostics: TestDiagnosticSchemaEnrichment."""

import pytest

from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _BUILTIN_CODES,
    _all_builtin_diagnostics,
    build_all_categories_domain,
)


class TestDiagnosticSchemaEnrichment:
    """Every built-in diagnostic carries category, rule, and suggestion."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.domain = build_all_categories_domain()
        self.ir = IRBuilder(self.domain).build()
        self.diagnostics = self.ir["diagnostics"]

    def test_every_builtin_emit_site_carries_enriched_keys(self):
        """Assert across *all* built-in codes — not just the five
        ``build_all_categories_domain`` produces. A missing/typo ``rule``/
        ``suggestion`` key at any of the 19 emit sites fails here."""
        diagnostics = _all_builtin_diagnostics()
        observed = {d["code"] for d in diagnostics}
        assert observed >= _BUILTIN_CODES, (
            f"emit sites not exercised: {sorted(_BUILTIN_CODES - observed)}"
        )
        for d in diagnostics:
            if d["code"] not in _BUILTIN_CODES:
                continue  # custom/foreign findings are not schema-enriched
            rule = d.get("rule")
            assert d.get("category"), f"{d['code']} missing category"
            assert isinstance(rule, dict), f"{d['code']} missing rule dict"
            assert rule.get("rationale"), f"{d['code']} rule missing rationale"
            assert rule.get("fix"), f"{d['code']} rule missing fix"
            assert d.get("suggestion") == rule["fix"], f"{d['code']} suggestion drift"

    def test_every_diagnostic_carries_the_enriched_keys(self):
        assert len(self.diagnostics) > 0, "Expected diagnostics but got none"
        for d in self.diagnostics:
            assert d.get("category"), f"{d['code']} missing category"
            rule = d.get("rule")
            assert isinstance(rule, dict), f"{d['code']} missing rule dict"
            assert rule.get("rationale"), f"{d['code']} rule missing rationale"
            assert rule.get("fix"), f"{d['code']} rule missing fix"
            assert d.get("suggestion"), f"{d['code']} missing suggestion"

    def test_suggestion_defaults_to_rule_fix(self):
        # The separate ``suggestion`` key is the forward-compat AI-override
        # hook; for shipped rules it equals ``rule["fix"]`` (no override yet).
        assert len(self.diagnostics) > 0
        for d in self.diagnostics:
            assert d["suggestion"] == d["rule"]["fix"]

    def test_code_to_category_mapping(self):
        by_code = {d["code"]: d["category"] for d in self.diagnostics}
        assert by_code["AGGREGATE_WITHOUT_COMMAND_HANDLER"] == "handler_completeness"
        assert by_code["EVENT_WITHOUT_DATA"] == "aggregate_design"
        assert by_code["UPCASTER_GAP"] == "versioning"
        assert by_code["DEPRECATED_ELEMENT"] == "deprecation"

    def test_all_four_categories_present(self):
        categories = {d["category"] for d in self.diagnostics}
        assert {
            "handler_completeness",
            "aggregate_design",
            "versioning",
            "deprecation",
        } <= categories
