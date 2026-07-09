"""Tests for the event-store single-writer guard helpers.

``event_store_subscription_handlers`` powers the ``protean server --workers
N>1`` refuse-to-start guard: it returns the handlers whose subscriptions
resolve to the (single-writer) event-store type. The negative cases matter as
much as the positive one — a false positive would break legitimate stream/broker
multi-worker deployments.
"""

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.fields import Identifier, String
from protean.server.subscription import (
    event_store_multi_worker_error,
    event_store_subscription_handlers,
)
from protean.server.subscription.profiles import SubscriptionType
from protean.utils.mixins import handle


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    name = String()


class OrderPlaced(BaseEvent):
    order_id = Identifier()
    name = String()


class TestEventStoreSubscriptionHandlers:
    def test_detects_event_store_handler(self, test_domain):
        """A handler resolving to EVENT_STORE is reported by name."""

        @test_domain.event_handler(
            part_of=Order, subscription_type=SubscriptionType.EVENT_STORE
        )
        class OrderEventHandler(BaseEventHandler):
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        offenders = event_store_subscription_handlers(test_domain)
        assert offenders == ["OrderEventHandler"]

    def test_detects_event_store_via_server_default(self, test_domain):
        """Server-level default_subscription_type = event_store is detected."""
        test_domain.config["server"]["default_subscription_type"] = "event_store"

        @test_domain.event_handler(part_of=Order)
        class OrderEventHandler(BaseEventHandler):
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        offenders = event_store_subscription_handlers(test_domain)
        assert offenders == ["OrderEventHandler"]

    def test_stream_handler_not_reported(self, test_domain):
        """A stream-resolved handler is not reported — the negative case."""
        test_domain.config["server"]["default_subscription_type"] = "stream"

        @test_domain.event_handler(part_of=Order)
        class OrderEventHandler(BaseEventHandler):
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.init(traverse=False)

        assert event_store_subscription_handlers(test_domain) == []

    def test_broker_subscriber_only_domain_is_empty(self, test_domain):
        """Broker subscribers use a multi-worker-safe path and are excluded."""

        @test_domain.subscriber(stream="orders")
        class OrderSubscriber(BaseSubscriber):
            def __call__(self, data):
                pass

        test_domain.register(Order)
        test_domain.init(traverse=False)

        assert event_store_subscription_handlers(test_domain) == []

    def test_empty_domain_is_empty(self, test_domain):
        """A domain with no handlers reports no offenders."""
        test_domain.register(Order)
        test_domain.init(traverse=False)

        assert event_store_subscription_handlers(test_domain) == []


class TestEventStoreMultiWorkerError:
    def test_message_names_handlers_and_worker_count(self):
        message = event_store_multi_worker_error(["HandlerA", "HandlerB"], 4)

        assert "4 workers" in message
        assert "- HandlerA" in message
        assert "- HandlerB" in message

    def test_message_lists_the_three_ways_forward(self):
        message = event_store_multi_worker_error(["HandlerA"], 2)

        assert "single worker" in message
        assert 'subscription_type = "stream"' in message
        assert "--acknowledge-event-store-risk" in message
