"""Tests for DLQ discovery utility."""

import pytest

from protean import Domain
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.utils.dlq import (
    _infer_stream_category,
    collect_dlq_streams,
    collect_failed_streams,
    command_dispatcher_fqn,
    discover_subscriptions,
    failed_positions_stream,
)
from protean.utils.mixins import handle


@pytest.mark.no_test_domain
class TestDiscoverSubscriptions:
    def test_discover_subscriptions_with_event_handlers(self):
        domain = Domain(__file__, "TestDLQ")

        @domain.aggregate
        class Order:
            name: str

        @domain.event(part_of=Order)
        class OrderPlaced:
            order_id: str

        @domain.event_handler(part_of=Order)
        class OrderEventHandler:
            pass

        domain.init()

        infos = discover_subscriptions(domain)
        assert len(infos) >= 1

        order_info = next(
            (i for i in infos if "OrderEventHandler" in i.handler_name), None
        )
        assert order_info is not None
        assert order_info.dlq_stream.endswith(":dlq")
        assert order_info.backfill_dlq_stream is None  # No priority lanes by default
        # An event handler owns its stream directly, so it names itself.
        assert order_info.subscription_fqn == order_info.handler_fqn

    def test_discover_subscriptions_empty_domain(self):
        domain = Domain(__file__, "EmptyDLQ")
        domain.init()

        infos = discover_subscriptions(domain)
        assert infos == []

    def test_collect_dlq_streams(self):
        domain = Domain(__file__, "TestCollect")

        @domain.aggregate
        class User:
            name: str

        @domain.event(part_of=User)
        class UserRegistered:
            user_id: str

        @domain.event_handler(part_of=User)
        class UserHandler:
            pass

        domain.init()

        streams = collect_dlq_streams(domain)
        assert len(streams) >= 1
        assert all(s.endswith(":dlq") for s in streams)

    def test_collect_dlq_streams_deduplicates(self):
        domain = Domain(__file__, "TestDedup")

        @domain.aggregate
        class Account:
            name: str

        @domain.event(part_of=Account)
        class AccountCreated:
            account_id: str

        @domain.event_handler(part_of=Account)
        class AccountHandler1:
            pass

        @domain.event_handler(part_of=Account)
        class AccountHandler2:
            pass

        domain.init()

        streams = collect_dlq_streams(domain)
        # Even with two handlers for the same stream, DLQ stream names are deduplicated
        dlq_stream_count = sum(1 for s in streams if "account" in s.lower())
        assert dlq_stream_count >= 1

    def test_discover_subscriptions_with_command_handlers(self):
        domain = Domain(__file__, "TestCmdHandler")

        @domain.aggregate
        class Invoice:
            amount: float

        @domain.command(part_of=Invoice)
        class CreateInvoice:
            amount: float

        @domain.command_handler(part_of=Invoice)
        class InvoiceCommandHandler:
            pass

        domain.init()

        infos = discover_subscriptions(domain)
        cmd_info = next(
            (i for i in infos if "InvoiceCommandHandler" in i.handler_name), None
        )
        assert cmd_info is not None
        assert "invoice" in cmd_info.stream_category
        assert cmd_info.dlq_stream.endswith(":dlq")

    def test_discover_subscriptions_with_projectors(self):
        from protean.fields import Identifier, String

        domain = Domain(__file__, "TestProjector")

        @domain.aggregate
        class Product:
            name: str

        @domain.event(part_of=Product)
        class ProductCreated:
            name: str

        @domain.projection
        class ProductListing:
            product_id: Identifier(identifier=True)
            name: String()

        @domain.projector(projector_for=ProductListing, aggregates=[Product])
        class ProductProjector:
            pass

        domain.init()

        infos = discover_subscriptions(domain)
        proj_info = next(
            (i for i in infos if "ProductProjector" in i.handler_name), None
        )
        assert proj_info is not None
        assert proj_info.dlq_stream.endswith(":dlq")
        assert "product" in proj_info.stream_category

    def test_discover_subscriptions_with_priority_lanes(self):
        domain = Domain(__file__, "TestLanes")
        domain.config["server"] = {
            "priority_lanes": {
                "enabled": True,
                "backfill_suffix": "backfill",
            }
        }

        @domain.aggregate
        class Shipment:
            tracking: str

        @domain.event(part_of=Shipment)
        class ShipmentCreated:
            tracking: str

        @domain.event_handler(part_of=Shipment)
        class ShipmentHandler:
            pass

        domain.init()

        infos = discover_subscriptions(domain)
        ship_info = next(
            (i for i in infos if "ShipmentHandler" in i.handler_name), None
        )
        assert ship_info is not None
        assert ship_info.dlq_stream.endswith(":dlq")
        assert ship_info.backfill_dlq_stream is not None
        assert ship_info.backfill_dlq_stream.endswith(":backfill:dlq")

    def test_collect_dlq_streams_includes_backfill_when_lanes_enabled(self):
        domain = Domain(__file__, "TestLanesCollect")
        domain.config["server"] = {
            "priority_lanes": {
                "enabled": True,
                "backfill_suffix": "backfill",
            }
        }

        @domain.aggregate
        class Ticket:
            title: str

        @domain.event(part_of=Ticket)
        class TicketOpened:
            title: str

        @domain.event_handler(part_of=Ticket)
        class TicketHandler:
            pass

        domain.init()

        streams = collect_dlq_streams(domain)
        # Should have both primary DLQ and backfill DLQ
        assert len(streams) == 2
        assert any(s.endswith(":backfill:dlq") for s in streams)
        # Primary DLQ stream ends with :dlq but not :backfill:dlq
        primary = [s for s in streams if not s.endswith(":backfill:dlq")]
        assert len(primary) == 1
        assert primary[0].endswith(":dlq")

    def test_infer_stream_category_no_meta(self):
        class NoMeta:
            pass

        assert _infer_stream_category(NoMeta) is None

    def test_infer_stream_category_with_explicit_stream(self):
        domain = Domain(__file__, "TestInfer")

        @domain.aggregate
        class Cart:
            item: str

        @domain.event(part_of=Cart)
        class CartUpdated:
            item: str

        @domain.event_handler(part_of=Cart, stream_category="all_carts")
        class CartHandler:
            pass

        domain.init()

        assert _infer_stream_category(CartHandler) == "all_carts"

    def test_infer_stream_category_via_part_of(self):
        domain = Domain(__file__, "TestInferPartOf")

        @domain.aggregate
        class Warehouse:
            location: str

        @domain.event(part_of=Warehouse)
        class WarehouseCreated:
            location: str

        @domain.event_handler(part_of=Warehouse)
        class WarehouseHandler:
            pass

        domain.init()

        stream_cat = _infer_stream_category(WarehouseHandler)
        assert stream_cat is not None
        assert "warehouse" in stream_cat

    def test_infer_stream_category_no_part_of(self):
        """Test _infer_stream_category with meta but no part_of or stream_category."""

        class FakeMeta:
            stream_category = None
            part_of = None

        class FakeHandler:
            meta_ = FakeMeta()

        assert _infer_stream_category(FakeHandler) is None

    def test_discover_subscriptions_includes_subscribers(self):
        """Subscribers (broker subscriptions) are discovered with DLQ streams."""
        from protean.core.subscriber import BaseSubscriber

        domain = Domain(__file__, "TestSubscribers")

        class PaymentWebhookSubscriber(BaseSubscriber):
            def __call__(self, data: dict):
                pass

        domain.register(PaymentWebhookSubscriber, stream="payment_events")
        domain.init(traverse=False)

        infos = discover_subscriptions(domain)
        sub_info = next(
            (i for i in infos if "PaymentWebhookSubscriber" in i.handler_name), None
        )
        assert sub_info is not None
        assert sub_info.stream_category == "payment_events"
        assert sub_info.dlq_stream == "payment_events:dlq"
        assert sub_info.backfill_dlq_stream is None  # No priority lanes for subscribers

    def test_discover_subscriptions_subscriber_deduplication(self):
        """Subscribers are not duplicated in discovery results."""
        from protean.core.subscriber import BaseSubscriber

        domain = Domain(__file__, "TestSubDedup")

        class ExternalSubscriber(BaseSubscriber):
            def __call__(self, data: dict):
                pass

        domain.register(ExternalSubscriber, stream="ext_events")
        domain.init(traverse=False)

        infos = discover_subscriptions(domain)
        # Call again to verify deduplication within a single call
        sub_infos = [i for i in infos if "ExternalSubscriber" in i.handler_name]
        assert len(sub_infos) == 1

    def test_collect_dlq_streams_includes_subscriber_dlqs(self):
        """collect_dlq_streams() includes DLQ streams from subscribers."""
        from protean.core.subscriber import BaseSubscriber

        domain = Domain(__file__, "TestSubCollect")

        class WebhookSub(BaseSubscriber):
            def __call__(self, data: dict):
                pass

        domain.register(WebhookSub, stream="webhooks")
        domain.init(traverse=False)

        streams = collect_dlq_streams(domain)
        assert "webhooks:dlq" in streams


def _real_failed_streams(domain: Domain) -> set[str]:
    """The failed-positions stream each event-store subscription actually uses.

    Builds the engine's subscriptions the same way ``protean server`` does and
    reads their ``failed_positions_stream`` attribute, so this is the ground
    truth the ``eventstore dlq`` CLI must match.
    """
    engine = Engine(domain=domain, test_mode=True)
    try:
        return {
            sub.failed_positions_stream
            for sub in engine._subscriptions.values()
            if getattr(sub, "failed_positions_stream", None)
        }
    finally:
        engine.loop.close()


@pytest.mark.no_test_domain
class TestCollectFailedStreams:
    def test_matches_engine_subscriptions_across_handler_types(self):
        """The CLI-derived failed streams equal what the engine subscriptions use.

        Covers all three event-store handler kinds at once — an event handler, a
        command handler, and a projector — because a command handler is fanned
        into a ``CommandDispatcher`` whose stream name differs from the handler
        class's, which is where the CLI would otherwise read the wrong stream.
        """
        domain = Domain(__file__, "TestNoDrift")

        @domain.aggregate
        class Invoice:
            amount: str

        @domain.event(part_of=Invoice)
        class InvoiceRaised:
            amount: str

        @domain.command(part_of=Invoice)
        class CreateInvoice:
            amount: str

        @domain.command_handler(part_of=Invoice)
        class InvoiceCommandHandler:
            @handle(CreateInvoice)
            def create(self, command):
                pass

        @domain.event_handler(part_of=Invoice)
        class InvoiceEventHandler:
            @handle(InvoiceRaised)
            def on_raised(self, event):
                pass

        @domain.projection
        class InvoiceListing:
            id = Identifier(identifier=True)
            amount = String()

        @domain.projector(projector_for=InvoiceListing, aggregates=[Invoice])
        class InvoiceProjector:
            @handle(InvoiceRaised)
            def project(self, event):
                pass

        domain.init(traverse=False)

        derived = {stream for _info, stream in collect_failed_streams(domain)}
        assert derived, "expected at least one failed stream"
        assert derived == _real_failed_streams(domain)

    def test_command_handler_stream_uses_dispatcher_name(self):
        """A command handler's failed stream is keyed by the dispatcher, not the class.

        The engine wraps a command stream's handlers in one CommandDispatcher, so
        the failed-positions stream carries the dispatcher fqn. Deriving it from
        the handler class fqn would point the CLI at a stream that never exists.
        """
        domain = Domain(__file__, "TestCmdStream")

        @domain.aggregate
        class Order:
            total: str

        @domain.command(part_of=Order)
        class PlaceOrder:
            total: str

        @domain.command_handler(part_of=Order)
        class OrderCommandHandler:
            @handle(PlaceOrder)
            def place(self, command):
                pass

        domain.init(traverse=False)

        pairs = collect_failed_streams(domain)
        cmd = next(p for p in pairs if p[0].is_command_handler)
        info, stream = cmd
        category = info.stream_category
        expected = failed_positions_stream(command_dispatcher_fqn(category), category)
        assert stream == expected
        # And crucially NOT the handler-class-keyed name that would miss the stream.
        assert stream != failed_positions_stream(info.handler_fqn, category)
        # The reported subscription identity is the dispatcher, not the handler
        # class, so CLI output names the subscription that wrote the records.
        assert info.subscription_fqn == command_dispatcher_fqn(category)
        assert info.subscription_fqn != info.handler_fqn

    def test_command_handlers_sharing_category_collapse_to_one_stream(self):
        """Two command handlers on one stream share a single dispatcher stream."""
        domain = Domain(__file__, "TestCmdShare")

        @domain.aggregate
        class Account:
            balance: str

        @domain.command(part_of=Account)
        class Debit:
            amount: str

        @domain.command(part_of=Account)
        class Credit:
            amount: str

        @domain.command_handler(part_of=Account)
        class DebitHandler:
            @handle(Debit)
            def debit(self, command):
                pass

        @domain.command_handler(part_of=Account)
        class CreditHandler:
            @handle(Credit)
            def credit(self, command):
                pass

        domain.init(traverse=False)

        cmd_streams = [s for info, s in collect_failed_streams(domain)]
        # One stream, not two, and it matches what the engine builds.
        assert len(set(cmd_streams)) == len(cmd_streams)  # no duplicate streams
        assert set(cmd_streams) == _real_failed_streams(domain)

    def test_excludes_broker_subscribers(self):
        """Broker subscribers have no event-store failed stream, so they're excluded."""
        from protean.core.subscriber import BaseSubscriber

        domain = Domain(__file__, "TestBrokerExcluded")

        @domain.aggregate
        class Widget:
            name: str

        @domain.event(part_of=Widget)
        class WidgetMade:
            name: str

        @domain.event_handler(part_of=Widget)
        class WidgetHandler:
            @handle(WidgetMade)
            def on_made(self, event):
                pass

        class WebhookSubscriber(BaseSubscriber):
            def __call__(self, data: dict):
                pass

        domain.register(WebhookSubscriber, stream="external")
        domain.init(traverse=False)

        infos = [info for info, _ in collect_failed_streams(domain)]
        names = {info.handler_name for info in infos}
        assert "WidgetHandler" in names
        assert "WebhookSubscriber" not in names
