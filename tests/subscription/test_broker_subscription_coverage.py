import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.server import Engine
from protean.utils import fqn


class DummySubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        pass


class FailingSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        raise Exception("Test exception")


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(DummySubscriber, stream="test_stream")
    test_domain.register(FailingSubscriber, stream="fail_stream")
    test_domain.init(traverse=False)


@pytest.mark.asyncio
async def test_broker_subscription_poll_exits_when_keep_going_false(test_domain):
    """Test that BrokerSubscription.poll() exits when keep_going is set to False"""
    engine = Engine(test_domain, test_mode=True)
    subscription = engine._broker_subscriptions[fqn(DummySubscriber)]

    # Mock the tick method to prevent actual processing
    subscription.tick = AsyncMock()

    # Start polling in background
    poll_task = asyncio.create_task(subscription.poll())

    # Let it run briefly
    await asyncio.sleep(0.1)

    # Set keep_going to False to trigger exit
    subscription.keep_going = False

    # Wait for poll to complete
    await asyncio.wait_for(poll_task, timeout=1.0)

    # Verify poll exited
    assert poll_task.done()


@pytest.mark.asyncio
async def test_broker_subscription_poll_exits_when_engine_shutting_down(test_domain):
    """Test that BrokerSubscription.poll() exits when engine.shutting_down is True"""
    engine = Engine(test_domain, test_mode=True)
    subscription = engine._broker_subscriptions[fqn(DummySubscriber)]

    # Mock the tick method to prevent actual processing
    subscription.tick = AsyncMock()

    # Start polling in background
    poll_task = asyncio.create_task(subscription.poll())

    # Let it run briefly
    await asyncio.sleep(0.1)

    # Set engine.shutting_down to True to trigger exit
    engine.shutting_down = True

    # Wait for poll to complete
    await asyncio.wait_for(poll_task, timeout=1.0)

    # Verify poll exited
    assert poll_task.done()


@pytest.mark.asyncio
async def test_broker_subscription_poll_test_mode_sleep_zero(test_domain):
    """Test that BrokerSubscription.poll() uses asyncio.sleep(0) in test mode"""
    engine = Engine(test_domain, test_mode=True)
    subscription = engine._broker_subscriptions[fqn(DummySubscriber)]

    # Verify the engine is in test mode
    assert engine.test_mode is True

    # Mock tick to return immediately but let it run briefly
    tick_call_count = 0

    async def mock_tick():
        nonlocal tick_call_count
        tick_call_count += 1
        # Stop after enough iterations to hit the sleep line
        if tick_call_count >= 3:
            subscription.keep_going = False
        # Add a tiny delay to let the event loop run
        await asyncio.sleep(0.001)

    subscription.tick = mock_tick

    # Start polling and let it run to hit the sleep(0) line
    poll_task = asyncio.create_task(subscription.poll())

    # Wait for poll to complete
    try:
        await asyncio.wait_for(poll_task, timeout=1.0)
    except asyncio.TimeoutError:
        subscription.keep_going = False
        await asyncio.wait_for(poll_task, timeout=0.5)

    # Verify tick was called multiple times (means the loop ran and hit sleep lines)
    assert tick_call_count >= 3


@pytest.mark.asyncio
async def test_broker_subscription_tick_with_empty_messages(test_domain):
    """Test that BrokerSubscription.tick() handles empty message batches correctly"""
    engine = Engine(test_domain, test_mode=True)
    subscription = engine._broker_subscriptions[fqn(DummySubscriber)]

    # Mock get_next_batch_of_messages to return empty list
    subscription.get_next_batch_of_messages = AsyncMock(return_value=[])

    # Mock process_batch to track if it was called
    subscription.process_batch = AsyncMock()

    # Call tick
    await subscription.tick()

    # Verify process_batch was not called because messages was empty
    subscription.process_batch.assert_not_called()


@pytest.mark.asyncio
async def test_broker_subscription_tick_with_messages(test_domain):
    """Test that BrokerSubscription.tick() calls process_batch when messages exist"""
    engine = Engine(test_domain, test_mode=True)
    subscription = engine._broker_subscriptions[fqn(DummySubscriber)]

    # Mock get_next_batch_of_messages to return messages
    test_messages = [("msg1", {"data": "test1"}), ("msg2", {"data": "test2"})]
    subscription.get_next_batch_of_messages = AsyncMock(return_value=test_messages)

    # Mock process_batch to track if it was called
    subscription.process_batch = AsyncMock()

    # Call tick
    await subscription.tick()

    # Verify process_batch was called with the messages
    subscription.process_batch.assert_called_once_with(test_messages)


@pytest.mark.asyncio
async def test_broker_subscription_process_batch_nack_failure(test_domain, caplog):
    """Test that BrokerSubscription.process_batch() logs warning when nack fails"""
    engine = Engine(test_domain, test_mode=True)
    subscription = engine._broker_subscriptions[fqn(FailingSubscriber)]

    # Mock broker nack to return False (failure)
    subscription.broker.nack = MagicMock(return_value=False)

    # Mock engine.handle_broker_message to return False (failed processing)
    engine.handle_broker_message = AsyncMock(return_value=False)

    # Test messages
    test_messages = [("msg_id_1", {"data": "test"})]

    # Process the batch
    with caplog.at_level(logging.WARNING):
        result = await subscription.process_batch(test_messages)

    # Verify nack was called
    subscription.broker.nack.assert_called_once_with(
        "fail_stream", "msg_id_1", subscription.subscriber_name
    )

    # Verify warning was logged
    assert "Failed to nack message msg_id_1" in caplog.text

    # Verify no messages were processed successfully
    assert result == 0


@pytest.mark.asyncio
async def test_broker_subscription_process_batch_ack_failure(test_domain, caplog):
    """Test that BrokerSubscription.process_batch() logs warning when ack fails"""
    engine = Engine(test_domain, test_mode=True)
    subscription = engine._broker_subscriptions[fqn(DummySubscriber)]

    # Mock broker ack to return False (failure)
    subscription.broker.ack = MagicMock(return_value=False)

    # Mock engine.handle_broker_message to return True (successful processing)
    engine.handle_broker_message = AsyncMock(return_value=True)

    # Test messages
    test_messages = [("msg_id_1", {"data": "test"})]

    # Process the batch
    with caplog.at_level(logging.WARNING):
        result = await subscription.process_batch(test_messages)

    # Verify ack was called
    subscription.broker.ack.assert_called_once_with(
        "test_stream", "msg_id_1", subscription.subscriber_name
    )

    # Verify warning was logged
    assert "Failed to acknowledge message msg_id_1" in caplog.text

    # Verify no messages were processed successfully due to ack failure
    assert result == 0
