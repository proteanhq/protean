"""Diagnostics: TestValueObjectMutableField."""

from protean import Domain
from protean.fields import Dict, List
from protean.fields.simple import Float, String
from protean.ir.builder import IRBuilder
from protean.utils import fqn
from tests.ir.diagnostics._helpers import (
    _codes_for,
)


class TestValueObjectMutableField:
    """VALUE_OBJECT_MUTABLE_FIELD flags a value object with a ``list``/``dict``
    field (mutable state breaks equality-by-value)."""

    def test_list_field_flagged(self):
        domain = Domain(name="VOList", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.value_object(part_of=Order)
        class ShippingLabel:
            carrier = String()
            tags = List()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [
            d for d in ir["diagnostics"] if d["code"] == "VALUE_OBJECT_MUTABLE_FIELD"
        ]
        assert len(diags) == 1
        d = diags[0]
        assert d["element"] == fqn(ShippingLabel)
        assert d["field"] == "tags"
        assert d["level"] == "warning"
        assert d["category"] == "aggregate_design"
        assert d["rule"]["rationale"]
        assert d["rule"]["fix"]
        assert d["suggestion"] == d["rule"]["fix"]

    def test_dict_field_flagged(self):
        domain = Domain(name="VODict", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.value_object(part_of=Order)
        class Metadata:
            label = String()
            attrs = Dict()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [
            d for d in ir["diagnostics"] if d["code"] == "VALUE_OBJECT_MUTABLE_FIELD"
        ]
        assert len(diags) == 1
        assert diags[0]["element"] == fqn(Metadata)
        assert diags[0]["field"] == "attrs"

    def test_scalar_only_vo_not_flagged(self):
        domain = Domain(name="VOScalar", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.value_object(part_of=Order)
        class Money:
            amount = Float()
            currency = String()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "VALUE_OBJECT_MUTABLE_FIELD" not in codes

    def test_abstract_aggregate_vo_not_flagged(self):
        """A mutable-field VO reachable only through an abstract aggregate is
        skipped along with its (non-instantiable) enclosing cluster."""
        domain = Domain(name="VOAbstract", root_path=".")

        @domain.aggregate(abstract=True)
        class BaseOrder:
            total = Float()

        @domain.value_object(part_of=BaseOrder)
        class ShippingLabel:
            carrier = String()
            tags = List()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "VALUE_OBJECT_MUTABLE_FIELD" not in codes

    def test_suppress_checks_drops_code(self):
        domain = Domain(name="VOSuppress", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.value_object(
            part_of=Order, suppress_checks=["VALUE_OBJECT_MUTABLE_FIELD"]
        )
        class ShippingLabel:
            carrier = String()
            tags = List()

        @domain.value_object(part_of=Order)
        class Manifest:
            ref = String()
            items = List()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Suppressed on ShippingLabel, yet the identical shape on Manifest still
        # fires: the rule is active and suppression is selective.
        assert "VALUE_OBJECT_MUTABLE_FIELD" not in _codes_for(ir, "ShippingLabel")
        assert "VALUE_OBJECT_MUTABLE_FIELD" in _codes_for(ir, "Manifest")
