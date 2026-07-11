"""Diagnostics: TestAggregateNoInvariants."""

from protean import Domain
from protean.core.entity import invariant
from protean.exceptions import ValidationError
from protean.fields.simple import Float
from protean.ir.builder import IRBuilder
from protean.utils import fqn
from tests.ir.diagnostics._helpers import (
    _codes_for,
)


class TestAggregateNoInvariants:
    """AGGREGATE_NO_INVARIANTS is an INFO-level nudge for an aggregate with no
    pre/post invariants; abstract aggregates are skipped."""

    def test_aggregate_without_invariants_flagged(self):
        domain = Domain(name="NoInvariants", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [d for d in ir["diagnostics"] if d["code"] == "AGGREGATE_NO_INVARIANTS"]
        assert len(diags) == 1
        d = diags[0]
        assert d["element"] == fqn(Order)
        assert d["level"] == "info"
        assert d["category"] == "aggregate_design"
        assert d["rule"]["rationale"]
        assert d["rule"]["fix"]
        assert d["suggestion"] == d["rule"]["fix"]

    def test_post_invariant_not_flagged(self):
        domain = Domain(name="PostInvariant", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

            @invariant.post
            def total_is_non_negative(self):
                if self.total is not None and self.total < 0:
                    raise ValidationError({"total": ["must be non-negative"]})

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "AGGREGATE_NO_INVARIANTS" not in codes

    def test_pre_invariant_not_flagged(self):
        domain = Domain(name="PreInvariant", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

            @invariant.pre
            def total_present(self):
                if self.total is None:
                    raise ValidationError({"total": ["is required"]})

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "AGGREGATE_NO_INVARIANTS" not in codes

    def test_abstract_aggregate_not_flagged(self):
        """``abstract`` is sourced from ``meta_`` via the registry; an abstract
        aggregate with no invariants is skipped before the invariants check."""
        domain = Domain(name="AbstractAgg", root_path=".")

        @domain.aggregate(abstract=True)
        class BaseThing:
            total = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "AGGREGATE_NO_INVARIANTS" not in codes

    def test_suppress_checks_drops_code(self):
        domain = Domain(name="NoInvariantsSuppress", root_path=".")

        @domain.aggregate(suppress_checks=["AGGREGATE_NO_INVARIANTS"])
        class Order:
            total = Float()

        @domain.aggregate
        class Shipment:
            weight = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Suppressed on Order, yet the identical shape on Shipment still fires.
        assert "AGGREGATE_NO_INVARIANTS" not in _codes_for(ir, "Order")
        assert "AGGREGATE_NO_INVARIANTS" in _codes_for(ir, "Shipment")
