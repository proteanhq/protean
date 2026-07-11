"""Tests for IRBuilder elements index, contracts, and diagnostics."""

import pytest

from protean import Domain, handle
from protean.core.aggregate import BaseAggregate, apply
from protean.core.entity import invariant
from protean.core.value_object import BaseValueObject
from protean.exceptions import ConfigurationError, ValidationError
from protean.fields import Dict, HasMany, HasOne, Identifier, List, Reference
from protean.fields.simple import Float, String
from protean.ir.builder import IRBuilder
from protean.utils import fqn
from protean.utils.mixins import read

from .elements import build_published_event_domain
from .support import (
    infra_from_import_domain,
    infra_guarded_domain,
    infra_import_domain,
)


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
class TestInternalElementsExcluded:
    """Internal framework elements (like Outbox) must not appear in the IR."""

    def test_internal_aggregate_excluded_from_elements_index(self):
        """An aggregate registered with internal=True should not appear
        in the elements index."""
        from protean.core.aggregate import BaseAggregate

        domain = Domain(name="InternalTest", root_path=".")

        @domain.aggregate
        class Order:
            customer_name = String(max_length=100, required=True)

        class InternalTracker(BaseAggregate):
            status = String(max_length=20)

        domain.register(InternalTracker, internal=True)
        domain.init(traverse=False)

        ir = IRBuilder(domain).build()

        agg_fqns = ir["elements"]["AGGREGATE"]
        assert any("Order" in fqn for fqn in agg_fqns)
        assert not any("InternalTracker" in fqn for fqn in agg_fqns)

    def test_internal_aggregate_excluded_from_clusters(self):
        """An aggregate registered with internal=True should not appear
        in the clusters section."""
        from protean.core.aggregate import BaseAggregate

        domain = Domain(name="InternalClusterTest", root_path=".")

        @domain.aggregate
        class Order:
            customer_name = String(max_length=100, required=True)

        class InternalTracker(BaseAggregate):
            status = String(max_length=20)

        domain.register(InternalTracker, internal=True)
        domain.init(traverse=False)

        ir = IRBuilder(domain).build()

        cluster_names = [c["aggregate"]["name"] for c in ir["clusters"].values()]
        assert "Order" in cluster_names
        assert "InternalTracker" not in cluster_names


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

    def test_no_warning_when_externally_populated(self):
        """A projection marked externally_populated (subscriber/handler-written,
        the ACL pattern) must not be flagged even with no co-located projector."""
        domain = Domain(name="AclProjTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.projection(externally_populated=True)
        class VerifiedPurchases:
            order_id = Identifier(identifier=True)
            name = String(max_length=100)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        proj_warnings = [
            d
            for d in ir["diagnostics"]
            if d["code"] == "PROJECTION_WITHOUT_PROJECTOR"
            and "VerifiedPurchases" in d["element"]
        ]
        assert proj_warnings == []

    def test_externally_populated_false_still_warns(self):
        """The opt-out is explicit: a plain projection with no projector still
        warns (guards against the flag defaulting on)."""
        domain = Domain(name="PlainProjTest", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=100)

        @domain.projection
        class PlainView:
            order_id = Identifier(identifier=True)
            name = String(max_length=100)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        proj_warnings = [
            d
            for d in ir["diagnostics"]
            if d["code"] == "PROJECTION_WITHOUT_PROJECTOR"
            and "PlainView" in d["element"]
        ]
        assert len(proj_warnings) == 1


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

    def test_error_level_rejected_for_custom_rules(self):
        """Custom rules cannot use 'error' level — errors are DomainValidator's domain."""
        domain = _build_domain_with_rules([f"{_FIXTURES}.error_level_rule"])
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CUSTOM_ERROR" not in codes

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


# ── Enriched diagnostic schema (category / rule / suggestion) ────────


def build_all_categories_domain() -> Domain:
    """A domain that emits at least one diagnostic per built-in category."""
    domain = Domain(name="AllCategories", root_path=".")

    @domain.aggregate(deprecated={"since": "0.15", "removal": "1.0"})
    class Order:  # deprecation + handler_completeness (no command handler)
        name = String(max_length=100)

    @domain.event(part_of=Order)
    class OrderNudged:  # aggregate_design (EVENT_WITHOUT_DATA) + UNHANDLED_EVENT
        pass

    @domain.event(part_of=Order)
    class OrderPlaced:  # versioning (UPCASTER_GAP) + UNHANDLED_EVENT
        __version__ = 2
        name = String()

    domain.init(traverse=False)
    return domain


# The full set of built-in diagnostic codes. Every one must be exercised by
# ``_all_builtin_diagnostics`` so the schema-enrichment assertions cover *every*
# emit site — not just the handful ``build_all_categories_domain`` produces.
_BUILTIN_CODES = frozenset(
    {
        "UNHANDLED_EVENT",
        "UNUSED_COMMAND",
        "ES_EVENT_MISSING_APPLY",
        "PUBLISHED_NO_EXTERNAL_BROKER",
        "AGGREGATE_WITHOUT_COMMAND_HANDLER",
        "PROJECTION_WITHOUT_PROJECTOR",
        "AGGREGATE_TOO_LARGE",
        "HANDLER_TOO_BROAD",
        "EVENT_WITHOUT_DATA",
        "UPCASTER_GAP",
        "DEPRECATED_ELEMENT",
        "DEPRECATED_FIELD",
        "DEPRECATED_OPTION",
        "DEPRECATED_EMAIL",
        "CROSS_AGGREGATE_REFERENCE",
        "ES_AGGREGATE_NO_EVENTS",
        "VALUE_OBJECT_MUTABLE_FIELD",
        "AGGREGATE_NO_INVARIANTS",
        "CIRCULAR_CLUSTER_DEPENDENCY",
        "INFRA_IMPORT_IN_DOMAIN",
        "QUERY_HANDLER_WITHOUT_QUERY",
        "PROJECTOR_HANDLES_ORPHANED_EVENT",
        "COMMAND_HANDLER_CROSS_CLUSTER",
        "SUBSCRIBER_NO_STREAMS",
        "PROCESS_MANAGER_UNCLOSED",
    }
)


def _build_aggregate_design_domain() -> Domain:
    """Emits all four aggregate-design fitness-function codes so the shared
    schema-enrichment assertions cover their emit sites too.

    ``CROSS_AGGREGATE_REFERENCE`` (Customer→Order), ``ES_AGGREGATE_NO_EVENTS``
    (event-sourced Ledger with no events), ``VALUE_OBJECT_MUTABLE_FIELD``
    (a VO with a ``List`` field), and ``AGGREGATE_NO_INVARIANTS`` (every
    aggregate here lacks invariants).
    """
    domain = Domain(name="AggregateDesign", root_path=".")

    @domain.aggregate
    class Order:
        total = Float()

    @domain.aggregate
    class Customer:
        name = String()
        order = Reference(Order)  # CROSS_AGGREGATE_REFERENCE

    @domain.aggregate(event_sourced=True)
    class Ledger:  # ES_AGGREGATE_NO_EVENTS — no events declared
        balance = Float()

    @domain.value_object(part_of=Order)
    class ShippingLabel:
        carrier = String()
        tags = List()  # VALUE_OBJECT_MUTABLE_FIELD

    domain.init(traverse=False)
    return domain


def _build_completeness_domain() -> Domain:
    """Emits UNUSED_COMMAND, PUBLISHED_NO_EXTERNAL_BROKER,
    PROJECTION_WITHOUT_PROJECTOR, AGGREGATE_TOO_LARGE, HANDLER_TOO_BROAD,
    DEPRECATED_FIELD (plus AGGREGATE_WITHOUT_COMMAND_HANDLER)."""
    domain = Domain(name="EnrichCompleteness", root_path=".")
    domain.config["lint"] = {"aggregate_size_limit": 1, "handler_breadth_limit": 1}

    @domain.aggregate
    class Order:
        legacy = String(max_length=10, deprecated="0.15")  # DEPRECATED_FIELD

    @domain.entity(part_of=Order)
    class LineItem:  # two entities > size limit 1 → AGGREGATE_TOO_LARGE
        sku = String(max_length=10)

    @domain.entity(part_of=Order)
    class Discount:
        code = String(max_length=10)

    @domain.command(part_of=Order)
    class PlaceOrder:
        name = String(required=True)

    @domain.command(part_of=Order)
    class CancelOrder:
        name = String(required=True)

    @domain.command(part_of=Order)
    class ArchiveOrder:  # no handler → UNUSED_COMMAND
        name = String(required=True)

    @domain.command_handler(part_of=Order)
    class OrderHandler:  # handles 2 > breadth limit 1 → HANDLER_TOO_BROAD
        @handle(PlaceOrder)
        def place(self, command):
            pass

        @handle(CancelOrder)
        def cancel(self, command):
            pass

    @domain.event(part_of=Order, published=True)
    class OrderShipped:  # published, no external broker → PUBLISHED_NO_EXTERNAL_BROKER
        order_id = Identifier(required=True)

    @domain.projection
    class OrderView:  # no projector → PROJECTION_WITHOUT_PROJECTOR
        order_id = Identifier(identifier=True)

    domain.init(traverse=False)
    return domain


def _build_es_domain() -> Domain:
    """Emits ES_EVENT_MISSING_APPLY and DEPRECATED_OPTION (the ``is_event_sourced``
    alias emit site in ``_diagnose_deprecated_options``)."""
    import warnings

    domain = Domain(name="EnrichEs", root_path=".")

    @domain.event(part_of="Wallet")
    class WalletCreated:
        wallet_id = Identifier(identifier=True)

    @domain.event(part_of="Wallet")
    class FundsAdded:
        amount = Float(required=True)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # `is_event_sourced` alias is deprecated

        @domain.aggregate(is_event_sourced=True)  # alias → DEPRECATED_OPTION
        class Wallet:
            balance = Float(default=0.0)

            @apply
            def created(self, event: WalletCreated) -> None:  # no @apply for FundsAdded
                pass

    domain.init(traverse=False)
    return domain


def _build_flow_fitness_domain() -> Domain:
    """Emits QUERY_HANDLER_WITHOUT_QUERY, PROJECTOR_HANDLES_ORPHANED_EVENT,
    and PROCESS_MANAGER_UNCLOSED (the 3.5.4 rules exercised for schema
    enrichment)."""
    domain = Domain(name="EnrichFlowFitness", root_path=".")

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

    @domain.query_handler(part_of=OrderView)  # no query → QUERY_HANDLER_WITHOUT_QUERY
    class OrderViewQueryHandler:
        pass

    @domain.process_manager(
        stream_categories=["order"]
    )  # no end → PROCESS_MANAGER_UNCLOSED
    class OrderSaga:
        order_id = Identifier()

        @handle(OrderPlaced, start=True, correlate="order_id")
        def on_placed(self, event):
            self.order_id = event.order_id

    domain.init(traverse=False)

    # An orphaned projector handler key (a stale ``__type__`` no live domain can
    # register) only exists in materialized IR — inject it so the enrichment
    # sweep covers the PROJECTOR_HANDLES_ORPHANED_EVENT emit site.
    method = next(iter(OrderViewProjector._handlers[OrderPlaced.__type__]))
    OrderViewProjector._handlers["EnrichFlowFitness.RemovedEvent.v1"].add(method)

    return domain


def _all_builtin_diagnostics() -> list[dict]:
    """Diagnostics covering every built-in code, merged from focused domains.

    A single domain cannot naturally emit all built-in codes without
    interactions, so each code (or small compatible group) gets a minimal
    domain. The merged list drives the schema-enrichment assertions across
    *every* emit site — including the second ``DEPRECATED_OPTION`` site
    (command ``published``) and ``DEPRECATED_EMAIL``, which are otherwise
    unasserted.
    """
    import warnings

    diagnostics: list[dict] = []
    diagnostics += IRBuilder(build_all_categories_domain()).build()["diagnostics"]
    diagnostics += IRBuilder(_build_completeness_domain()).build()["diagnostics"]
    diagnostics += IRBuilder(_build_es_domain()).build()["diagnostics"]
    diagnostics += IRBuilder(_build_aggregate_design_domain()).build()["diagnostics"]

    # DEPRECATED_OPTION — command ``published`` emit site (distinct dict from
    # the aggregate-alias site above; both are hand-copied and must be checked).
    cmd_domain = Domain(name="EnrichCmdOption", root_path=".")

    @cmd_domain.aggregate
    class Order:
        name = String(max_length=10)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        @cmd_domain.command(part_of=Order, published=True)
        class PlaceOrder:
            name = String(required=True)

    cmd_domain.init(traverse=False)
    diagnostics += IRBuilder(cmd_domain).build()["diagnostics"]

    # DEPRECATED_EMAIL — the email subsystem is itself deprecated.
    email_domain = Domain(name="EnrichEmail")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")

        @email_domain.email
        class WelcomeMail:
            pass

    email_domain.init(traverse=False)
    diagnostics += IRBuilder(email_domain).build()["diagnostics"]

    # CIRCULAR_CLUSTER_DEPENDENCY — a 2-cluster identity-reference cycle.
    cycle_domain = Domain(name="EnrichCycle", root_path=".")

    @cycle_domain.aggregate
    class CycleOrder:
        name = String(max_length=10)
        customer = Reference("CycleCustomer")

    @cycle_domain.aggregate
    class CycleCustomer:
        name = String(max_length=10)
        order = Reference("CycleOrder")

    cycle_domain.init(traverse=False)
    diagnostics += IRBuilder(cycle_domain).build()["diagnostics"]

    # INFRA_IMPORT_IN_DOMAIN — opt-in; the fixture module imports protean.adapters.
    infra_domain = Domain(name="EnrichInfra", root_path=".")
    infra_domain.config["lint"] = {"check_infra_imports": True}
    infra_domain.register(infra_import_domain.Money)
    infra_domain.register(infra_import_domain.InfraOrder)
    infra_domain.init(traverse=False)
    diagnostics += IRBuilder(infra_domain).build()["diagnostics"]

    # 3.5.4 flow-fitness rules reachable from a live domain.
    diagnostics += IRBuilder(_build_flow_fitness_domain()).build()["diagnostics"]

    # SUBSCRIBER_NO_STREAMS — the subscriber factory hard-requires a stream, so
    # null it post-init to reach the materialized-IR state the rule guards.
    sub_domain = Domain(name="EnrichSubscriber", root_path=".")

    @sub_domain.subscriber(broker="default", stream="payments")
    class PaymentSubscriber:
        def __call__(self, payload):
            pass

    sub_domain.init(traverse=False)
    PaymentSubscriber.meta_.stream = None
    diagnostics += IRBuilder(sub_domain).build()["diagnostics"]

    # COMMAND_HANDLER_CROSS_CLUSTER — handler_setup forbids a handler targeting
    # another cluster's command, so inject the foreign command type into the
    # handler map (the state stored/hand-edited IR can carry).
    xc_domain = Domain(name="EnrichCrossCluster", root_path=".")

    @xc_domain.aggregate
    class Order:
        name = String(max_length=50)

    @xc_domain.aggregate
    class Shipment:
        name = String(max_length=50)

    @xc_domain.command(part_of=Order)
    class PlaceOrder:
        order_id = Identifier(identifier=True)

    @xc_domain.command(part_of=Shipment)
    class DispatchShipment:
        shipment_id = Identifier(identifier=True)

    @xc_domain.command_handler(part_of=Order)
    class OrderCommandHandler:
        @handle(PlaceOrder)
        def place(self, command):
            pass

    xc_domain.init(traverse=False)
    method = next(iter(OrderCommandHandler._handlers[PlaceOrder.__type__]))
    OrderCommandHandler._handlers[DispatchShipment.__type__].add(method)
    diagnostics += IRBuilder(xc_domain).build()["diagnostics"]

    return diagnostics


@pytest.mark.no_test_domain
class TestDiagnosticSchemaEnrichment:
    """Every built-in diagnostic carries category, rule, and suggestion."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.domain = build_all_categories_domain()
        self.ir = IRBuilder(self.domain).build()
        self.diagnostics = self.ir["diagnostics"]

    def test_every_builtin_emit_site_carries_enriched_keys(self):
        """Assert across *all* built-in codes — not just the five
        ``build_all_categories_domain`` produces. A missing/typo ``rule``/
        ``suggestion`` key at any of the 16 emit sites fails here."""
        diagnostics = _all_builtin_diagnostics()
        observed = {d["code"] for d in diagnostics}
        assert observed >= _BUILTIN_CODES, (
            f"emit sites not exercised: {sorted(_BUILTIN_CODES - observed)}"
        )
        for d in diagnostics:
            if d["code"] not in _BUILTIN_CODES:
                continue  # custom/foreign findings are not schema-enriched
            rule = d.get("rule")
            assert d.get("category"), f"{d['code']} missing category"
            assert isinstance(rule, dict), f"{d['code']} missing rule dict"
            assert rule.get("rationale"), f"{d['code']} rule missing rationale"
            assert rule.get("fix"), f"{d['code']} rule missing fix"
            assert d.get("suggestion") == rule["fix"], f"{d['code']} suggestion drift"

    def test_every_diagnostic_carries_the_enriched_keys(self):
        assert len(self.diagnostics) > 0, "Expected diagnostics but got none"
        for d in self.diagnostics:
            assert d.get("category"), f"{d['code']} missing category"
            rule = d.get("rule")
            assert isinstance(rule, dict), f"{d['code']} missing rule dict"
            assert rule.get("rationale"), f"{d['code']} rule missing rationale"
            assert rule.get("fix"), f"{d['code']} rule missing fix"
            assert d.get("suggestion"), f"{d['code']} missing suggestion"

    def test_suggestion_defaults_to_rule_fix(self):
        # The separate ``suggestion`` key is the forward-compat AI-override
        # hook; for shipped rules it equals ``rule["fix"]`` (no override yet).
        assert len(self.diagnostics) > 0
        for d in self.diagnostics:
            assert d["suggestion"] == d["rule"]["fix"]

    def test_code_to_category_mapping(self):
        by_code = {d["code"]: d["category"] for d in self.diagnostics}
        assert by_code["AGGREGATE_WITHOUT_COMMAND_HANDLER"] == "handler_completeness"
        assert by_code["EVENT_WITHOUT_DATA"] == "aggregate_design"
        assert by_code["UPCASTER_GAP"] == "versioning"
        assert by_code["DEPRECATED_ELEMENT"] == "deprecation"

    def test_all_four_categories_present(self):
        categories = {d["category"] for d in self.diagnostics}
        assert {
            "handler_completeness",
            "aggregate_design",
            "versioning",
            "deprecation",
        } <= categories


# ── Per-element suppress_checks ─────────────────────────────────────


def _codes_for(ir: dict, element_substr: str) -> list[str]:
    """Codes of diagnostics whose element FQN contains ``element_substr``."""
    return [
        d["code"] for d in ir["diagnostics"] if element_substr in d.get("element", "")
    ]


@pytest.mark.no_test_domain
class TestSuppressChecksOption:
    """The per-element ``suppress_checks`` option drops the named codes."""

    def test_aggregate_suppresses_its_own_code(self):
        domain = Domain(name="SuppressAgg", root_path=".")

        @domain.aggregate(suppress_checks=["AGGREGATE_WITHOUT_COMMAND_HANDLER"])
        class Suppressed:
            name = String(max_length=50)

        @domain.aggregate
        class Kept:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Suppressed aggregate: its finding is gone; Kept still has it. This
        # also proves one element's suppression does not affect another.
        assert "AGGREGATE_WITHOUT_COMMAND_HANDLER" not in _codes_for(ir, "Suppressed")
        assert "AGGREGATE_WITHOUT_COMMAND_HANDLER" in _codes_for(ir, "Kept")

    def test_event_suppression_via_registry_no_options_block(self):
        """Events carry no IR ``options`` block, so suppression must resolve
        from the registry — this is the load-bearing no-options-block path."""
        domain = Domain(name="SuppressEvent", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.event(part_of=Order, suppress_checks=["UNHANDLED_EVENT"])
        class OrderPlaced:
            name = String()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert "UNHANDLED_EVENT" not in _codes_for(ir, "OrderPlaced")

    def test_command_inherits_suppress_checks(self):
        """Commands pick up ``suppress_checks`` via the inherited option set
        (``BaseMessageType`` → filtered comprehension in command.py)."""
        domain = Domain(name="SuppressCommand", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.command(part_of=Order, suppress_checks=["UNUSED_COMMAND"])
        class PlaceOrder:
            name = String(required=True)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert "UNUSED_COMMAND" not in _codes_for(ir, "PlaceOrder")

    def test_unmatched_code_removes_nothing(self):
        domain = Domain(name="SuppressNoMatch", root_path=".")

        @domain.aggregate(suppress_checks=["NONEXISTENT_CODE"])
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert "AGGREGATE_WITHOUT_COMMAND_HANDLER" in _codes_for(ir, "Order")

    def test_bare_string_is_normalised_to_single_code(self):
        """A bare string (not a list) is treated as one code, not iterated
        character-by-character — otherwise the finding silently survives."""
        domain = Domain(name="SuppressBareString", root_path=".")

        @domain.aggregate(suppress_checks="AGGREGATE_WITHOUT_COMMAND_HANDLER")
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert "AGGREGATE_WITHOUT_COMMAND_HANDLER" not in _codes_for(ir, "Order")


# ── [lint].suppressions allow-list ──────────────────────────────────


def _build_five_finding_domain(suppressions: dict | None = None) -> Domain:
    """Domain with five AGGREGATE_WITHOUT_COMMAND_HANDLER findings.

    One per aggregate (OrderA..OrderE), so the total order over survivors is
    by aggregate FQN — deterministic and independent of rule execution order.
    """
    domain = Domain(name="AllowList", root_path=".")

    @domain.aggregate
    class OrderA:
        name = String(max_length=50)

    @domain.aggregate
    class OrderB:
        name = String(max_length=50)

    @domain.aggregate
    class OrderC:
        name = String(max_length=50)

    @domain.aggregate
    class OrderD:
        name = String(max_length=50)

    @domain.aggregate
    class OrderE:
        name = String(max_length=50)

    if suppressions is not None:
        domain.config["lint"] = {"suppressions": suppressions}

    domain.init(traverse=False)
    return domain


@pytest.mark.no_test_domain
class TestSuppressionAllowList:
    """``[lint].suppressions`` grandfathers the first N findings per code."""

    def _handler_gap_elements(self, ir: dict) -> list[str]:
        return sorted(
            d["element"]
            for d in ir["diagnostics"]
            if d["code"] == "AGGREGATE_WITHOUT_COMMAND_HANDLER"
        )

    def test_count_grandfathers_first_n(self):
        domain = _build_five_finding_domain({"AGGREGATE_WITHOUT_COMMAND_HANDLER": 2})
        ir = IRBuilder(domain).build()
        survivors = self._handler_gap_elements(ir)
        assert len(survivors) == 3

    def test_survivors_are_the_deterministic_tail(self):
        """The survivors are exactly those ranked *after* position N in the
        (code, element, field, message) total order — not merely count − N."""
        domain = _build_five_finding_domain({"AGGREGATE_WITHOUT_COMMAND_HANDLER": 2})
        ir = IRBuilder(domain).build()

        all_elements = sorted(
            fqn
            for fqn in {
                d["element"]
                for d in IRBuilder(_build_five_finding_domain()).build()["diagnostics"]
                if d["code"] == "AGGREGATE_WITHOUT_COMMAND_HANDLER"
            }
        )
        assert len(all_elements) == 5
        expected_survivors = all_elements[2:]  # first 2 grandfathered away
        assert self._handler_gap_elements(ir) == expected_survivors

    def test_build_is_deterministic(self):
        domain = _build_five_finding_domain({"AGGREGATE_WITHOUT_COMMAND_HANDLER": 2})
        first = IRBuilder(domain).build()["diagnostics"]
        second = IRBuilder(domain).build()["diagnostics"]
        assert first == second

    def test_absent_suppressions_keeps_all(self):
        domain = _build_five_finding_domain()
        ir = IRBuilder(domain).build()
        assert len(self._handler_gap_elements(ir)) == 5

    def test_zero_count_suppresses_nothing(self):
        domain = _build_five_finding_domain({"AGGREGATE_WITHOUT_COMMAND_HANDLER": 0})
        ir = IRBuilder(domain).build()
        assert len(self._handler_gap_elements(ir)) == 5

    def test_custom_rule_findings_are_subject_to_allow_list(self):
        """Custom findings with only the minimal keys are still allow-listed
        and default to category='custom' — no KeyError on the absent keys."""
        domain = Domain(name="CustomAllowList", root_path=".")
        domain.config["lint"] = {
            "rules": [f"{_FIXTURES}.repeated_code_rule"],
            "suppressions": {"REPEATED": 1},
        }

        @domain.aggregate
        class Widget:
            label = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        repeated = [d for d in ir["diagnostics"] if d["code"] == "REPEATED"]
        assert len(repeated) == 2  # 3 emitted, first 1 grandfathered
        assert all(d["category"] == "custom" for d in repeated)

    def test_grandfathered_set_follows_sort_not_emission_order(self):
        """The load-bearing ``survivors.sort(...)``: findings emitted OUT of
        sort order (z, a, q, b, k) must be grandfathered by *sorted* order, so
        the first two removed are ``a``/``b`` — not the first two *emitted*
        (``z``/``a``). Replacing the sort with a no-op would fail this."""
        domain = Domain(name="ScrambledAllowList", root_path=".")
        domain.config["lint"] = {
            "rules": [f"{_FIXTURES}.scrambled_code_rule"],
            "suppressions": {"SCRAMBLED": 2},
        }

        @domain.aggregate
        class Widget:
            label = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        survivors = sorted(
            d["element"] for d in ir["diagnostics"] if d["code"] == "SCRAMBLED"
        )
        # sorted(z,a,q,b,k) = a,b,k,q,z; first two (a,b) grandfathered away.
        assert survivors == ["test.k", "test.q", "test.z"]


@pytest.mark.no_test_domain
class TestSuppressionsConfigValidation:
    """``[lint].suppressions`` must be a table of non-negative integers."""

    def _domain_with_suppressions(self, suppressions) -> Domain:
        domain = Domain(name="BadSuppressions", root_path=".")
        domain.config["lint"] = {"suppressions": suppressions}

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        return domain

    def test_string_count_raises_configuration_error(self):
        domain = self._domain_with_suppressions({"AGGREGATE_TOO_LARGE": "3"})
        with pytest.raises(ConfigurationError, match="non-negative integer"):
            IRBuilder(domain).build()

    def test_negative_count_raises_configuration_error(self):
        domain = self._domain_with_suppressions({"AGGREGATE_TOO_LARGE": -1})
        with pytest.raises(ConfigurationError, match="non-negative integer"):
            IRBuilder(domain).build()

    def test_boolean_count_raises_configuration_error(self):
        # ``bool`` is an ``int`` subclass — must be rejected, not read as 1.
        domain = self._domain_with_suppressions({"AGGREGATE_TOO_LARGE": True})
        with pytest.raises(ConfigurationError, match="non-negative integer"):
            IRBuilder(domain).build()

    def test_non_table_raises_configuration_error(self):
        domain = self._domain_with_suppressions(5)
        with pytest.raises(ConfigurationError, match="table of"):
            IRBuilder(domain).build()

    def test_valid_zero_count_does_not_raise(self):
        domain = self._domain_with_suppressions(
            {"AGGREGATE_WITHOUT_COMMAND_HANDLER": 0}
        )
        # Must build cleanly — 0 is a valid non-negative integer.
        ir = IRBuilder(domain).build()
        assert any(
            d["code"] == "AGGREGATE_WITHOUT_COMMAND_HANDLER" for d in ir["diagnostics"]
        )


@pytest.mark.no_test_domain
class TestLintTableConfigValidation:
    """``[lint]`` itself must be a table — non-CLI entry points (``protean
    generate``, materialize hooks, staleness detection) build the IR directly
    without going through ``protean check``'s validation, so the builder must
    reject a malformed ``[lint]`` before any ``[lint]``-scoped rule reads it."""

    def test_non_table_lint_raises_configuration_error(self):
        domain = Domain(name="BadLintTable", root_path=".")
        domain.config["lint"] = 5

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        with pytest.raises(ConfigurationError, match=r"\[lint\] must be a table"):
            IRBuilder(domain).build()

    def test_non_table_lint_raises_before_aggregate_size_limit_read(self):
        """``aggregate_size_limit`` runs before the suppression
        stage in ``_collect_diagnostics`` — the guard must fire before *any*
        rule reads ``[lint]``, not just before ``_apply_suppressions``."""
        domain = Domain(name="BadLintTableEarly", root_path=".")
        domain.config["lint"] = "not-a-table"

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        with pytest.raises(ConfigurationError, match=r"\[lint\] must be a table"):
            IRBuilder(domain).build()


# ── Aggregate & value-object fitness functions ────────────────


@pytest.mark.no_test_domain
class TestCrossAggregateReference:
    """CROSS_AGGREGATE_REFERENCE flags a ``Reference`` to a different
    aggregate's root, but never a child→own-root back-pointer."""

    def test_reference_to_other_aggregate_flagged(self):
        domain = Domain(name="CrossRef", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate
        class Customer:
            name = String()
            order = Reference(Order)  # points at a *different* aggregate's root

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [
            d for d in ir["diagnostics"] if d["code"] == "CROSS_AGGREGATE_REFERENCE"
        ]
        assert len(diags) == 1
        d = diags[0]
        assert d["element"] == fqn(Customer)
        assert d["field"] == "order"
        assert d["level"] == "warning"
        # diagnostic schema
        assert d["category"] == "aggregate_design"
        assert d["rule"]["rationale"]
        assert d["rule"]["fix"]
        assert d["suggestion"] == d["rule"]["fix"]

    def test_child_back_pointer_not_flagged(self):
        """The load-bearing compliant case: a child entity referencing its own
        aggregate root (target == own cluster key) is never flagged, and the
        root's ``HasMany`` is out of scope."""
        domain = Domain(name="PostBlog", root_path=".")

        @domain.aggregate
        class Post:
            title = String()
            comments = HasMany("Comment")  # root→child composition, out of scope

        @domain.entity(part_of=Post)
        class Comment:
            content = String()
            post = Reference(Post)  # child→own-root back-pointer, target == own

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CROSS_AGGREGATE_REFERENCE" not in codes

    def test_associations_only_not_flagged(self):
        """An aggregate holding only ``HasOne``/``HasMany`` (no ``Reference``)
        is never flagged, regardless of target."""
        domain = Domain(name="OnlyAssoc", root_path=".")

        @domain.aggregate
        class Basket:
            label = String()
            item = HasOne("BasketItem")
            extras = HasMany("BasketExtra")

        @domain.entity(part_of=Basket)
        class BasketItem:
            sku = String()

        @domain.entity(part_of=Basket)
        class BasketExtra:
            note = String()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CROSS_AGGREGATE_REFERENCE" not in codes

    def test_reference_to_entity_not_flagged(self):
        """The ``target in cluster_keys`` guard: a ``Reference`` whose target is
        another aggregate's child *entity* (not a cluster key / root) is out of
        scope and never flagged. Deleting that guard must fail this test."""
        domain = Domain(name="RefToEntity", root_path=".")

        @domain.aggregate
        class Catalog:
            name = String()
            products = HasMany("Product")

        @domain.entity(part_of=Catalog)
        class Product:
            sku = String()

        @domain.aggregate
        class Wishlist:
            product = Reference(Product)  # target is an entity, not a root

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CROSS_AGGREGATE_REFERENCE" not in codes

    def test_abstract_aggregate_not_flagged(self):
        """An abstract aggregate carrying a cross-aggregate ``Reference`` is
        skipped — the shape only exists on a non-instantiable base."""
        domain = Domain(name="CrossRefAbstract", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate(abstract=True)
        class BaseCustomer:
            name = String()
            order = Reference(Order)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CROSS_AGGREGATE_REFERENCE" not in codes

    def test_infrastructure_aggregate_not_flagged(self):
        """A framework/infrastructure aggregate (FQN under ``protean.adapters.``)
        is skipped even when it carries a cross-aggregate ``Reference``. Deleting
        the ``protean.adapters.`` guard must fail this test."""
        domain = Domain(name="CrossRefInfra", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate
        class Customer:
            name = String()
            order = Reference(Order)

        # Masquerade as an infrastructure aggregate so its cluster FQN sits under
        # ``protean.adapters.`` (real adapter aggregates are internal and never
        # clustered, so this override is how the guard is reached).
        Customer.__module__ = "protean.adapters.fake"

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "CROSS_AGGREGATE_REFERENCE" not in codes

    def test_suppress_checks_drops_code(self):
        domain = Domain(name="CrossRefSuppress", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.aggregate(suppress_checks=["CROSS_AGGREGATE_REFERENCE"])
        class Customer:
            name = String()
            order = Reference(Order)

        @domain.aggregate
        class Invoice:
            order = Reference(Order)  # identical shape, not suppressed

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Suppressed on Customer, yet the identical shape on Invoice still fires:
        # the rule is active and suppression is selective, not a global no-op.
        assert "CROSS_AGGREGATE_REFERENCE" not in _codes_for(ir, "Customer")
        assert "CROSS_AGGREGATE_REFERENCE" in _codes_for(ir, "Invoice")


@pytest.mark.no_test_domain
class TestESAggregateNoEvents:
    """ES_AGGREGATE_NO_EVENTS flags an ``event_sourced=True`` aggregate with no
    events (it cannot reconstitute state)."""

    def test_es_aggregate_without_events_flagged(self):
        domain = Domain(name="ESNoEvents", root_path=".")

        @domain.aggregate(event_sourced=True)
        class Account:
            balance = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [d for d in ir["diagnostics"] if d["code"] == "ES_AGGREGATE_NO_EVENTS"]
        assert len(diags) == 1
        d = diags[0]
        assert d["element"] == fqn(Account)
        assert d["level"] == "warning"
        assert d["category"] == "aggregate_design"
        assert d["rule"]["rationale"]
        assert d["rule"]["fix"]
        assert d["suggestion"] == d["rule"]["fix"]

    def test_es_aggregate_with_event_not_flagged(self):
        domain = Domain(name="ESWithEvent", root_path=".")

        @domain.aggregate(event_sourced=True)
        class Account:
            balance = Float()

        @domain.event(part_of=Account)
        class Deposited:
            amount = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "ES_AGGREGATE_NO_EVENTS" not in codes

    def test_non_event_sourced_without_events_not_flagged(self):
        """The ``is_event_sourced`` guard fails first for a plain aggregate."""
        domain = Domain(name="NonESNoEvents", root_path=".")

        @domain.aggregate
        class Account:
            balance = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "ES_AGGREGATE_NO_EVENTS" not in codes

    def test_fact_events_do_not_count_as_domain_events(self):
        """The framework-generated ``FactEvent`` (``auto_generated``) lands in
        ``cluster["events"]`` but cannot reconstitute an ES aggregate by replay,
        so an ES aggregate with only fact events is still flagged."""
        domain = Domain(name="ESFactOnly", root_path=".")

        @domain.aggregate(event_sourced=True, fact_events=True)
        class Account:
            balance = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [d for d in ir["diagnostics"] if d["code"] == "ES_AGGREGATE_NO_EVENTS"]
        assert len(diags) == 1
        assert diags[0]["element"] == fqn(Account)

    def test_abstract_es_aggregate_not_flagged(self):
        """An abstract ``event_sourced=True`` aggregate with no events is skipped
        — the missing-events shape only exists on a non-instantiable base."""
        domain = Domain(name="ESAbstract", root_path=".")

        @domain.aggregate(event_sourced=True, abstract=True)
        class BaseAccount:
            balance = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "ES_AGGREGATE_NO_EVENTS" not in codes

    def test_infrastructure_aggregate_not_flagged(self):
        """A framework/infrastructure ES aggregate (FQN under
        ``protean.adapters.``) with no events is skipped. Deleting the
        ``protean.adapters.`` guard must fail this test."""
        domain = Domain(name="ESInfra", root_path=".")

        @domain.aggregate(event_sourced=True)
        class Account:
            balance = Float()

        # Masquerade as an infrastructure aggregate so its cluster FQN sits under
        # ``protean.adapters.`` (real adapter aggregates are internal and never
        # clustered, so this override is how the guard is reached).
        Account.__module__ = "protean.adapters.fake"

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "ES_AGGREGATE_NO_EVENTS" not in codes

    def test_suppress_checks_drops_code(self):
        domain = Domain(name="ESSuppress", root_path=".")

        @domain.aggregate(
            event_sourced=True, suppress_checks=["ES_AGGREGATE_NO_EVENTS"]
        )
        class Account:
            balance = Float()

        @domain.aggregate(event_sourced=True)
        class Ledger:
            balance = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Suppressed on Account, yet the identical shape on Ledger still fires.
        assert "ES_AGGREGATE_NO_EVENTS" not in _codes_for(ir, "Account")
        assert "ES_AGGREGATE_NO_EVENTS" in _codes_for(ir, "Ledger")


@pytest.mark.no_test_domain
class TestValueObjectMutableField:
    """VALUE_OBJECT_MUTABLE_FIELD flags a value object with a ``list``/``dict``
    field (mutable state breaks equality-by-value)."""

    def test_list_field_flagged(self):
        domain = Domain(name="VOList", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.value_object(part_of=Order)
        class ShippingLabel:
            carrier = String()
            tags = List()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [
            d for d in ir["diagnostics"] if d["code"] == "VALUE_OBJECT_MUTABLE_FIELD"
        ]
        assert len(diags) == 1
        d = diags[0]
        assert d["element"] == fqn(ShippingLabel)
        assert d["field"] == "tags"
        assert d["level"] == "warning"
        assert d["category"] == "aggregate_design"
        assert d["rule"]["rationale"]
        assert d["rule"]["fix"]
        assert d["suggestion"] == d["rule"]["fix"]

    def test_dict_field_flagged(self):
        domain = Domain(name="VODict", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.value_object(part_of=Order)
        class Metadata:
            label = String()
            attrs = Dict()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [
            d for d in ir["diagnostics"] if d["code"] == "VALUE_OBJECT_MUTABLE_FIELD"
        ]
        assert len(diags) == 1
        assert diags[0]["element"] == fqn(Metadata)
        assert diags[0]["field"] == "attrs"

    def test_scalar_only_vo_not_flagged(self):
        domain = Domain(name="VOScalar", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.value_object(part_of=Order)
        class Money:
            amount = Float()
            currency = String()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "VALUE_OBJECT_MUTABLE_FIELD" not in codes

    def test_abstract_aggregate_vo_not_flagged(self):
        """A mutable-field VO reachable only through an abstract aggregate is
        skipped along with its (non-instantiable) enclosing cluster."""
        domain = Domain(name="VOAbstract", root_path=".")

        @domain.aggregate(abstract=True)
        class BaseOrder:
            total = Float()

        @domain.value_object(part_of=BaseOrder)
        class ShippingLabel:
            carrier = String()
            tags = List()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "VALUE_OBJECT_MUTABLE_FIELD" not in codes

    def test_suppress_checks_drops_code(self):
        domain = Domain(name="VOSuppress", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        @domain.value_object(
            part_of=Order, suppress_checks=["VALUE_OBJECT_MUTABLE_FIELD"]
        )
        class ShippingLabel:
            carrier = String()
            tags = List()

        @domain.value_object(part_of=Order)
        class Manifest:
            ref = String()
            items = List()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Suppressed on ShippingLabel, yet the identical shape on Manifest still
        # fires: the rule is active and suppression is selective.
        assert "VALUE_OBJECT_MUTABLE_FIELD" not in _codes_for(ir, "ShippingLabel")
        assert "VALUE_OBJECT_MUTABLE_FIELD" in _codes_for(ir, "Manifest")


@pytest.mark.no_test_domain
class TestAggregateNoInvariants:
    """AGGREGATE_NO_INVARIANTS is an INFO-level nudge for an aggregate with no
    pre/post invariants; abstract aggregates are skipped."""

    def test_aggregate_without_invariants_flagged(self):
        domain = Domain(name="NoInvariants", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        diags = [d for d in ir["diagnostics"] if d["code"] == "AGGREGATE_NO_INVARIANTS"]
        assert len(diags) == 1
        d = diags[0]
        assert d["element"] == fqn(Order)
        assert d["level"] == "info"
        assert d["category"] == "aggregate_design"
        assert d["rule"]["rationale"]
        assert d["rule"]["fix"]
        assert d["suggestion"] == d["rule"]["fix"]

    def test_post_invariant_not_flagged(self):
        domain = Domain(name="PostInvariant", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

            @invariant.post
            def total_is_non_negative(self):
                if self.total is not None and self.total < 0:
                    raise ValidationError({"total": ["must be non-negative"]})

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "AGGREGATE_NO_INVARIANTS" not in codes

    def test_pre_invariant_not_flagged(self):
        domain = Domain(name="PreInvariant", root_path=".")

        @domain.aggregate
        class Order:
            total = Float()

            @invariant.pre
            def total_present(self):
                if self.total is None:
                    raise ValidationError({"total": ["is required"]})

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "AGGREGATE_NO_INVARIANTS" not in codes

    def test_abstract_aggregate_not_flagged(self):
        """``abstract`` is sourced from ``meta_`` via the registry; an abstract
        aggregate with no invariants is skipped before the invariants check."""
        domain = Domain(name="AbstractAgg", root_path=".")

        @domain.aggregate(abstract=True)
        class BaseThing:
            total = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        codes = [d["code"] for d in ir["diagnostics"]]
        assert "AGGREGATE_NO_INVARIANTS" not in codes

    def test_suppress_checks_drops_code(self):
        domain = Domain(name="NoInvariantsSuppress", root_path=".")

        @domain.aggregate(suppress_checks=["AGGREGATE_NO_INVARIANTS"])
        class Order:
            total = Float()

        @domain.aggregate
        class Shipment:
            weight = Float()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Suppressed on Order, yet the identical shape on Shipment still fires.
        assert "AGGREGATE_NO_INVARIANTS" not in _codes_for(ir, "Order")
        assert "AGGREGATE_NO_INVARIANTS" in _codes_for(ir, "Shipment")


# ── CIRCULAR_CLUSTER_DEPENDENCY ─────────────────────────────────────


def _circular_findings(ir: dict) -> list[dict]:
    return [d for d in ir["diagnostics"] if d["code"] == "CIRCULAR_CLUSTER_DEPENDENCY"]


@pytest.mark.no_test_domain
class TestCircularClusterDependency:
    """CIRCULAR_CLUSTER_DEPENDENCY flags aggregate clusters whose cross-cluster
    identity references form a directed cycle, and only those."""

    def test_two_cluster_cycle_flags_both(self):
        domain = Domain(name="TwoCycle", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)
            customer = Reference("Customer")

        @domain.aggregate
        class Customer:
            name = String(max_length=50)
            latest_order = Reference("Order")

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _circular_findings(ir)
        assert len(findings) == 2, "one diagnostic per participating cluster"
        assert sorted(d["element"] for d in findings) == sorted(
            [fqn(Order), fqn(Customer)]
        )
        for d in findings:
            assert d["level"] == "warning"
            assert d["category"] == "bounded_context"
            # The message names the whole mutually-dependent group.
            assert fqn(Order) in d["message"]
            assert fqn(Customer) in d["message"]
            assert d["element"] in d["message"]

    def test_three_cluster_cycle_is_deterministic(self):
        def build() -> dict:
            domain = Domain(name="ThreeCycle", root_path=".")

            @domain.aggregate
            class A:
                name = String(max_length=50)
                b = Reference("B")

            @domain.aggregate
            class B:
                name = String(max_length=50)
                c = Reference("C")

            @domain.aggregate
            class C:
                name = String(max_length=50)
                a = Reference("A")

            domain.init(traverse=False)
            return IRBuilder(domain).build()

        first = _circular_findings(build())
        assert len(first) == 3, "one diagnostic per cluster in the 3-cycle"

        # The reported chain is byte-identical across independent builds.
        second = _circular_findings(build())
        assert [d["message"] for d in first] == [d["message"] for d in second]

    def test_node_reachable_only_through_finalized_node_is_flagged(self):
        """SCC membership, not first-cycle discovery: in ``A->B, B->C, C->A,
        B->D, D->C`` every cluster is in one strongly-connected component
        (``D->C->A->B->D`` is a genuine cycle through ``D``). A plain DFS that
        only closes on an on-stack neighbour would miss ``D`` once ``C`` is
        finalized; SCC membership reports all four, each exactly once."""
        domain = Domain(name="SccReach", root_path=".")

        @domain.aggregate
        class A:
            name = String(max_length=50)
            b = Reference("B")

        @domain.aggregate
        class B:
            name = String(max_length=50)
            c = Reference("C")
            d = Reference("D")

        @domain.aggregate
        class C:
            name = String(max_length=50)
            a = Reference("A")

        @domain.aggregate
        class D:
            name = String(max_length=50)
            c = Reference("C")

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        findings = _circular_findings(ir)
        elements = [d["element"] for d in findings]
        assert sorted(elements) == sorted([fqn(A), fqn(B), fqn(C), fqn(D)])
        # Each cluster reported exactly once, no duplicates.
        assert len(elements) == len(set(elements))

    def test_cluster_on_two_cycles_is_reported_once(self):
        """A figure-eight — ``A<->B`` and ``A<->C`` — puts ``A`` on two distinct
        cycles. Frozenset-per-cycle dedup would emit ``A`` twice; SCC membership
        (all three are one component) emits each exactly once."""
        domain = Domain(name="FigureEight", root_path=".")

        @domain.aggregate
        class A:
            name = String(max_length=50)
            b = Reference("B")
            c = Reference("C")

        @domain.aggregate
        class B:
            name = String(max_length=50)
            a = Reference("A")

        @domain.aggregate
        class C:
            name = String(max_length=50)
            a = Reference("A")

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        elements = [d["element"] for d in _circular_findings(ir)]
        assert sorted(elements) == sorted([fqn(A), fqn(B), fqn(C)])
        assert elements.count(fqn(A)) == 1, "cluster on two cycles reported once"

    def test_two_disjoint_cycles_do_not_bleed(self):
        """Two independent 2-cycles plus an acyclic bridge: each cycle is its
        own component, the bridge cluster is in neither, so exactly the four
        cyclic clusters are flagged."""
        domain = Domain(name="TwoDisjoint", root_path=".")

        @domain.aggregate
        class A:
            name = String(max_length=50)
            b = Reference("B")

        @domain.aggregate
        class B:
            name = String(max_length=50)
            a = Reference("A")
            bridge = Reference("Bridge")

        @domain.aggregate
        class Bridge:
            name = String(max_length=50)
            c = Reference("C")

        @domain.aggregate
        class C:
            name = String(max_length=50)
            d = Reference("D")

        @domain.aggregate
        class D:
            name = String(max_length=50)
            c = Reference("C")

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        elements = [d["element"] for d in _circular_findings(ir)]
        assert sorted(elements) == sorted([fqn(A), fqn(B), fqn(C), fqn(D)])
        assert fqn(Bridge) not in elements, "acyclic bridge is not part of a cycle"

    def test_acyclic_chain_is_not_flagged(self):
        domain = Domain(name="Acyclic", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)
            customer = Reference("Customer")

        @domain.aggregate
        class Customer:
            name = String(max_length=50)
            region = Reference("Region")

        @domain.aggregate
        class Region:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _circular_findings(ir) == []

    def test_auto_generated_back_pointer_is_not_an_edge(self):
        """The false-edge guard: an entity declared with ``part_of`` gets an
        auto-generated Reference back at its own root, targeting the entity's
        own cluster FQN. ``target != cluster_fqn`` must drop it, so no self-loop
        cycle is reported."""
        domain = Domain(name="BackPointer", root_path=".")

        @domain.entity(part_of="Order")
        class LineItem:
            sku = String(max_length=50)

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _circular_findings(ir) == []

    def test_intra_cluster_explicit_reference_is_not_an_edge(self):
        """An entity holding an *explicit* Reference to its own aggregate root
        is intra-cluster (shares the root's FQN as its cluster), so it must not
        become a graph edge either."""
        domain = Domain(name="IntraRef", root_path=".")

        @domain.entity(part_of="Order")
        class LineItem:
            sku = String(max_length=50)
            parent = Reference("Order")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _circular_findings(ir) == []

    def test_per_element_suppression_removes_only_that_cluster(self):
        domain = Domain(name="CycleSuppress", root_path=".")

        @domain.aggregate(suppress_checks=["CIRCULAR_CLUSTER_DEPENDENCY"])
        class Order:
            name = String(max_length=50)
            customer = Reference("Customer")

        @domain.aggregate
        class Customer:
            name = String(max_length=50)
            latest_order = Reference("Order")

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        elements = [d["element"] for d in _circular_findings(ir)]
        assert fqn(Order) not in elements, "suppressed cluster is gone"
        assert elements == [fqn(Customer)], "the other cluster survives"


# ── INFRA_IMPORT_IN_DOMAIN ──────────────────────────────────────────


def _infra_findings(ir: dict) -> list[dict]:
    return [d for d in ir["diagnostics"] if d["code"] == "INFRA_IMPORT_IN_DOMAIN"]


def _build_infra_domain(name: str, lint: dict | None = None, **register_kwargs):
    """Register the infra-importing fixture aggregate (and its embedded value
    object) onto a fresh domain. ``register_kwargs`` flow to the aggregate."""
    domain = Domain(name=name, root_path=".")
    if lint is not None:
        domain.config["lint"] = lint
    domain.register(infra_import_domain.Money)
    domain.register(infra_import_domain.InfraOrder, **register_kwargs)
    domain.init(traverse=False)
    return domain


@pytest.mark.no_test_domain
class TestInfraImportInDomain:
    """INFRA_IMPORT_IN_DOMAIN (opt-in) flags domain elements whose source module
    imports from ``protean.adapters``."""

    def test_on_path_flags_infra_importing_aggregate(self):
        domain = _build_infra_domain("InfraOn", {"check_infra_imports": True})
        ir = IRBuilder(domain).build()

        agg_fqn = fqn(infra_import_domain.InfraOrder)
        agg = [d for d in _infra_findings(ir) if d["element"] == agg_fqn]
        assert len(agg) == 1
        d = agg[0]
        assert d["level"] == "warning"
        assert d["category"] == "bounded_context"
        assert infra_import_domain.InfraOrder.__module__ in d["message"]
        assert "protean.adapters" in d["message"]

    def test_emits_once_per_element_in_the_module(self):
        """The aggregate and the value object both live in the infra-importing
        module, so each is flagged with its own FQN."""
        domain = _build_infra_domain("InfraPerElement", {"check_infra_imports": True})
        ir = IRBuilder(domain).build()

        elements = sorted(d["element"] for d in _infra_findings(ir))
        assert elements == sorted(
            [
                fqn(infra_import_domain.InfraOrder),
                fqn(infra_import_domain.Money),
            ]
        )

    def test_default_off_emits_nothing(self):
        """With the flag absent the method returns immediately — no file is
        parsed, no diagnostic is emitted, even though the module does import
        infra."""
        domain = _build_infra_domain("InfraOff")
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_clean_domain_with_flag_on_is_not_flagged(self):
        """An element module importing only ``protean.fields`` (this test
        module) must not be flagged, even with the rule on — no over-flagging on
        legitimate framework imports."""
        domain = Domain(name="CleanInfra", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_per_element_suppression_removes_only_that_element(self):
        domain = _build_infra_domain(
            "InfraSuppress",
            {"check_infra_imports": True},
            suppress_checks=["INFRA_IMPORT_IN_DOMAIN"],
        )
        ir = IRBuilder(domain).build()

        elements = [d["element"] for d in _infra_findings(ir)]
        assert fqn(infra_import_domain.InfraOrder) not in elements
        # The value object in the same module is untouched by the aggregate's
        # per-element suppression.
        assert fqn(infra_import_domain.Money) in elements

    def test_suppressions_allow_list_grandfathers_first_n(self):
        """Two infra-importing elements with ``suppressions = {code: 1}`` leaves
        exactly one survivor — the deterministically-ranked tail."""
        domain = _build_infra_domain(
            "InfraAllowList",
            {
                "check_infra_imports": True,
                "suppressions": {"INFRA_IMPORT_IN_DOMAIN": 1},
            },
        )
        ir = IRBuilder(domain).build()

        survivors = [d["element"] for d in _infra_findings(ir)]
        assert len(survivors) == 1
        all_elements = sorted(
            [
                fqn(infra_import_domain.InfraOrder),
                fqn(infra_import_domain.Money),
            ]
        )
        # First in (code, element, ...) order is grandfathered; the tail lives.
        assert survivors == all_elements[1:]

    def test_non_cluster_element_is_scanned(self):
        """A repository is not an aggregate-cluster member, yet it lives in the
        infra-importing module. The scan covers *every* registered domain
        element, so the repository is flagged too — not just the aggregate and
        value object inside the cluster."""
        domain = _build_infra_domain("InfraRepo", {"check_infra_imports": True})
        domain.register(
            infra_import_domain.InfraOrderRepository,
            part_of=infra_import_domain.InfraOrder,
        )
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        elements = [d["element"] for d in _infra_findings(ir)]
        assert fqn(infra_import_domain.InfraOrderRepository) in elements

    def test_from_import_alias_form_is_detected(self):
        """``from protean import adapters`` (module ``protean``, alias
        ``adapters``) must be caught — the rule inspects imported alias names,
        not only ``ImportFrom.module``."""
        domain = Domain(name="InfraFromForm", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}
        domain.register(infra_from_import_domain.FromFormOrder)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        elements = [d["element"] for d in _infra_findings(ir)]
        assert fqn(infra_from_import_domain.FromFormOrder) in elements

    def test_guarded_and_lazy_imports_are_not_flagged(self):
        """An adapter import reachable only under ``TYPE_CHECKING`` or inside a
        method body introduces no module-level runtime coupling, so it must not
        be flagged — those are the idiomatic ways to avoid coupling."""
        domain = Domain(name="InfraGuarded", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}
        domain.register(infra_guarded_domain.GuardedOrder)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_unresolvable_module_fails_open(self):
        """When ``find_spec`` raises (e.g. a ``__module__`` whose parent is not a
        package), the rule fails open — the module is skipped, no diagnostic is
        emitted, and the diagnostics pass is not aborted."""
        domain = Domain(name="InfraUnresolvable", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}
        # ``os`` is a module, not a package, so ``find_spec('os.no_such_sub')``
        # raises ModuleNotFoundError.
        broken = type(
            "BrokenModuleVO",
            (BaseValueObject,),
            {"__module__": "os.no_such_sub", "amount": String(max_length=5)},
        )
        domain.register(broken)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_unparseable_source_fails_open(self, monkeypatch):
        """When a resolved source file cannot be AST-parsed, the rule fails open:
        the module is treated as not importing infra rather than crashing the
        build."""
        monkeypatch.setattr(
            "protean.ir.builder.ast.parse",
            lambda *a, **k: (_ for _ in ()).throw(SyntaxError("boom")),
        )
        domain = _build_infra_domain("InfraUnparseable", {"check_infra_imports": True})
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_duplicate_fqn_is_scanned_once(self):
        """Two distinct classes sharing a fully-qualified name (same module and
        name, different element buckets) are scanned once, not twice — the
        ``seen`` guard dedupes by FQN, so the infra-importing FQN is flagged a
        single time."""
        domain = Domain(name="InfraDup", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}
        module = infra_import_domain.__name__
        vo = type(
            "DupElement",
            (BaseValueObject,),
            {"__module__": module, "amount": String(max_length=5)},
        )
        agg = type(
            "DupElement",
            (BaseAggregate,),
            {"__module__": module, "name": String(max_length=5)},
        )
        domain.register(vo)
        domain.register(agg)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        dup_fqn = f"{module}.DupElement"
        assert [d["element"] for d in _infra_findings(ir)].count(dup_fqn) == 1

    def test_element_without_module_is_skipped(self):
        """An element whose ``__module__`` is empty contributes no source file to
        scan, so it is skipped without error."""
        domain = Domain(name="InfraNoModule", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}
        no_module = type(
            "NoModuleVO",
            (BaseValueObject,),
            {"__module__": "", "amount": String(max_length=5)},
        )
        domain.register(no_module)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []


# ── Handler completeness & flow fitness rules (3.5.4) ───────────────


def _findings(ir: dict, code: str) -> list[dict]:
    """Diagnostics carrying the given code."""
    return [d for d in ir["diagnostics"] if d["code"] == code]


@pytest.mark.no_test_domain
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


@pytest.mark.no_test_domain
class TestSubscriberNoStreams:
    """SUBSCRIBER_NO_STREAMS: a subscriber with no stream has nothing to
    consume. Keys off ``stream`` (not the removed ``stream_category``)."""

    def test_streamless_subscriber_flagged(self):
        domain = Domain(name="NoStreamSub", root_path=".")

        @domain.subscriber(broker="default", stream="payments")
        class PaymentSubscriber:
            def __call__(self, payload):
                pass

        domain.init(traverse=False)

        # The subscriber factory hard-requires a stream, so a streamless
        # subscriber cannot be registered. It can still appear in materialized
        # IR (loaded or hand-edited), which is what this info rule guards — null
        # the stream post-init to exercise that path.
        PaymentSubscriber.meta_.stream = None
        ir = IRBuilder(domain).build()

        findings = _findings(ir, "SUBSCRIBER_NO_STREAMS")
        assert len(findings) > 0
        finding = findings[0]
        assert "PaymentSubscriber" in finding["element"]
        assert finding["level"] == "info"

    def test_subscriber_with_stream_not_flagged(self):
        """A subscriber with a real ``stream`` produces zero findings — guards
        against a ``stream_category`` regression (the check reads ``stream``)."""
        domain = Domain(name="StreamSub", root_path=".")

        @domain.subscriber(broker="default", stream="payment_gateway")
        class PaymentSubscriber:
            def __call__(self, payload):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "SUBSCRIBER_NO_STREAMS") == []


@pytest.mark.no_test_domain
class TestProjectorHandlesOrphanedEvent:
    """PROJECTOR_HANDLES_ORPHANED_EVENT: a projector handling an event that no
    cluster registers is wired to a type that can never be dispatched."""

    def test_orphaned_event_flagged(self):
        domain = Domain(name="Orphan", root_path=".")

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

        # A live domain cannot wire a projector to an unregistered event (the
        # ``@handle`` decorator requires a registered event class). The orphan
        # the rule guards — a stale ``__type__`` left after a rename or removal —
        # appears only in materialized IR loaded from an older or hand-edited
        # source, so inject the ghost type into the handler map to exercise it.
        method = next(iter(OrderViewProjector._handlers[OrderPlaced.__type__]))
        OrderViewProjector._handlers["Orphan.RemovedEvent.v1"].add(method)

        ir = IRBuilder(domain).build()

        findings = _findings(ir, "PROJECTOR_HANDLES_ORPHANED_EVENT")
        assert len(findings) > 0
        finding = findings[0]
        assert "OrderViewProjector" in finding["element"]
        assert finding["level"] == "warning"
        # The orphaned type is named; the registered OrderPlaced is not flagged.
        assert "RemovedEvent" in finding["message"]
        assert not any("OrderPlaced" in f["message"] for f in findings)

    def test_internal_aggregate_event_not_flagged(self):
        """An ``internal`` aggregate is excluded from clusters, but its events
        are still registered and dispatchable — a projector handling one is not
        an orphan. The registered-type set must span all registered events, not
        just clustered ones."""
        from protean.core.aggregate import BaseAggregate

        domain = Domain(name="InternalEvt", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        class InternalTracker(BaseAggregate):
            name = String(max_length=50)

        @domain.event(part_of=InternalTracker)
        class TrackerFired:
            tracker_id = Identifier(identifier=True)

        domain.register(InternalTracker, internal=True)

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        @domain.projector(projector_for=OrderView, aggregates=[Order])
        class OrderViewProjector:
            @handle(TrackerFired)
            def on_tracker(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "PROJECTOR_HANDLES_ORPHANED_EVENT") == []

    def test_registered_events_not_flagged(self):
        domain = Domain(name="NoOrphan", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id = Identifier(identifier=True)

        @domain.event(part_of=Order)
        class OrderShipped:
            order_id = Identifier(identifier=True)

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        @domain.projector(projector_for=OrderView, aggregates=[Order])
        class OrderViewProjector:
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

            @handle(OrderShipped)
            def on_shipped(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "PROJECTOR_HANDLES_ORPHANED_EVENT") == []

    def test_cross_aggregate_registered_event_not_flagged(self):
        """A projector legitimately handles events from other aggregates; the
        registered-type lookup spans all clusters, so a foreign-but-registered
        event is not an orphan."""
        domain = Domain(name="CrossAgg", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.aggregate
        class Payment:
            name = String(max_length=50)

        @domain.event(part_of=Payment)
        class PaymentReceived:
            payment_id = Identifier(identifier=True)

        @domain.projection
        class OrderView:
            order_id = Identifier(identifier=True)

        @domain.projector(projector_for=OrderView, aggregates=[Order])
        class OrderViewProjector:
            @handle(PaymentReceived)
            def on_payment(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "PROJECTOR_HANDLES_ORPHANED_EVENT") == []


@pytest.mark.no_test_domain
class TestCommandHandlerCrossCluster:
    """COMMAND_HANDLER_CROSS_CLUSTER: a command handler processing another
    cluster's command puts that aggregate's write path outside its boundary."""

    def test_cross_cluster_command_flagged(self):
        domain = Domain(name="CrossCluster", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.aggregate
        class Shipment:
            name = String(max_length=50)

        @domain.command(part_of=Order)
        class PlaceOrder:
            order_id = Identifier(identifier=True)

        @domain.command(part_of=Shipment)
        class DispatchShipment:
            shipment_id = Identifier(identifier=True)

        @domain.command_handler(part_of=Order)
        class OrderCommandHandler:
            @handle(PlaceOrder)
            def place(self, command):
                pass

        domain.init(traverse=False)

        # The framework forbids a command handler from targeting another
        # cluster's command (handler_setup validates command/handler part_of
        # equality), so this cannot come from registration. It can appear in
        # materialized IR loaded from an older or hand-edited source — the state
        # the diagnostic guards — so inject the foreign command type into the
        # handler map to exercise that path.
        method = next(iter(OrderCommandHandler._handlers[PlaceOrder.__type__]))
        OrderCommandHandler._handlers[DispatchShipment.__type__].add(method)

        ir = IRBuilder(domain).build()

        findings = _findings(ir, "COMMAND_HANDLER_CROSS_CLUSTER")
        assert len(findings) > 0
        finding = findings[0]
        assert "OrderCommandHandler" in finding["element"]
        assert finding["level"] == "warning"
        # Pin the cluster *attribution*, not just any "Order"/"Shipment"
        # substring (the handler name and command type contain those already):
        # the message must name both distinct cluster FQNs — the handler's own
        # cluster and the command's owning cluster.
        order_cluster = next(k for k in ir["clusters"] if k.endswith(".Order"))
        shipment_cluster = next(k for k in ir["clusters"] if k.endswith(".Shipment"))
        assert order_cluster != shipment_cluster
        assert order_cluster in finding["message"]
        assert shipment_cluster in finding["message"]

    def test_same_cluster_command_not_flagged(self):
        domain = Domain(name="SameCluster", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.command(part_of=Order)
        class PlaceOrder:
            order_id = Identifier(identifier=True)

        @domain.command_handler(part_of=Order)
        class OrderCommandHandler:
            @handle(PlaceOrder)
            def place(self, command):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "COMMAND_HANDLER_CROSS_CLUSTER") == []

    def test_unregistered_command_type_skipped(self):
        """A command type in the handler map but registered in no cluster is
        attributable to no owner and must be skipped, not flagged."""
        domain = Domain(name="UnregisteredCmd", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.command(part_of=Order)
        class PlaceOrder:
            order_id = Identifier(identifier=True)

        @domain.command_handler(part_of=Order)
        class OrderCommandHandler:
            @handle(PlaceOrder)
            def place(self, command):
                pass

        domain.init(traverse=False)

        # Inject a command type owned by no registered cluster.
        method = next(iter(OrderCommandHandler._handlers[PlaceOrder.__type__]))
        OrderCommandHandler._handlers["Ghost.Unknown.v1"].add(method)

        ir = IRBuilder(domain).build()

        assert _findings(ir, "COMMAND_HANDLER_CROSS_CLUSTER") == []

    def test_cross_cluster_event_handler_not_flagged(self):
        """An event handler reacting across clusters is legitimate (the #824
        boundary); the command-only rule must ignore event handlers."""
        domain = Domain(name="EventCross", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.aggregate
        class Shipment:
            name = String(max_length=50)

        @domain.event(part_of=Shipment)
        class ShipmentDispatched:
            shipment_id = Identifier(identifier=True)

        @domain.event_handler(part_of=Order)
        class OrderReactsToShipment:
            @handle(ShipmentDispatched)
            def on_dispatched(self, event):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "COMMAND_HANDLER_CROSS_CLUSTER") == []


@pytest.mark.no_test_domain
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


@pytest.mark.no_test_domain
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
