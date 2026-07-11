"""Diagnostics: TestQueryHandlerWithoutQuery."""

from protean import Domain, handle
from protean.fields import Identifier
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from protean.utils.mixins import read
from tests.ir.diagnostics._helpers import (
    _findings,
)


class TestQueryHandlerWithoutQuery:
    """QUERY_HANDLER_WITHOUT_QUERY: a projection wiring a query handler but
    declaring no query has a read path nothing can invoke."""

    def test_query_handler_without_query_flagged(self):
        domain = Domain(name="QHNoQuery", root_path=".")

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        # A query handler needs only a projection (no ``@read`` method is
        # required); with no ``Query`` declared, its read path is unreachable.
        @domain.query_handler(part_of=OrderView)
        class OrderViewQueryHandler:
            pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _findings(ir, "QUERY_HANDLER_WITHOUT_QUERY")
        assert len(findings) > 0
        finding = findings[0]
        assert "OrderView" in finding["element"]
        assert finding["level"] == "warning"

    def test_query_handler_with_query_not_flagged(self):
        domain = Domain(name="QHWithQuery", root_path=".")

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        @domain.query(part_of=OrderView)
        class GetOrder:
            order_id = Identifier(required=True)

        @domain.query_handler(part_of=OrderView)
        class OrderViewQueryHandler:
            @read(GetOrder)
            def by_order(self, query):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "QUERY_HANDLER_WITHOUT_QUERY") == []

    def test_projection_without_query_handler_not_flagged(self):
        domain = Domain(name="QHNeither", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id = Identifier(identifier=True)

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        @domain.projector(projector_for=OrderView, aggregates=[Order])
        class OrderViewProjector:
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "QUERY_HANDLER_WITHOUT_QUERY") == []
