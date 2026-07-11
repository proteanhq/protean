"""Diagnostics: TestHandlerCompletenessSuppression."""

from protean import Domain, handle
from protean.fields import Identifier
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _codes_for,
)


class TestHandlerCompletenessSuppression:
    """A representative new rule flows through the #774 suppression path."""

    def test_suppress_process_manager_unclosed(self):
        # Positive control: the identical PM without ``suppress_checks`` *is*
        # flagged — so the negative assertion below proves suppression, not a
        # rule that silently stopped firing.
        control = Domain(name="ControlPM", root_path=".")

        @control.aggregate
        class ControlOrder:
            name = String(max_length=50)

        @control.event(part_of=ControlOrder)
        class ControlOrderPlaced:
            order_id = Identifier(identifier=True)

        @control.process_manager(stream_categories=["order"])
        class ControlSaga:
            order_id = Identifier()

            @handle(ControlOrderPlaced, start=True, correlate="order_id")
            def on_placed(self, event):
                self.order_id = event.order_id

        control.init(traverse=False)
        control_ir = IRBuilder(control).build()
        assert "PROCESS_MANAGER_UNCLOSED" in _codes_for(control_ir, "ControlSaga")

        domain = Domain(name="SuppressPM", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id = Identifier(identifier=True)

        @domain.process_manager(
            stream_categories=["order"],
            suppress_checks=["PROCESS_MANAGER_UNCLOSED"],
        )
        class OrderSaga:
            order_id = Identifier()

            @handle(OrderPlaced, start=True, correlate="order_id")
            def on_placed(self, event):
                self.order_id = event.order_id

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Unsuppressed this PM would be flagged (see control); ``suppress_checks``
        # removes it.
        assert "PROCESS_MANAGER_UNCLOSED" not in _codes_for(ir, "OrderSaga")
