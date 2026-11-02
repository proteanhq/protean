"""Tests for how a BrokerSubscription reads, hands over and settles broker messages.

Each test publishes real messages to the inline broker and lets a
``BrokerSubscription`` consume them with real subscribers.
"""

import asyncio
import logging
import time

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.domain import Processing
from protean.server import Engine
from protean.server.subscription.broker_subscription import BrokerSubscription

received: list[dict] = []


class RecordingSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        received.append(data)


class FailingSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        raise Exception("Test exception")


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    # Publishing must only store the message, so the subscription under test
    # is the one that delivers it.
    test_domain.config["message_processing"] = Processing.ASYNC.value
    test_domain.register(RecordingSubscriber, stream="test_stream")
    test_domain.register(FailingSubscriber, stream="fail_stream")
    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def clear_received():
    yield
    received.clear()


@pytest.fixture
def engine(test_domain):
    return Engine(test_domain, test_mode=True)


@pytest.fixture
def broker(test_domain):
    return test_domain.brokers["default"]


@pytest.fixture
def recording_subscription(engine, broker):
    return BrokerSubscription(engine, broker, "test_stream", RecordingSubscriber)


@pytest.fixture
def failing_subscription(engine, broker):
    return BrokerSubscription(
        engine,
        broker,
        "fail_stream",
        FailingSubscriber,
        max_retries=3,
        # Retry at once, so the test spends no time in the retry delay.
        retry_delay_seconds=0,
    )


async def wait_until(predicate, timeout: float = 2.0) -> None:
    """Yield to the event loop until ``predicate()`` is true, or fail."""
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not met before timeout"
        await asyncio.sleep(0.001)


async def test_poll_stops_after_the_subscription_shuts_down(recording_subscription):
    """``poll()`` returns once ``shutdown()`` asks the subscription to stop."""
    poll_task = asyncio.create_task(recording_subscription.poll())
    await wait_until(lambda: recording_subscription.last_idle_tick_started is not None)

    await recording_subscription.shutdown()
    await asyncio.wait_for(poll_task, timeout=1.0)

    assert recording_subscription.keep_going is False


async def test_poll_stops_when_the_engine_shuts_down(engine, recording_subscription):
    """``poll()`` returns once the engine is shutting down."""
    poll_task = asyncio.create_task(recording_subscription.poll())
    await wait_until(lambda: recording_subscription.last_idle_tick_started is not None)

    engine.shutting_down = True
    await asyncio.wait_for(poll_task, timeout=1.0)


async def test_poll_in_test_mode_delivers_a_message_published_after_it_started(
    engine, broker
):
    """In test mode the poll loop ignores a long ``tick_interval`` and picks up
    a message published after its first empty tick."""
    subscription = BrokerSubscription(
        engine, broker, "test_stream", RecordingSubscriber, tick_interval=60
    )
    poll_task = asyncio.create_task(subscription.poll())
    await wait_until(lambda: subscription.last_idle_tick_started is not None)

    broker.publish("test_stream", {"data": "late"})
    await wait_until(lambda: received == [{"data": "late"}])

    await subscription.shutdown()
    await asyncio.wait_for(poll_task, timeout=1.0)
    assert received == [{"data": "late"}]


async def test_tick_on_an_empty_stream_delivers_nothing(recording_subscription):
    """``tick()`` returns False and calls no subscriber when the stream is empty."""
    had_work = await recording_subscription.tick()

    assert had_work is False
    assert received == []


async def test_tick_delivers_each_published_message_to_the_subscriber(
    broker, recording_subscription
):
    """``tick()`` hands every waiting message to the subscriber, in order."""
    broker.publish("test_stream", {"data": "test1"})
    broker.publish("test_stream", {"data": "test2"})

    had_work = await recording_subscription.tick()

    assert had_work is True
    assert received == [{"data": "test1"}, {"data": "test2"}]


async def test_tick_acknowledges_delivered_messages(broker, recording_subscription):
    """A message that ``tick()`` delivered is acknowledged, so it is neither
    left in flight nor delivered again."""
    broker.publish("test_stream", {"data": "test1"})
    await recording_subscription.tick()

    had_work = await recording_subscription.tick()

    assert had_work is False
    assert received == [{"data": "test1"}]
    group = broker.info()["consumer_groups"][recording_subscription.subscriber_name]
    assert group["in_flight_messages"] == {"test_stream": 0}


async def test_process_batch_warns_when_the_broker_refuses_a_nack(
    failing_subscription, caplog
):
    """When the broker refuses to NACK a failed message, ``process_batch()``
    logs a warning and counts no success.

    The inline broker accepts the first NACK of a message and refuses a second
    NACK while the message waits for redelivery.
    """
    failing_subscription.broker.publish("fail_stream", {"data": "test"})
    [message] = await failing_subscription.get_next_batch_of_messages()
    identifier = message[0]
    warning = f"[FailingSubscriber] Failed to NACK message {identifier}"

    with caplog.at_level(logging.WARNING):
        first = await failing_subscription.process_batch([message])
    assert first == 0
    assert failing_subscription.retry_counts == {identifier: 1}
    assert warning not in caplog.text

    with caplog.at_level(logging.WARNING):
        second = await failing_subscription.process_batch([message])
    assert second == 0
    assert failing_subscription.retry_counts == {identifier: 2}
    assert warning in caplog.text


async def test_process_batch_does_not_count_a_message_the_broker_refuses_to_ack(
    recording_subscription, caplog
):
    """When the broker refuses to acknowledge a handled message,
    ``process_batch()`` logs a warning and does not count it as a success.

    The inline broker accepts the first ACK of a message and refuses a second.
    """
    recording_subscription.broker.publish("test_stream", {"data": "test"})
    [message] = await recording_subscription.get_next_batch_of_messages()
    identifier = message[0]
    warning = f"Failed to acknowledge message {identifier}"

    with caplog.at_level(logging.WARNING):
        first = await recording_subscription.process_batch([message])
    assert first == 1
    assert warning not in caplog.text

    with caplog.at_level(logging.WARNING):
        second = await recording_subscription.process_batch([message])
    assert second == 0
    assert received == [{"data": "test"}, {"data": "test"}]
    assert warning in caplog.text
