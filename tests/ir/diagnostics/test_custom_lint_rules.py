"""Diagnostics: TestCustomLintRules."""

from protean import Domain
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _FIXTURES,
    _build_domain_with_rules,
)


class TestCustomLintRules:
    """Custom lint rules loaded from [lint] rules config."""

    def test_good_rule_appends_diagnostics(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.good_rule"])
        ir = IRBuilder(domain).build()

        custom = [d for d in ir["diagnostics"] if d["code"] == "CUSTOM_CHECK"]
        assert len(custom) == 1
        assert custom[0]["level"] == "info"
        assert custom[0]["element"] == "test.element"

    def test_multi_result_rule(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.multi_result_rule"])
        ir = IRBuilder(domain).build()

        custom_a = [d for d in ir["diagnostics"] if d["code"] == "CUSTOM_A"]
        custom_b = [d for d in ir["diagnostics"] if d["code"] == "CUSTOM_B"]
        assert len(custom_a) == 1
        assert custom_a[0]["level"] == "warning"
        assert len(custom_b) == 1
        assert custom_b[0]["level"] == "info"

    def test_empty_rule_adds_nothing(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.empty_rule"])
        ir = IRBuilder(domain).build()

        # Only built-in diagnostics should be present
        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CUSTOM_CHECK" not in codes

    def test_raising_rule_is_skipped(self):
        """A rule that throws an exception is logged and skipped."""
        domain = _build_domain_with_rules([f"{_FIXTURES}.raising_rule"])
        ir = IRBuilder(domain).build()

        # Should not crash — built-in diagnostics still present
        assert isinstance(ir["diagnostics"], list)

    def test_bad_return_type_is_skipped(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.bad_return_type"])
        ir = IRBuilder(domain).build()
        assert isinstance(ir["diagnostics"], list)

    def test_missing_keys_skipped(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.missing_keys_rule"])
        ir = IRBuilder(domain).build()

        # The invalid item should not appear
        codes = [d["code"] for d in ir["diagnostics"]]
        assert "PARTIAL" not in codes

    def test_bad_level_skipped(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.bad_level_rule"])
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "BAD_LEVEL" not in codes

    def test_error_level_rejected_for_custom_rules(self):
        """Custom rules cannot use 'error' level — errors are DomainValidator's domain."""
        domain = _build_domain_with_rules([f"{_FIXTURES}.error_level_rule"])
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CUSTOM_ERROR" not in codes

    def test_non_dict_item_skipped(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.non_dict_item_rule"])
        ir = IRBuilder(domain).build()
        assert isinstance(ir["diagnostics"], list)

    def test_import_failure_skipped(self):
        """A non-existent rule path is logged and skipped."""
        domain = _build_domain_with_rules(["nonexistent.module.rule"])
        ir = IRBuilder(domain).build()
        assert isinstance(ir["diagnostics"], list)

    def test_invalid_dotted_path_skipped(self):
        """A rule path without dots (no module) is logged and skipped."""
        domain = _build_domain_with_rules(["norule"])
        ir = IRBuilder(domain).build()
        assert isinstance(ir["diagnostics"], list)

    def test_no_rules_configured(self):
        """No [lint] rules config means no custom rules run."""
        domain = Domain(name="NoRulesTest", root_path=".")

        @domain.aggregate
        class Item:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Should have only built-in diagnostics
        assert isinstance(ir["diagnostics"], list)

    def test_multiple_rules_all_run(self):
        domain = _build_domain_with_rules(
            [
                f"{_FIXTURES}.good_rule",
                f"{_FIXTURES}.multi_result_rule",
            ]
        )
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CUSTOM_CHECK" in codes
        assert "CUSTOM_A" in codes
        assert "CUSTOM_B" in codes
