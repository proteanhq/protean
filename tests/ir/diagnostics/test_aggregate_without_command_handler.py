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


def _flagged_elements(diagnostics: list[dict]) -> list[str]:
    return [
        d["element"]
        for d in diagnostics
        if d["code"] == "AGGREGATE_WITHOUT_COMMAND_HANDLER"
    ]


class TestAbstractAggregateIsNotFlagged:
    """An abstract base aggregate is never instantiated, so it needs no handler."""

    def test_abstract_base_with_handled_subclass_is_not_flagged(self):
        domain = Domain(name="AbstractBaseHandled", root_path=".")

        @domain.aggregate(abstract=True)
        class Tracked:
            created_by = String(max_length=50)

        @domain.aggregate
        class Ticket(Tracked):
            title = String(max_length=100)

        @domain.command(part_of=Ticket)
        class OpenTicket:
            title = String(required=True)

        @domain.command_handler(part_of=Ticket)
        class TicketCommandHandler:
            @handle(OpenTicket)
            def open(self, command):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # The abstract base has its own cluster, so the rule sees it and must skip it.
        assert any(fqn.endswith(".Tracked") for fqn in ir["clusters"])

        flagged = _flagged_elements(ir["diagnostics"])
        assert not any(element.endswith(".Tracked") for element in flagged)
        assert not any(element.endswith(".Ticket") for element in flagged)

    def test_abstract_base_is_not_flagged_through_domain_check(self):
        domain = Domain(name="AbstractBaseCheck", root_path=".")

        @domain.aggregate(abstract=True)
        class Tracked:
            created_by = String(max_length=50)

        @domain.aggregate
        class Ticket(Tracked):
            title = String(max_length=100)

        @domain.command(part_of=Ticket)
        class OpenTicket:
            title = String(required=True)

        @domain.command_handler(part_of=Ticket)
        class TicketCommandHandler:
            @handle(OpenTicket)
            def open(self, command):
                pass

        report = domain.check(traverse=False)

        assert report["errors"] == []
        assert _flagged_elements(report["diagnostics"]) == []

    def test_unhandled_concrete_subclass_is_flagged_but_not_its_abstract_base(self):
        domain = Domain(name="AbstractBaseUnhandled", root_path=".")

        @domain.aggregate(abstract=True)
        class Tracked:
            created_by = String(max_length=50)

        @domain.aggregate
        class Ticket(Tracked):
            title = String(max_length=100)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        flagged = _flagged_elements(ir["diagnostics"])
        assert flagged
        assert any(element.endswith(".Ticket") for element in flagged)
        assert not any(element.endswith(".Tracked") for element in flagged)
