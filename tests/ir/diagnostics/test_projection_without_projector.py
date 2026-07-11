"""Diagnostics: TestProjectionWithoutProjector."""

from protean import Domain, handle
from protean.fields import Identifier
from protean.fields.simple import String
from protean.ir.builder import IRBuilder


class TestProjectionWithoutProjector:
    """Detect projections with no projector to populate them."""

    def test_projection_without_projector_detected(self):
        domain = Domain(name="NoProjTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)
            name = String(max_length=100)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "PROJECTION_WITHOUT_PROJECTOR" in codes

    def test_projection_without_projector_format(self):
        domain = Domain(name="NoProjFmt", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.projection
        class OrderSummary:
            order_id = Identifier(identifier=True)
            name = String(max_length=100)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diag = next(
            d for d in ir["diagnostics"] if d["code"] == "PROJECTION_WITHOUT_PROJECTOR"
        )
        assert diag["level"] == "warning"
        assert "OrderSummary" in diag["message"]
        assert "no projector" in diag["message"]
        assert "OrderSummary" in diag["element"]

    def test_no_warning_when_projector_exists(self):
        domain = Domain(name="WithProjTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.event(part_of=Order)
        class OrderPlaced:
            name = String(required=True)

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)
            name = String(max_length=100)

        @domain.projector(projector_for=OrderView, aggregates=[Order])
        class OrderProjector:
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "PROJECTION_WITHOUT_PROJECTOR" not in codes

    def test_no_warning_when_externally_populated(self):
        """A projection marked externally_populated (subscriber/handler-written,
        the ACL pattern) must not be flagged even with no co-located projector."""
        domain = Domain(name="AclProjTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.projection(externally_populated=True)
        class VerifiedPurchases:
            order_id = Identifier(identifier=True)
            name = String(max_length=100)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        proj_warnings = [
            d
            for d in ir["diagnostics"]
            if d["code"] == "PROJECTION_WITHOUT_PROJECTOR"
            and "VerifiedPurchases" in d["element"]
        ]
        assert proj_warnings == []

    def test_externally_populated_false_still_warns(self):
        """The opt-out is explicit: a plain projection with no projector still
        warns (guards against the flag defaulting on)."""
        domain = Domain(name="PlainProjTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.projection
        class PlainView:
            order_id = Identifier(identifier=True)
            name = String(max_length=100)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        proj_warnings = [
            d
            for d in ir["diagnostics"]
            if d["code"] == "PROJECTION_WITHOUT_PROJECTOR"
            and "PlainView" in d["element"]
        ]
        assert len(proj_warnings) == 1
