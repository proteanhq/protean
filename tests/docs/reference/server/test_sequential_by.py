"""The examples on ``docs/reference/server/sequential-by.md`` behave as the page says."""

import re

import pytest

from protean import handle
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import Identifier
from protean.port.broker import BrokerCapabilities
from protean.server import Engine
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
)
from protean.server.subscription.partitioned_stream_subscription import (
    PartitionedStreamSubscription,
)
from tests.docs.support import load_example
from tests.shared import REDIS_URI

pytestmark = pytest.mark.no_test_domain


def test_each_handler_kind_keeps_its_sequential_by():
    example = load_example("reference/server/sequential-by/001.py")
    example.domain.init(traverse=False)

    assert example.OrderEventHandler.meta_.sequential_by == "client_id"
    assert example.ProductSummaryProjector.meta_.sequential_by == "product_id"
    assert example.OrderFulfillment.meta_.sequential_by is True


def test_each_category_is_partitioned_by_the_key_its_handler_names():
    example = load_example("reference/server/sequential-by/001.py")
    example.domain.init(traverse=False)

    assert example.domain._partition_keys == {
        "shop::order": "client_id",
        "shop::product": "product_id",
        # The process manager's ``correlate="order_id"`` field.
        "shop::payment": "order_id",
    }


def test_the_inline_broker_keeps_an_ordinary_subscription():
    example = load_example("reference/server/sequential-by/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        engine = Engine(example.domain, test_mode=True)

    module = example.OrderFulfillment.__module__
    # No ``-partitioned`` subscription: under the inline broker the process
    # manager gets one plain subscription per category.
    assert f"{module}.OrderFulfillment-partitioned" not in engine.subscriptions
    assert isinstance(
        engine.subscriptions[f"{module}.OrderFulfillment-shop::payment"],
        EventStoreSubscription,
    )


def test_a_key_the_event_does_not_carry_fails_at_init():
    example = load_example("reference/server/sequential-by/001.py")
    example.OrderEventHandler.meta_.sequential_by = "region"

    with pytest.raises(
        IncorrectUsageError,
        match="Event `OrderPlaced` has no field named `region`",
    ):
        example.domain.init(traverse=False)


def test_a_process_manager_event_without_its_correlate_field_fails_at_init():
    example = load_example("reference/server/sequential-by/001.py")

    @example.domain.event(part_of=example.Payment)
    class PaymentRefunded:
        payment_id = Identifier(required=True)

    @example.domain.process_manager(sequential_by=True)
    class Refunds:
        payment_id = Identifier(identifier=True)

        @handle(PaymentRefunded, start=True, correlate="order_id")
        def on_refunded(self, event: PaymentRefunded) -> None: ...

    with pytest.raises(
        IncorrectUsageError,
        match="Event `PaymentRefunded` has no field named `order_id`",
    ):
        example.domain.init(traverse=False)


def test_two_keys_on_one_category_fail_at_init():
    example = load_example("reference/server/sequential-by/001.py")

    # The clash the page names: the ``client_id`` handler and a process manager
    # that correlates ``OrderPlaced`` by ``order_id``.
    @example.domain.process_manager(sequential_by=True)
    class OrderTracking:
        order_id = Identifier(identifier=True)

        @handle(example.OrderPlaced, start=True, correlate="order_id")
        def on_placed(self, event) -> None: ...

    with pytest.raises(
        IncorrectUsageError,
        match="`shop::order` is partitioned by conflicting keys",
    ):
        example.domain.init(traverse=False)


def test_the_boolean_form_is_rejected_on_an_event_handler():
    example = load_example("reference/server/sequential-by/001.py")
    example.OrderEventHandler.meta_.sequential_by = True

    with pytest.raises(IncorrectUsageError, match="for process managers only"):
        example.domain.init(traverse=False)


def test_a_broker_without_partitioning_is_rejected_at_init():
    example = load_example("reference/server/sequential-by/001.py")
    # Redis PubSub advertises only SIMPLE_QUEUING. Building it does not
    # connect, so init() reaches the capability check without a live server.
    example.domain.config["brokers"]["default"] = {
        "provider": "redis_pubsub",
        "URI": f"{REDIS_URI}/9",
    }

    with pytest.raises(
        IncorrectUsageError, match="does not advertise STREAM_PARTITIONING"
    ):
        example.domain.init(traverse=False)


@pytest.mark.redis
def test_the_redis_broker_builds_partitioned_subscriptions():
    example = load_example("reference/server/sequential-by/001.py")
    example.domain.config["brokers"]["default"] = {
        "provider": "redis",
        "URI": f"{REDIS_URI}/9",
    }
    example.domain.config["server"]["default_subscription_type"] = "stream"
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        broker = example.domain.brokers["default"]
        assert broker.has_capability(BrokerCapabilities.STREAM_PARTITIONING)
        engine = Engine(example.domain, test_mode=True)

    module = example.OrderEventHandler.__module__
    for key in (
        f"{module}.OrderEventHandler",
        f"{module}.ProductSummaryProjector-shop::product",
    ):
        assert isinstance(engine.subscriptions[key], PartitionedStreamSubscription)
    # The process manager gets one partitioned subscription across its
    # categories in place of one per category.
    assert isinstance(
        engine.subscriptions[f"{module}.OrderFulfillment-partitioned"],
        PartitionedStreamSubscription,
    )
    assert f"{module}.OrderFulfillment-shop::payment" not in engine.subscriptions


@pytest.mark.parametrize(
    "client_id, reason",
    [
        ("", "null or empty"),
        ("acme:eu", "contains a colon"),
        ("dlq", "reserved lane/DLQ token"),
        ("backfill", "reserved lane/DLQ token"),
        ("__partitions__", "reserved '__name__' sentinel form"),
    ],
)
def test_a_rejected_key_fails_the_callers_commit(client_id, reason):
    example = load_example("reference/server/sequential-by/001.py")
    example.domain.config["enable_outbox"] = True
    example.domain.config["server"]["default_subscription_type"] = "stream"
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(client_id="c-1", total=10.0)
        order.raise_(
            example.OrderPlaced(order_id=order.id, client_id="c-1", total=10.0)
        )
        # Set after raising: an empty value would fail the event's
        # required-field check before the key check ran.
        object.__setattr__(order._events[-1], "client_id", client_id)

        with pytest.raises(ValidationError, match=re.escape(reason)):
            example.domain.repository_for(example.Order).add(order)

        outbox = example.domain._get_outbox_repo("default")
        assert outbox.find_unprocessed() == []


def test_a_valid_key_reaches_the_outbox_with_its_partition_key():
    example = load_example("reference/server/sequential-by/001.py")
    example.domain.config["enable_outbox"] = True
    example.domain.config["server"]["default_subscription_type"] = "stream"
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(client_id="acme", total=10.0)
        order.raise_(
            example.OrderPlaced(order_id=order.id, client_id="acme", total=10.0)
        )
        example.domain.repository_for(example.Order).add(order)

        rows = example.domain._get_outbox_repo("default").find_unprocessed()
        assert [row.partition_key for row in rows] == ["acme"]
