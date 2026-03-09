"""Tests for IRBuilder elements index, contracts, and diagnostics."""

import pytest

from protean import Domain, handle
from protean.core.aggregate import apply
from protean.fields import Identifier
from protean.fields.simple import Float, String
from protean.ir.builder import IRBuilder

from .elements import build_published_event_domain


def build_diagnostics_test_domain() -> Domain:
    """Build a domain with unhandled events and unused commands."""
    domain = Domain(name="DiagTest", root_path=".")

    @domain.event(part_of="Order")
    class OrderPlaced:
        order_id = Identifier(identifier=True)

    @domain.event(part_of="Order")
    class OrderCancelled:
        order_id = Identifier(identifier=True)

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
            wallet_id = Identifier(identifier=True)

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


# ── PUBLISHED_NO_EXTERNAL_BROKER ─────────────────────────────────────


@pytest.mark.no_test_domain
class TestPublishedNoExternalBroker:
    """Detect published events with no external brokers configured."""

    def test_published_event_without_broker_flagged(self):
        domain = Domain(name="PubNoBrokerTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.event(part_of=Order, published=True)
        class OrderShipped:
            order_id = Identifier(required=True)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [
            d for d in ir["diagnostics"] if d["code"] == "PUBLISHED_NO_EXTERNAL_BROKER"
        ]
        assert len(diags) == 1
        assert diags[0]["level"] == "warning"

    def test_no_warning_when_external_broker_configured(self):
        domain = Domain(name="PubWithBrokerTest", root_path=".")
        domain.config["outbox"] = {"external_brokers": ["redis"]}

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.event(part_of=Order, published=True)
        class OrderShipped:
            order_id = Identifier(required=True)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "PUBLISHED_NO_EXTERNAL_BROKER" not in codes


# ── AGGREGATE_WITHOUT_COMMAND_HANDLER ────────────────────────────────


@pytest.mark.no_test_domain
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


# ── PROJECTION_WITHOUT_PROJECTOR ─────────────────────────────────────


@pytest.mark.no_test_domain
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


# ── AGGREGATE_TOO_LARGE ─────────────────────────────────────────────


@pytest.mark.no_test_domain
class TestAggregateTooLarge:
    """Detect aggregate clusters with too many entities."""

    def test_large_aggregate_detected(self):
        domain = Domain(name="LargeAggTest", root_path=".")
        # Set limit low for testing
        domain.config["lint"] = {"aggregate_size_limit": 2}

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.entity(part_of=Order)
        class LineItem:
            sku = String(max_length=50)

        @domain.entity(part_of=Order)
        class Discount:
            code = String(max_length=20)

        @domain.entity(part_of=Order)
        class Payment:
            amount = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [d for d in ir["diagnostics"] if d["code"] == "AGGREGATE_TOO_LARGE"]
        assert len(diags) == 1
        assert diags[0]["level"] == "info"
        assert "Order" in diags[0]["message"]
        assert "3 entities" in diags[0]["message"]

    def test_no_warning_when_under_limit(self):
        domain = Domain(name="SmallAggTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.entity(part_of=Order)
        class LineItem:
            sku = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "AGGREGATE_TOO_LARGE" not in codes


# ── HANDLER_TOO_BROAD ───────────────────────────────────────────────


@pytest.mark.no_test_domain
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


# ── EVENT_WITHOUT_DATA ──────────────────────────────────────────────


@pytest.mark.no_test_domain
class TestEventWithoutData:
    """Detect events with zero user-defined fields."""

    def test_empty_event_detected(self):
        domain = Domain(name="EmptyEventTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.event(part_of=Order)
        class OrderNudged:
            pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [d for d in ir["diagnostics"] if d["code"] == "EVENT_WITHOUT_DATA"]
        assert len(diags) == 1
        assert diags[0]["level"] == "info"
        assert "OrderNudged" in diags[0]["message"]

    def test_no_warning_when_event_has_fields(self):
        domain = Domain(name="FieldEventTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id = Identifier(required=True)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "EVENT_WITHOUT_DATA" not in codes

    def test_fact_events_excluded(self):
        """Fact events are auto-generated and should not be flagged."""
        domain = Domain(name="FactEventTest", root_path=".")

        @domain.aggregate(fact_events=True)
        class Order:
            name = String(max_length=100)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Find the Order cluster (not MemoryMessage)
        order_cluster = next(
            c for c in ir["clusters"].values() if c["aggregate"]["name"] == "Order"
        )
        fact_events = [
            e for e in order_cluster["events"].values() if e.get("is_fact_event", False)
        ]
        assert len(fact_events) > 0, "Expected at least one fact event"

        # The fact event should NOT trigger EVENT_WITHOUT_DATA
        diags = [d for d in ir["diagnostics"] if d["code"] == "EVENT_WITHOUT_DATA"]
        assert len(diags) == 0


# ── Custom lint rules ───────────────────────────────────────────────

_FIXTURES = "tests.ir.custom_lint_fixtures"


def _build_domain_with_rules(rules: list[str]) -> Domain:
    """Helper: build a minimal domain with custom lint rules configured."""
    domain = Domain(name="CustomRuleTest", root_path=".")
    domain.config["lint"] = {"rules": rules}

    @domain.aggregate
    class Widget:
        label = String(max_length=50)

    domain.init(traverse=False)
    return domain


@pytest.mark.no_test_domain
class TestCustomLintRules:
    """Custom lint rules loaded from [lint] rules config."""

    def test_good_rule_appends_diagnostics(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.good_rule"])
        ir = IRBuilder(domain).build()

        custom = [d for d in ir["diagnostics"] if d["code"] == "CUSTOM_CHECK"]
        assert len(custom) == 1
        assert custom[0]["level"] == "info"
        assert custom[0]["element"] == "test.element"

    def test_multi_result_rule(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.multi_result_rule"])
        ir = IRBuilder(domain).build()

        custom_a = [d for d in ir["diagnostics"] if d["code"] == "CUSTOM_A"]
        custom_b = [d for d in ir["diagnostics"] if d["code"] == "CUSTOM_B"]
        assert len(custom_a) == 1
        assert custom_a[0]["level"] == "warning"
        assert len(custom_b) == 1
        assert custom_b[0]["level"] == "info"

    def test_empty_rule_adds_nothing(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.empty_rule"])
        ir = IRBuilder(domain).build()

        # Only built-in diagnostics should be present
        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CUSTOM_CHECK" not in codes

    def test_raising_rule_is_skipped(self):
        """A rule that throws an exception is logged and skipped."""
        domain = _build_domain_with_rules([f"{_FIXTURES}.raising_rule"])
        ir = IRBuilder(domain).build()

        # Should not crash — built-in diagnostics still present
        assert isinstance(ir["diagnostics"], list)

    def test_bad_return_type_is_skipped(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.bad_return_type"])
        ir = IRBuilder(domain).build()
        assert isinstance(ir["diagnostics"], list)

    def test_missing_keys_skipped(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.missing_keys_rule"])
        ir = IRBuilder(domain).build()

        # The invalid item should not appear
        codes = [d["code"] for d in ir["diagnostics"]]
        assert "PARTIAL" not in codes

    def test_bad_level_skipped(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.bad_level_rule"])
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "BAD_LEVEL" not in codes

    def test_non_dict_item_skipped(self):
        domain = _build_domain_with_rules([f"{_FIXTURES}.non_dict_item_rule"])
        ir = IRBuilder(domain).build()
        assert isinstance(ir["diagnostics"], list)

    def test_import_failure_skipped(self):
        """A non-existent rule path is logged and skipped."""
        domain = _build_domain_with_rules(["nonexistent.module.rule"])
        ir = IRBuilder(domain).build()
        assert isinstance(ir["diagnostics"], list)

    def test_invalid_dotted_path_skipped(self):
        """A rule path without dots (no module) is logged and skipped."""
        domain = _build_domain_with_rules(["norule"])
        ir = IRBuilder(domain).build()
        assert isinstance(ir["diagnostics"], list)

    def test_no_rules_configured(self):
        """No [lint] rules config means no custom rules run."""
        domain = Domain(name="NoRulesTest", root_path=".")

        @domain.aggregate
        class Item:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Should have only built-in diagnostics
        assert isinstance(ir["diagnostics"], list)

    def test_multiple_rules_all_run(self):
        domain = _build_domain_with_rules(
            [
                f"{_FIXTURES}.good_rule",
                f"{_FIXTURES}.multi_result_rule",
            ]
        )
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CUSTOM_CHECK" in codes
        assert "CUSTOM_A" in codes
        assert "CUSTOM_B" in codes
