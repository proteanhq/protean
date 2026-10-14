"""The examples on ``docs/concepts/async-processing/subscriptions.md`` behave as the page says."""

import pytest

from protean.fields import Identifier
from protean.server import Engine
from protean.server.subscription.broker_subscription import BrokerSubscription
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
)
from protean.utils import fqn
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _init(example):
    example.domain.init(traverse=False)
    return example.domain.domain_context()


def _run_engine(domain):
    engine = Engine(domain, test_mode=True)
    engine.run()
    return engine


def _last_position(domain):
    """Return the event store position of the last stored message."""
    message = domain.event_store.store.read("$all")[-1]
    return message.metadata.event_store.global_position


# Broker subscriptions


def test_the_subscriber_gets_a_broker_subscription_on_its_stream():
    example = load_example("concepts/async-processing/subscriptions/001.py")
    with _init(example):
        engine = Engine(example.domain, test_mode=True)
        try:
            subscription = engine._broker_subscriptions[
                fqn(example.ExternalOrderSubscriber)
            ]
        finally:
            engine.loop.close()

        assert isinstance(subscription, BrokerSubscription)
        assert subscription.stream_name == "external_orders"
        assert subscription.broker is example.domain.brokers["default"]


def test_the_subscriber_consumes_a_message_from_the_broker():
    example = load_example("concepts/async-processing/subscriptions/001.py")
    with _init(example):
        broker = example.domain.brokers["default"]
        broker.publish("external_orders", {"order_id": "ext-1"})
        group = fqn(example.ExternalOrderSubscriber)

        _run_engine(example.domain)

        # The subscriber's consumer group has read and acknowledged the
        # message, so nothing is left for it. A new group still sees it.
        assert broker.read("external_orders", group, 10) == []
        ((_, payload),) = broker.read("external_orders", "another-group", 10)
        assert payload["order_id"] == "ext-1"


# Handler subscriptions and stream categories


def test_the_engine_subscribes_the_handler_to_the_order_category():
    example = load_example("concepts/async-processing/subscriptions/002.py")
    with _init(example):
        engine = Engine(example.domain, test_mode=True)
        try:
            subscription = engine.subscriptions[fqn(example.OrderEventHandler)]
        finally:
            engine.loop.close()

        assert isinstance(subscription, EventStoreSubscription)
        assert subscription.handler is example.OrderEventHandler
        assert subscription.stream_category == "ecommerce::order"


def test_the_default_category_comes_from_the_aggregate():
    example = load_example("concepts/async-processing/subscriptions/003.py")
    with _init(example):
        assert example.Order.meta_.stream_category == "ecommerce::order"
        assert example.OrderEventHandler.meta_.stream_category == "ecommerce::order"


def test_the_report_handler_reads_the_all_orders_category():
    example = load_example("concepts/async-processing/subscriptions/002.py")

    @example.domain.aggregate(stream_category="all_orders")
    class Return: ...

    @example.domain.event(part_of=Return)
    class ReturnRequested:
        return_id = Identifier(required=True)

    @example.domain.event(part_of=example.Order)
    class OrderPlaced:
        order_id = Identifier(required=True)

    with _init(example):
        returned = Return()
        returned.raise_(ReturnRequested(return_id=returned.id))
        example.domain.repository_for(Return).add(returned)
        requested_at = _last_position(example.domain)

        order = example.Order()
        order.raise_(OrderPlaced(order_id=order.id))
        example.domain.repository_for(example.Order).add(order)
        placed_at = _last_position(example.domain)

        engine = _run_engine(example.domain)

        report = engine.subscriptions[fqn(example.OrderReportHandler)]
        handler = engine.subscriptions[fqn(example.OrderEventHandler)]
        assert report.stream_category == "all_orders"
        # Each subscription tracks its position in its own category only.
        assert report.current_position == requested_at
        assert handler.current_position == placed_at


# Cross-aggregate coordination


def test_the_order_handler_reduces_stock_through_the_command():
    example = load_example("concepts/async-processing/subscriptions/004.py")
    with _init(example):
        inventory = example.Inventory(product_id="book-1", in_stock=100)
        example.domain.repository_for(example.Inventory).add(inventory)
        order = example.Order(product_id="book-1", quantity=10)
        order.ship()
        example.domain.repository_for(example.Order).add(order)

        engine = _run_engine(example.domain)

        assert (
            engine.subscriptions[fqn(example.OrderEventHandler)].stream_category
            == "ecommerce::order"
        )
        inventory = example.domain.repository_for(example.Inventory).get("book-1")
        assert inventory.in_stock == 90
        assert inventory.applied_order_ids == [order.id]


def test_a_repeated_command_for_the_same_order_is_skipped():
    example = load_example("concepts/async-processing/subscriptions/004.py")
    with _init(example):
        inventory = example.Inventory(product_id="book-1", in_stock=100)
        example.domain.repository_for(example.Inventory).add(inventory)
        command = example.ReduceStock(
            order_id="order-1", product_id="book-1", quantity=10
        )
        example.domain.process(command, asynchronous=False)
        example.domain.process(command, asynchronous=False)

        inventory = example.domain.repository_for(example.Inventory).get("book-1")
        assert inventory.in_stock == 90
