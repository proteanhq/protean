"""Diagnostics: TestCustomLintRules."""

import logging

import pytest

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

    @pytest.mark.parametrize(
        ("rule", "code"),
        [
            ("empty_rule", "CUSTOM_CHECK"),
            ("missing_keys_rule", "PARTIAL"),
            ("bad_level_rule", "BAD_LEVEL"),
            ("error_level_rule", "CUSTOM_ERROR"),
        ],
        ids=[
            "rule-returns-nothing",
            "finding-missing-required-keys",
            "finding-with-unknown-level",
            "finding-with-error-level",
        ],
    )
    def test_rule_adds_no_invalid_finding(self, rule, code):
        """An empty rule adds nothing, and a finding that lacks required keys or
        uses a level other than ``info`` or ``warning`` is dropped. Custom rules
        cannot use ``error``, which is reserved for the domain validator."""
        domain = _build_domain_with_rules([f"{_FIXTURES}.{rule}"])
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert code not in codes

    @pytest.mark.parametrize(
        "rule_path",
        [
            f"{_FIXTURES}.bad_return_type",
            f"{_FIXTURES}.non_dict_item_rule",
            "norule",
        ],
        ids=["returns-a-string", "returns-a-non-dict-item", "path-without-a-module"],
    )
    def test_unusable_rule_does_not_break_the_build(self, rule_path):
        """A rule that returns something other than a list of dicts, or a rule
        path with no module part, is skipped and the build still returns its
        diagnostics list."""
        domain = _build_domain_with_rules([rule_path])
        ir = IRBuilder(domain).build()
        assert isinstance(ir["diagnostics"], list)

    def test_raising_rule_is_skipped(self, caplog):
        """A rule that throws an exception is logged and skipped."""
        domain = _build_domain_with_rules([f"{_FIXTURES}.raising_rule"])
        with caplog.at_level(logging.WARNING, logger="protean.ir.builder"):
            ir = IRBuilder(domain).build()

        assert any(
            "raising_rule" in r.getMessage()
            and "Something went wrong in the rule" in r.getMessage()
            for r in caplog.records
        )

        # The build does not crash and still returns its diagnostics.
        assert isinstance(ir["diagnostics"], list)

    def test_import_failure_skipped(self, caplog):
        """A non-existent rule path is logged and skipped."""
        domain = _build_domain_with_rules(["nonexistent.module.rule"])
        with caplog.at_level(logging.WARNING, logger="protean.ir.builder"):
            ir = IRBuilder(domain).build()

        assert any(
            "nonexistent.module.rule" in r.getMessage()
            and "could not be imported" in r.getMessage()
            and "ModuleNotFoundError" in r.getMessage()
            for r in caplog.records
        )
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
