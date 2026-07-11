"""Diagnostics: TestSuppressionAllowList."""

from protean import Domain
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _FIXTURES,
    _build_five_finding_domain,
)


class TestSuppressionAllowList:
    """``[lint].suppressions`` grandfathers the first N findings per code."""

    def _handler_gap_elements(self, ir: dict) -> list[str]:
        return sorted(
            d["element"]
            for d in ir["diagnostics"]
            if d["code"] == "AGGREGATE_WITHOUT_COMMAND_HANDLER"
        )

    def test_count_grandfathers_first_n(self):
        domain = _build_five_finding_domain({"AGGREGATE_WITHOUT_COMMAND_HANDLER": 2})
        ir = IRBuilder(domain).build()
        survivors = self._handler_gap_elements(ir)
        assert len(survivors) == 3

    def test_survivors_are_the_deterministic_tail(self):
        """The survivors are exactly those ranked *after* position N in the
        (code, element, field, message) total order — not merely count − N."""
        domain = _build_five_finding_domain({"AGGREGATE_WITHOUT_COMMAND_HANDLER": 2})
        ir = IRBuilder(domain).build()

        all_elements = sorted(
            fqn
            for fqn in {
                d["element"]
                for d in IRBuilder(_build_five_finding_domain()).build()["diagnostics"]
                if d["code"] == "AGGREGATE_WITHOUT_COMMAND_HANDLER"
            }
        )
        assert len(all_elements) == 5
        expected_survivors = all_elements[2:]  # first 2 grandfathered away
        assert self._handler_gap_elements(ir) == expected_survivors

    def test_build_is_deterministic(self):
        domain = _build_five_finding_domain({"AGGREGATE_WITHOUT_COMMAND_HANDLER": 2})
        first = IRBuilder(domain).build()["diagnostics"]
        second = IRBuilder(domain).build()["diagnostics"]
        assert first == second

    def test_absent_suppressions_keeps_all(self):
        domain = _build_five_finding_domain()
        ir = IRBuilder(domain).build()
        assert len(self._handler_gap_elements(ir)) == 5

    def test_zero_count_suppresses_nothing(self):
        domain = _build_five_finding_domain({"AGGREGATE_WITHOUT_COMMAND_HANDLER": 0})
        ir = IRBuilder(domain).build()
        assert len(self._handler_gap_elements(ir)) == 5

    def test_custom_rule_findings_are_subject_to_allow_list(self):
        """Custom findings with only the minimal keys are still allow-listed
        and default to category='custom' — no KeyError on the absent keys."""
        domain = Domain(name="CustomAllowList", root_path=".")
        domain.config["lint"] = {
            "rules": [f"{_FIXTURES}.repeated_code_rule"],
            "suppressions": {"REPEATED": 1},
        }

        @domain.aggregate
        class Widget:
            label = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        repeated = [d for d in ir["diagnostics"] if d["code"] == "REPEATED"]
        assert len(repeated) == 2  # 3 emitted, first 1 grandfathered
        assert all(d["category"] == "custom" for d in repeated)

    def test_grandfathered_set_follows_sort_not_emission_order(self):
        """The load-bearing ``survivors.sort(...)``: findings emitted OUT of
        sort order (z, a, q, b, k) must be grandfathered by *sorted* order, so
        the first two removed are ``a``/``b`` — not the first two *emitted*
        (``z``/``a``). Replacing the sort with a no-op would fail this."""
        domain = Domain(name="ScrambledAllowList", root_path=".")
        domain.config["lint"] = {
            "rules": [f"{_FIXTURES}.scrambled_code_rule"],
            "suppressions": {"SCRAMBLED": 2},
        }

        @domain.aggregate
        class Widget:
            label = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        survivors = sorted(
            d["element"] for d in ir["diagnostics"] if d["code"] == "SCRAMBLED"
        )
        # sorted(z,a,q,b,k) = a,b,k,q,z; first two (a,b) grandfathered away.
        assert survivors == ["test.k", "test.q", "test.z"]
