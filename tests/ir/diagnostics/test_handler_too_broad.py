"""Diagnostics: TestHandlerTooBroad."""

from protean import Domain, handle
from protean.fields.simple import String
from protean.ir.builder import IRBuilder


class TestHandlerTooBroad:
    """Detect handlers handling too many message types."""

    def test_broad_command_handler_detected(self):
        domain = Domain(name="BroadHandlerTest", root_path=".")
        domain.config["lint"] = {"handler_breadth_limit": 2}

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.command(part_of=Order)
        class CreateOrder:
            name = String(required=True)

        @domain.command(part_of=Order)
        class UpdateOrder:
            name = String(required=True)

        @domain.command(part_of=Order)
        class CancelOrder:
            name = String(required=True)

        @domain.command_handler(part_of=Order)
        class OrderHandler:
            @handle(CreateOrder)
            def create(self, command):
                pass

            @handle(UpdateOrder)
            def update(self, command):
                pass

            @handle(CancelOrder)
            def cancel(self, command):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [d for d in ir["diagnostics"] if d["code"] == "HANDLER_TOO_BROAD"]
        assert len(diags) == 1
        assert diags[0]["level"] == "info"
        assert "OrderHandler" in diags[0]["message"]
        assert "3 message types" in diags[0]["message"]

    def test_broad_event_handler_detected(self):
        """Event handler handling too many event types is flagged."""
        domain = Domain(name="BroadEventHandlerTest", root_path=".")
        domain.config["lint"] = {"handler_breadth_limit": 2}

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.event(part_of=Order)
        class OrderCreated:
            name = String(required=True)

        @domain.event(part_of=Order)
        class OrderUpdated:
            name = String(required=True)

        @domain.event(part_of=Order)
        class OrderCancelled:
            name = String(required=True)

        @domain.event_handler(part_of=Order)
        class OrderEventHandler:
            @handle(OrderCreated)
            def on_created(self, event):
                pass

            @handle(OrderUpdated)
            def on_updated(self, event):
                pass

            @handle(OrderCancelled)
            def on_cancelled(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [d for d in ir["diagnostics"] if d["code"] == "HANDLER_TOO_BROAD"]
        assert any("OrderEventHandler" in d["message"] for d in diags)
        assert all(d["level"] == "info" for d in diags)

    def test_no_warning_when_under_limit(self):
        domain = Domain(name="NarrowHandlerTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.command(part_of=Order)
        class CreateOrder:
            name = String(required=True)

        @domain.command_handler(part_of=Order)
        class OrderHandler:
            @handle(CreateOrder)
            def create(self, command):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "HANDLER_TOO_BROAD" not in codes
