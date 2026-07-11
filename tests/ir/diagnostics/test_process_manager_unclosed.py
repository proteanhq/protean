"""Diagnostics: TestProcessManagerUnclosed."""

from protean import Domain, handle
from protean.fields import Identifier
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _findings,
)


class TestProcessManagerUnclosed:
    """PROCESS_MANAGER_UNCLOSED: a process manager with no ``end=True`` handler
    never signals completion, so its instances accumulate."""

    def test_unclosed_pm_flagged(self):
        domain = Domain(name="UnclosedPM", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id = Identifier(identifier=True)

        @domain.process_manager(stream_categories=["order"])
        class OrderSaga:
            order_id = Identifier()

            @handle(OrderPlaced, start=True, correlate="order_id")
            def on_placed(self, event):
                self.order_id = event.order_id

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _findings(ir, "PROCESS_MANAGER_UNCLOSED")
        assert len(findings) > 0
        finding = findings[0]
        assert "OrderSaga" in finding["element"]
        assert finding["level"] == "info"

    def test_closed_pm_not_flagged(self):
        domain = Domain(name="ClosedPM", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id = Identifier(identifier=True)

        @domain.event(part_of=Order)
        class OrderCompleted:
            order_id = Identifier(identifier=True)

        @domain.process_manager(stream_categories=["order"])
        class OrderSaga:
            order_id = Identifier()

            @handle(OrderPlaced, start=True, correlate="order_id")
            def on_placed(self, event):
                self.order_id = event.order_id

            @handle(OrderCompleted, correlate="order_id", end=True)
            def on_completed(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "PROCESS_MANAGER_UNCLOSED") == []

    def test_handlerless_pm_not_flagged(self):
        """A process manager with no handlers has no flow to close — it is not
        reported ``PROCESS_MANAGER_UNCLOSED`` (which would carry a misleading
        "no ``end=True`` handler" message). Only a PM that *has* handlers, none
        terminating, is flagged."""
        domain = Domain(name="HandlerlessPM", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id = Identifier(identifier=True)

        @domain.process_manager(stream_categories=["order"])
        class OrderSaga:
            order_id = Identifier()

            @handle(OrderPlaced, start=True, correlate="order_id")
            def on_placed(self, event):
                self.order_id = event.order_id

        domain.init(traverse=False)

        # A handler-less PM only appears in materialized IR (a live PM keeps its
        # registered handlers) — drop the handler map to exercise that state.
        OrderSaga._handlers = {}
        ir = IRBuilder(domain).build()

        assert _findings(ir, "PROCESS_MANAGER_UNCLOSED") == []
