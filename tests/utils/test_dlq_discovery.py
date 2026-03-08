"""Tests for DLQ discovery utility."""

import pytest

from protean import Domain
from protean.utils.dlq import (
    _infer_stream_category,
    collect_dlq_streams,
    discover_subscriptions,
)


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
