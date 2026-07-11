"""Diagnostics: TestAggregateWithoutCommandHandler."""

from protean import Domain, handle
from protean.fields.simple import String
from protean.ir.builder import IRBuilder


class TestAggregateWithoutCommandHandler:
    """Detect aggregates with no command handler (no write path)."""

    def test_aggregate_without_handler_detected(self):
        domain = Domain(name="NoHandlerTest", root_path=".")

        @domain.aggregate
        class Product:
            name = String(max_length=100, required=True)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "AGGREGATE_WITHOUT_COMMAND_HANDLER" in codes

    def test_aggregate_without_handler_format(self):
        domain = Domain(name="NoHandlerFmt", root_path=".")

        @domain.aggregate
        class Widget:
            label = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diag = next(
            d
            for d in ir["diagnostics"]
            if d["code"] == "AGGREGATE_WITHOUT_COMMAND_HANDLER"
        )
        assert diag["level"] == "warning"
        assert "Widget" in diag["message"]
        assert "no command handler" in diag["message"]
        assert "Widget" in diag["element"]

    def test_no_warning_when_handler_exists(self):
        domain = Domain(name="WithHandlerTest", root_path=".")

        @domain.command(part_of="Order")
        class PlaceOrder:
            customer_name = String(required=True)

        @domain.aggregate
        class Order:
            customer_name = String(max_length=100, required=True)

        @domain.command_handler(part_of=Order)
        class OrderHandler:
            @handle(PlaceOrder)
            def place(self, command):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "AGGREGATE_WITHOUT_COMMAND_HANDLER" not in codes
