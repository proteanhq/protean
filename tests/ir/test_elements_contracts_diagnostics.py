"""Tests for IRBuilder elements index, contracts, and diagnostics."""

import pytest

from protean import Domain, handle
from protean.core.aggregate import apply
from protean.fields.simple import Float, Identifier, String
from protean.ir.builder import IRBuilder

from .elements import build_published_event_domain


def build_diagnostics_test_domain() -> Domain:
    """Build a domain with unhandled events and unused commands."""
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
            item_id = Identifier(required=True)

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
        assert len(ir["diagnostics"]) == 0

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
            order_id = Identifier(required=True)

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


@pytest.mark.no_test_domain
class TestUnusedCommand:
    """Verify UNUSED_COMMAND diagnostics."""

    def test_unused_command_detected(self):
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        unused = [d for d in ir["diagnostics"] if d["code"] == "UNUSED_COMMAND"]
        assert len(unused) == 1
        assert "PlaceOrder" in unused[0]["element"]

    def test_unused_command_format(self):
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        unused = [d for d in ir["diagnostics"] if d["code"] == "UNUSED_COMMAND"]
        for diag in unused:
            assert diag["level"] == "warning"
            assert "no registered handler" in diag["message"]

    def test_no_unused_when_handler_exists(self):
        domain = Domain(name="HandledCmd", root_path=".")

        @domain.command(part_of="Task")
        class CreateTask:
            title = String(required=True)

        @domain.aggregate
        class Task:
            title = String(max_length=100)

        @domain.command_handler(part_of=Task)
        class TaskCommandHandler:
            @handle(CreateTask)
            def handle_create(self, command):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        unused = [d for d in ir["diagnostics"] if d["code"] == "UNUSED_COMMAND"]
        assert len(unused) == 0


@pytest.mark.no_test_domain
class TestEsEventMissingApply:
    """Verify ES_EVENT_MISSING_APPLY diagnostics."""

    def test_missing_apply_detected(self):
        """ES aggregate with events but no @apply handler for one."""
        domain = Domain(name="EsMissing", root_path=".")

        @domain.event(part_of="Wallet")
        class WalletCreated:
            wallet_id = Identifier(required=True)

        @domain.event(part_of="Wallet")
        class FundsAdded:
            amount = Float(required=True)

        @domain.aggregate(is_event_sourced=True)
        class Wallet:
            balance = Float(default=0.0)

            @apply
            def created(self, event: WalletCreated) -> None:
                pass

            # No @apply for FundsAdded

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        missing = [
            d for d in ir["diagnostics"] if d["code"] == "ES_EVENT_MISSING_APPLY"
        ]
        assert len(missing) == 1
        assert "FundsAdded" in missing[0]["element"]
        assert "Wallet" in missing[0]["message"]

    def test_no_missing_apply_when_all_covered(self):
        from .elements import build_es_aggregate_domain

        domain = build_es_aggregate_domain()
        ir = IRBuilder(domain).build()
        missing = [
            d for d in ir["diagnostics"] if d["code"] == "ES_EVENT_MISSING_APPLY"
        ]
        assert len(missing) == 0

    def test_non_es_aggregate_not_checked(self):
        """Non-ES aggregates should not trigger ES_EVENT_MISSING_APPLY."""
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        missing = [
            d for d in ir["diagnostics"] if d["code"] == "ES_EVENT_MISSING_APPLY"
        ]
        assert len(missing) == 0

    def test_fact_events_excluded_from_apply_check(self):
        """Fact events should not require @apply handlers."""
        domain = Domain(name="EsFact", root_path=".")

        @domain.event(part_of="Account")
        class AccountOpened:
            holder = String(required=True)

        @domain.aggregate(is_event_sourced=True, fact_events=True)
        class Account:
            holder = String(max_length=100, required=True)

            @apply
            def opened(self, event: AccountOpened) -> None:
                self.holder = event.holder

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        missing = [
            d for d in ir["diagnostics"] if d["code"] == "ES_EVENT_MISSING_APPLY"
        ]
        # Fact event should not be flagged
        assert len(missing) == 0

    def test_missing_apply_format(self):
        domain = Domain(name="EsFmt", root_path=".")

        @domain.event(part_of="Ledger")
        class EntryAdded:
            amount = Float(required=True)

        @domain.aggregate(is_event_sourced=True)
        class Ledger:
            total = Float(default=0.0)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        missing = [
            d for d in ir["diagnostics"] if d["code"] == "ES_EVENT_MISSING_APPLY"
        ]
        assert len(missing) == 1
        assert missing[0]["level"] == "warning"
        assert "@apply handler" in missing[0]["message"]


@pytest.mark.no_test_domain
class TestDiagnosticsSortOrder:
    """Verify mixed diagnostics are sorted by code."""

    def test_mixed_diagnostics_sorted(self):
        """A domain with both UNHANDLED_EVENT and UNUSED_COMMAND should
        have diagnostics sorted alphabetically by code."""
        domain = build_diagnostics_test_domain()
        ir = IRBuilder(domain).build()
        codes = [d["code"] for d in ir["diagnostics"]]
        assert codes == sorted(codes)
        # Verify we have both types
        assert "UNHANDLED_EVENT" in codes
        assert "UNUSED_COMMAND" in codes


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
        assert "type" in event
        assert event["type"].startswith("PublishedTest.")

    def test_published_event_has_version(self):
        event = self.ir["contracts"]["events"][0]
        assert event["version"] == 1

    def test_published_event_has_fields(self):
        event = self.ir["contracts"]["events"][0]
        assert "fields" in event
        assert "account_id" in event["fields"]
        assert "holder_name" in event["fields"]

    def test_published_event_keys_are_language_neutral(self):
        """Contract entries should not use Python-specific dunder keys."""
        event = self.ir["contracts"]["events"][0]
        assert "__type__" not in event
        assert "__version__" not in event

    def test_unpublished_event_excluded(self):
        """AccountUpdated is not published and should not appear."""
        fqns = [e["fqn"] for e in self.ir["contracts"]["events"]]
        assert not any("AccountUpdated" in f for f in fqns)
