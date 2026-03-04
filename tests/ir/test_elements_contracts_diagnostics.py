"""Tests for IRBuilder elements index, contracts, and diagnostics."""

import pytest

from protean import Domain
from protean.fields.simple import Float, Identifier, String
from protean.ir.builder import IRBuilder

from .elements import build_published_event_domain


def build_diagnostics_test_domain() -> Domain:
    """Build a domain with an unhandled event for diagnostics testing."""
    domain = Domain(name="DiagTest", root_path=".")

    @domain.event(part_of="Order")
    class OrderPlaced:
        order_id = Identifier(required=True)

    @domain.event(part_of="Order")
    class OrderCancelled:
        order_id = Identifier(required=True)

    @domain.command(part_of="Order")
    class PlaceOrder:
        customer_name = String(required=True)

    @domain.aggregate
    class Order:
        customer_name = String(max_length=100, required=True)
        total = Float(min_value=0.0)

    domain.init(traverse=False)
    return domain


@pytest.mark.no_test_domain
class TestElementsIndex:
    """Verify elements index structure."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.domain = build_diagnostics_test_domain()
        self.ir = IRBuilder(self.domain).build()

    def test_elements_has_all_types(self):
        expected_types = [
            "AGGREGATE",
            "APPLICATION_SERVICE",
            "COMMAND",
            "COMMAND_HANDLER",
            "DATABASE_MODEL",
            "DOMAIN_SERVICE",
            "ENTITY",
            "EVENT",
            "EVENT_HANDLER",
            "PROCESS_MANAGER",
            "PROJECTION",
            "PROJECTOR",
            "QUERY",
            "QUERY_HANDLER",
            "REPOSITORY",
            "SUBSCRIBER",
            "VALUE_OBJECT",
        ]
        for etype in expected_types:
            assert etype in self.ir["elements"], f"Missing element type: {etype}"

    def test_aggregate_in_index(self):
        agg_list = self.ir["elements"]["AGGREGATE"]
        assert any("Order" in fqn for fqn in agg_list)

    def test_command_in_index(self):
        cmd_list = self.ir["elements"]["COMMAND"]
        assert any("PlaceOrder" in fqn for fqn in cmd_list)

    def test_event_in_index(self):
        evt_list = self.ir["elements"]["EVENT"]
        assert any("OrderPlaced" in fqn for fqn in evt_list)

    def test_elements_lists_sorted(self):
        for etype, fqn_list in self.ir["elements"].items():
            assert fqn_list == sorted(fqn_list), f"{etype} list not sorted"

    def test_empty_types_are_empty_lists(self):
        assert self.ir["elements"]["DOMAIN_SERVICE"] == []
        assert self.ir["elements"]["SUBSCRIBER"] == []


@pytest.mark.no_test_domain
class TestDiagnostics:
    """Verify diagnostics are collected."""

    def test_unhandled_event_diagnostic(self):
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        # Both OrderPlaced and OrderCancelled have no handlers
        unhandled = [d for d in ir["diagnostics"] if d["code"] == "UNHANDLED_EVENT"]
        assert len(unhandled) >= 2

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

    def test_no_diagnostics_when_all_handled(self):
        from protean import handle

        domain = Domain(name="NoWarn", root_path=".")

        @domain.event(part_of="Item")
        class ItemCreated:
            item_id = Identifier(required=True)

        @domain.aggregate
        class Item:
            name = String(max_length=50)

        @domain.event_handler(part_of=Item)
        class ItemHandler:
            @handle(ItemCreated)
            def on_created(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        unhandled = [d for d in ir["diagnostics"] if d["code"] == "UNHANDLED_EVENT"]
        assert len(unhandled) == 0


@pytest.mark.no_test_domain
class TestContracts:
    """Verify contracts section."""

    def test_contracts_events_empty_when_none_published(self):
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        # No events have published=True in this domain
        assert ir["contracts"]["events"] == []

    def test_contracts_structure(self):
        domain = Domain(name="Test", root_path=".")
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        assert "events" in ir["contracts"]
        assert isinstance(ir["contracts"]["events"], list)


@pytest.mark.no_test_domain
class TestPublishedContracts:
    """Verify published events appear in the contracts section."""

    @pytest.fixture(autouse=True)
    def setup(self):
        domain = build_published_event_domain()
        self.ir = IRBuilder(domain).build()

    def test_published_event_in_contracts(self):
        events = self.ir["contracts"]["events"]
        assert len(events) == 1

    def test_published_event_has_fqn(self):
        event = self.ir["contracts"]["events"][0]
        assert "AccountCreated" in event["fqn"]

    def test_published_event_has_type(self):
        event = self.ir["contracts"]["events"][0]
        assert "__type__" in event

    def test_unpublished_event_excluded(self):
        """AccountUpdated is not published and should not appear."""
        fqns = [e["fqn"] for e in self.ir["contracts"]["events"]]
        assert not any("AccountUpdated" in f for f in fqns)
