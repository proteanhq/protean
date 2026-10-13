"""The examples on ``docs/reference/server/subscription-types.md`` behave as the page says."""

import logging

import pytest

from protean.exceptions import ConfigurationError
from protean.server import Engine
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
)
from protean.server.subscription.stream_subscription import StreamSubscription
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

STREAM = "shop::order"


@pytest.fixture
def example():
    module = load_example("reference/server/subscription-types/001.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


@pytest.fixture
def engine(example):
    return Engine(example.domain, test_mode=True)


def test_retries_example_builds_a_stream_subscription_with_its_retry_settings(
    example, engine
):
    subscription = engine.subscription_factory.create_subscription(
        handler=example.RetryingHandler, stream_category=STREAM
    )

    assert isinstance(subscription, StreamSubscription)
    assert subscription.max_retries == 3
    assert subscription.retry_delay_seconds == 1
    assert subscription.dlq_stream == f"{STREAM}:dlq"


def test_stream_config_example_builds_a_stream_subscription(example, engine):
    subscription = engine.subscription_factory.create_subscription(
        handler=example.StreamHandler, stream_category=STREAM
    )

    assert isinstance(subscription, StreamSubscription)
    assert subscription.messages_per_tick == 100
    assert subscription.blocking_timeout_ms == 5000
    assert subscription.max_retries == 3
    assert subscription.retry_delay_seconds == 1
    assert subscription.enable_dlq is True


def test_production_profile_selects_a_stream_subscription(example, engine):
    subscription = engine.subscription_factory.create_subscription(
        handler=example.ProductionHandler, stream_category=STREAM
    )

    assert isinstance(subscription, StreamSubscription)
    # The production profile's own values, not the hardcoded defaults.
    assert subscription.messages_per_tick == 100
    assert subscription.retention_maxlen == 100_000


def test_event_store_config_example_builds_an_event_store_subscription(example, engine):
    # The last ``OrderEventHandler`` on the page is the one left registered, so
    # the engine itself built this subscription.
    subscription = engine.subscriptions[
        f"{example.EventStoreHandler.__module__}.OrderEventHandler"
    ]

    assert subscription.handler is example.EventStoreHandler
    assert isinstance(subscription, EventStoreSubscription)
    assert subscription.messages_per_tick == 100
    assert subscription.tick_interval == 1
    assert subscription.position_update_interval == 10


def test_projection_profile_selects_an_event_store_subscription(example, engine):
    key = f"{example.OrderProjector.__module__}.OrderProjector-{STREAM}"

    assert isinstance(engine.subscriptions[key], EventStoreSubscription)


def test_source_stream_becomes_the_event_store_origin_filter(example, engine):
    subscription = engine.subscription_factory.create_subscription(
        handler=example.OriginFilteredHandler, stream_category=STREAM
    )

    assert isinstance(subscription, EventStoreSubscription)
    assert subscription.origin_stream == "manage_order"


def test_position_is_stored_as_a_read_message_on_the_position_stream(example, engine):
    for total in (10.0, 20.0, 30.0):
        example.place_order(total)
    engine.run()

    handler_name = f"{example.EventStoreHandler.__module__}.OrderEventHandler"
    stream_category = STREAM
    records = example.domain.event_store.store._read(
        f"position-{handler_name}-{stream_category}"
    )

    assert records[-1]["data"] == {"position": 3}
    assert records[-1]["metadata"]["headers"]["type"] == "Read"
    assert records[-1]["metadata"]["domain"]["kind"] == "READ_POSITION"
    assert records[-1]["metadata"]["domain"]["origin_stream"] == STREAM


def test_the_internal_reads_accept_the_arguments_the_page_shows(example):
    example.place_order(10.0)

    # The inline broker has no blocking read, so ``read_blocking`` falls back to
    # a plain read. This checks the call shape, not the blocking.
    broker = example.domain.brokers["default"]
    assert (
        broker.read_blocking(
            stream=STREAM,
            consumer_group="OrderEventHandler",
            consumer_name="order-handler-1",
            timeout_ms=5000,
            count=100,
        )
        == []
    )

    messages = example.domain.event_store.store.read(
        STREAM, position=0, no_of_messages=10
    )
    assert [m.metadata.headers.type for m in messages] == ["Shop.OrderPlaced.v1"]


def test_dlq_message_carries_the_metadata_the_page_lists(example, engine):
    subscription = engine.subscription_factory.create_subscription(
        handler=example.StreamHandler, stream_category=STREAM
    )

    dlq_message = subscription._create_dlq_message(
        "1234567890-0", {"metadata": {"headers": {"time": "2024-01-15T10:30:00Z"}}}
    )

    assert set(dlq_message["_dlq_metadata"]) == {
        "original_stream",
        "original_id",
        "consumer_group",
        "consumer",
        "failed_at",
        "retry_count",
    }
    assert dlq_message["_dlq_metadata"]["original_stream"] == STREAM
    assert dlq_message["_dlq_metadata"]["retry_count"] == 3


def test_event_store_subscription_warns_in_production(
    example, engine, monkeypatch, caplog
):
    monkeypatch.setenv("PROTEAN_ENV", "production")

    with caplog.at_level(logging.WARNING):
        engine.subscription_factory.create_subscription(
            handler=example.EventStoreHandler, stream_category=STREAM
        )

    assert "EventStoreSubscription is being used in production" in caplog.text


def test_an_unknown_profile_is_rejected(example, engine):
    @example.domain.event_handler(part_of=example.Order, subscription_profile="nope")
    class UnknownProfileHandler: ...

    with pytest.raises(ConfigurationError, match="Unknown subscription profile 'nope'"):
        engine.subscription_factory.create_subscription(
            handler=UnknownProfileHandler, stream_category=STREAM
        )


def test_a_blocking_timeout_that_is_not_positive_is_rejected(example, engine):
    @example.domain.event_handler(
        part_of=example.Order,
        subscription_type="stream",
        subscription_config={"blocking_timeout_ms": 0},
    )
    class NoPauseHandler: ...

    with pytest.raises(
        ConfigurationError, match="blocking_timeout_ms must be positive"
    ):
        engine.subscription_factory.create_subscription(
            handler=NoPauseHandler, stream_category=STREAM
        )
