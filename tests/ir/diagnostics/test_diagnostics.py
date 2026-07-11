"""Diagnostics: TestDiagnostics."""

from protean import Domain, handle
from protean.fields import Identifier
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    build_diagnostics_test_domain,
)
from tests.ir.elements import build_published_event_domain


class TestDiagnostics:
    """Verify UNHANDLED_EVENT diagnostics."""

    def test_unhandled_event_diagnostic(self):
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        unhandled = [d for d in ir["diagnostics"] if d["code"] == "UNHANDLED_EVENT"]
        assert len(unhandled) == 2

    def test_diagnostic_format(self):
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        for diag in ir["diagnostics"]:
            assert "code" in diag
            assert "element" in diag
            assert "level" in diag
            assert "message" in diag

    def test_diagnostics_sorted_by_code(self):
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        codes = [d["code"] for d in ir["diagnostics"]]
        assert codes == sorted(codes)

    def test_no_unhandled_when_all_handled(self):
        domain = Domain(name="NoWarn", root_path=".")

        @domain.event(part_of="Item")
        class ItemCreated:
            item_id = Identifier(identifier=True)

        @domain.command(part_of="Item")
        class CreateItem:
            name = String(required=True)

        @domain.aggregate
        class Item:
            name = String(max_length=50)

        @domain.event_handler(part_of=Item)
        class ItemHandler:
            @handle(ItemCreated)
            def on_created(self, event):
                pass

        @domain.command_handler(part_of=Item)
        class ItemCommandHandler:
            @handle(CreateItem)
            def handle_create(self, command):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        unhandled = [d for d in ir["diagnostics"] if d["code"] == "UNHANDLED_EVENT"]
        unused = [d for d in ir["diagnostics"] if d["code"] == "UNUSED_COMMAND"]
        assert len(unhandled) == 0
        assert len(unused) == 0

    def test_published_events_excluded_from_unhandled(self):
        """Published events are intentionally external and should not
        be flagged as unhandled."""
        domain = build_published_event_domain()
        ir = IRBuilder(domain).build()
        unhandled = [d for d in ir["diagnostics"] if d["code"] == "UNHANDLED_EVENT"]
        # AccountCreated is published — should not appear
        unhandled_fqns = [d["element"] for d in unhandled]
        assert not any("AccountCreated" in f for f in unhandled_fqns)
        # AccountUpdated is NOT published — should appear
        assert any("AccountUpdated" in f for f in unhandled_fqns)

    def test_fact_events_excluded_from_unhandled(self):
        """Fact events are auto-generated and should not be flagged."""
        domain = Domain(name="FactTest", root_path=".")

        @domain.event(part_of="Order")
        class OrderPlaced:
            order_id = Identifier(identifier=True)

        @domain.aggregate(fact_events=True)
        class Order:
            customer_name = String(max_length=100, required=True)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        unhandled = [d for d in ir["diagnostics"] if d["code"] == "UNHANDLED_EVENT"]
        unhandled_names = [d["element"] for d in unhandled]
        # The fact event (auto-generated) should not appear
        assert not any("OrderFactEvent" in n for n in unhandled_names)
        # But OrderPlaced (user-defined, no handler) should appear
        assert any("OrderPlaced" in n for n in unhandled_names)
