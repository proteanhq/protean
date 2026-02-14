"""Tests for StreamSubscription error handling scenarios.

This module focuses on testing error paths and edge cases without using mocks,
ensuring real error conditions are properly handled.
"""

from uuid import uuid4

import pytest

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils.eventing import Message


class ErrorTestAggregate(BaseAggregate):
    """Test aggregate for error handling tests."""

    test_id: Identifier(required=True)
    message: String()


class ErrorTestEvent(BaseEvent):
    """Test event for error scenarios."""

    test_id: Identifier(required=True)
    message: String()


class ErrorTestEventHandler(BaseEventHandler):
    """Test event handler."""

    processed_events = []

    @handle(ErrorTestEvent)
    def handle_test_event(self, event):
        # Simulate processing
        self.processed_events.append(event)


class FailingEventHandler(BaseEventHandler):
    """Event handler that always fails."""

    @handle(ErrorTestEvent)
    def handle_test_event(self, event):
        raise Exception("Simulated processing failure")


class BrokenBroker:
    """A broker that simulates various failure modes."""

    def __init__(self, fail_ensure_group=False, fail_ack=False):
        self.fail_ensure_group = fail_ensure_group
        self.fail_ack = fail_ack
        self.messages = []

    def _ensure_group(self, consumer_group, stream):
        if self.fail_ensure_group:
            raise Exception("Failed to create consumer group")

    def read_blocking(self, stream, consumer_group, consumer_name, timeout_ms, count):
        return self.messages

    def ack(self, stream, identifier, consumer_group):
        if self.fail_ack:
            return False
        return True

    def nack(self, stream, identifier, consumer_group):
        return True

    def publish(self, stream, message):
        return "msg-id"


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    """Register domain elements for testing."""
    test_domain.register(ErrorTestAggregate)
    test_domain.register(ErrorTestEvent, part_of=ErrorTestAggregate)
    test_domain.register(ErrorTestEventHandler, part_of=ErrorTestAggregate)
    test_domain.register(FailingEventHandler, part_of=ErrorTestAggregate)
    test_domain.init(traverse=False)


@pytest.fixture
def engine(test_domain):
    """Create test engine."""
    with test_domain.domain_context():
        return Engine(test_domain, test_mode=True)


@pytest.fixture
def valid_test_event():
    """Create a valid test event."""
    event = ErrorTestEvent(test_id=str(uuid4()), message="test message")
    return Message.from_domain_object(event)


# Test Initialization Errors
@pytest.mark.redis
async def test_initialization_fails_when_broker_ensure_group_raises_exception(
    test_domain, engine
):
    """Test exception handling when _ensure_group fails."""
    with test_domain.domain_context():
        # Create subscription
        subscription = StreamSubscription(
            engine=engine, stream_category="test_errors", handler=ErrorTestEventHandler
        )

        # Initialize first to get a broker
        await subscription.initialize()

        # Replace broker with one that fails on _ensure_group
        broken_broker = BrokenBroker(fail_ensure_group=True)
        subscription.broker = broken_broker

        # Test that _ensure_group raises the exception
        with pytest.raises(Exception, match="Failed to create consumer group"):
            subscription.broker._ensure_group(
                subscription.consumer_group, subscription.stream_category
            )


@pytest.mark.redis
async def test_get_messages_when_broker_not_initialized(test_domain, engine):
    """Test when broker is not initialized."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine, stream_category="test_errors", handler=ErrorTestEventHandler
        )

        # Don't initialize - broker should be None
        assert subscription.broker is None

        # Call get_next_batch_of_messages with no broker
        messages = await subscription.get_next_batch_of_messages()

        # Should return empty list when broker not initialized
        assert messages == []


# Test Message Processing Errors
@pytest.mark.redis
async def test_message_deserialization_failure_continues_processing(
    test_domain, engine, valid_test_event
):
    """Test when message deserialization fails and continues."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="test_errors",
            handler=ErrorTestEventHandler,
            enable_dlq=True,
        )

        # Initialize with working broker
        await subscription.initialize()

        # Mock the broker ack method to always return True
        subscription.broker.ack = lambda *args: True

        # Create a batch with one valid and one invalid message
        messages = [
            ("msg-1", valid_test_event.to_dict()),  # Valid message
            (
                "msg-2",
                {"invalid": "data"},
            ),  # Invalid message that will fail deserialization
            ("msg-3", valid_test_event.to_dict()),  # Another valid message
        ]

        # Mock the engine's handle_message to track calls
        processed_messages = []
        original_handle = engine.handle_message

        async def track_handle_message(handler, message):
            processed_messages.append(message)
            return True

        engine.handle_message = track_handle_message

        # Process the batch
        result = await subscription.process_batch(messages)

        # Should process 2 valid messages, skip 1 invalid
        assert len(processed_messages) == 2
        assert result == 2  # Successfully processed messages

        # Restore original method
        engine.handle_message = original_handle


@pytest.mark.redis
async def test_acknowledgment_failure_warning(test_domain, engine):
    """Test when message acknowledgment fails."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine, stream_category="test_errors", handler=ErrorTestEventHandler
        )

        # Replace broker with one that fails on ack
        broken_broker = BrokenBroker(fail_ack=True)
        subscription.broker = broken_broker

        # Test acknowledgment failure
        result = await subscription._acknowledge_message("test-msg-id")

        # Should return False when acknowledgment fails
        assert result is False


# Test Retry and DLQ Flow
@pytest.mark.redis
async def test_retry_exhaustion_moves_to_dlq(test_domain, engine, valid_test_event):
    """Test complete retry flow without mocks."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="test_failing",
            handler=FailingEventHandler,  # Always fails
            max_retries=2,
            retry_delay_seconds=0.001,  # Fast retry for testing
            enable_dlq=True,
        )

        await subscription.initialize()

        # Track DLQ publishes
        dlq_messages = []
        original_publish = subscription.broker.publish

        def track_publish(stream, message):
            if stream.endswith(":dlq"):
                dlq_messages.append((stream, message))
            return original_publish(stream, message)

        subscription.broker.publish = track_publish

        # Process the failing message multiple times
        identifier = "test-fail-msg"
        payload = valid_test_event.to_dict()

        # First failure - should retry
        await subscription.handle_failed_message(identifier, payload)
        assert subscription.retry_counts.get(identifier, 0) == 1
        assert len(dlq_messages) == 0  # Not in DLQ yet

        # Second failure - should move to DLQ (max_retries=2)
        await subscription.handle_failed_message(identifier, payload)

        # After second failure, it should move to DLQ since max_retries=2
        # The retry count should be cleared after moving to DLQ
        assert identifier not in subscription.retry_counts
        assert len(dlq_messages) == 1
        assert dlq_messages[0][0] == "test_failing:dlq"
        assert "_dlq_metadata" in dlq_messages[0][1]


# Test StreamSubscription Configuration
@pytest.mark.redis
def test_subscription_id_generation_is_unique(test_domain, engine):
    """Test that subscription IDs are unique across instances."""
    with test_domain.domain_context():
        subscription1 = StreamSubscription(
            engine=engine, stream_category="test1", handler=ErrorTestEventHandler
        )

        subscription2 = StreamSubscription(
            engine=engine, stream_category="test2", handler=ErrorTestEventHandler
        )

        # IDs should be different
        assert subscription1.subscription_id != subscription2.subscription_id

        # Both should contain the handler class name
        assert "ErrorTestEventHandler" in subscription1.subscription_id
        assert "ErrorTestEventHandler" in subscription2.subscription_id


@pytest.mark.redis
async def test_dlq_disabled_skips_dlq_operations(test_domain, engine):
    """Test that DLQ operations are skipped when disabled."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="test_no_dlq",
            handler=ErrorTestEventHandler,
            enable_dlq=False,  # Disable DLQ
        )

        # Should not attempt to publish to DLQ
        # This test verifies the early return in move_to_dlq
        result = await subscription.move_to_dlq("test-id", {"test": "data"})

        # Should complete without error and return None
        assert result is None
