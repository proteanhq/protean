"""Tests for StreamSubscription edge cases and error scenarios."""

import logging
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from protean import handle
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.server.engine import Engine
from protean.server.subscription.stream_subscription import StreamSubscription


class EdgeCaseEvent(BaseEvent):
    """Test event for testing."""

    test_id: str
    message: str | None = None


class EdgeCaseEventHandler(BaseEventHandler):
    """Test event handler."""

    processed_events = []

    @handle(EdgeCaseEvent)
    def handle_test_event(self, event):
        self.processed_events.append(event)


@pytest.mark.redis
@pytest.mark.asyncio
class TestStreamSubscriptionEdgeCases:
    """Test edge cases and error scenarios in StreamSubscription."""

    async def test_ensure_group_failure(self, test_domain):
        """Test handling of _ensure_group failure during initialization."""
        engine = Engine(test_domain, test_mode=True)
        subscription = StreamSubscription(
            engine=engine,
            stream_category="test-stream",
            handler=EdgeCaseEventHandler,
        )

        # Mock broker with failing _ensure_group
        mock_broker = MagicMock()
        mock_broker._ensure_group.side_effect = Exception(
            "Consumer group creation failed"
        )
        engine.domain.brokers["default"] = mock_broker

        # Should raise and log the error
        with pytest.raises(Exception, match="Consumer group creation failed"):
            await subscription.initialize()

    async def test_poll_exits_when_not_keep_going(self, test_domain):
        """Test that poll exits when keep_going is False."""
        engine = Engine(test_domain, test_mode=True)
        subscription = StreamSubscription(
            engine=engine,
            stream_category="test-stream",
            handler=EdgeCaseEventHandler,
        )

        # Initialize with a mock broker
        mock_broker = MagicMock()
        mock_broker._ensure_group = MagicMock()
        mock_broker.read_blocking.return_value = []
        engine.domain.brokers["default"] = mock_broker

        await subscription.initialize()

        # Set keep_going to False
        subscription.keep_going = False

        # Poll should exit immediately without calling get_next_batch_of_messages
        with patch.object(subscription, "get_next_batch_of_messages") as mock_get_next:
            await subscription.poll()
            mock_get_next.assert_not_called()

    async def test_poll_test_mode_yields_control(self, test_domain):
        """Test that poll yields control in test mode."""
        engine = Engine(test_domain, test_mode=True)
        subscription = StreamSubscription(
            engine=engine,
            stream_category="test-stream",
            handler=EdgeCaseEventHandler,
        )

        # Initialize with a mock broker
        mock_broker = MagicMock()
        mock_broker._ensure_group = MagicMock()
        mock_broker.read_blocking.return_value = [("msg-1", {"test": "data"})]
        engine.domain.brokers["default"] = mock_broker

        await subscription.initialize()

        # Track if asyncio.sleep(0) was called
        sleep_called = []

        async def mock_sleep(delay):
            sleep_called.append(delay)
            # Stop iteration after first sleep
            subscription.keep_going = False
            return

        # Mock process_batch to avoid processing
        async def mock_process_batch(messages):
            return len(messages)

        subscription.process_batch = mock_process_batch

        # Patch asyncio.sleep to track calls
        with patch("asyncio.sleep", side_effect=mock_sleep):
            await subscription.poll()

        # Should have called sleep(0) in test mode
        assert 0 in sleep_called, "asyncio.sleep(0) should be called in test mode"

    async def test_get_next_batch_broker_not_initialized(self, test_domain, caplog):
        """Test get_next_batch_of_messages when broker is not initialized."""
        engine = Engine(test_domain, test_mode=True)
        subscription = StreamSubscription(
            engine=engine,
            stream_category="test-stream",
            handler=EdgeCaseEventHandler,
        )

        # Don't initialize, so broker remains None
        subscription.broker = None

        with caplog.at_level(logging.ERROR):
            result = await subscription.get_next_batch_of_messages()

        assert result == []
        assert "Broker not initialized" in caplog.text

    async def test_get_next_batch_read_blocking_exception(self, test_domain, caplog):
        """Test get_next_batch_of_messages when read_blocking raises exception."""
        engine = Engine(test_domain, test_mode=True)
        subscription = StreamSubscription(
            engine=engine,
            stream_category="test-stream",
            handler=EdgeCaseEventHandler,
        )

        # Initialize with a mock broker that raises exception
        mock_broker = MagicMock()
        mock_broker._ensure_group = MagicMock()
        mock_broker.read_blocking.side_effect = Exception("Read blocking failed")
        engine.domain.brokers["default"] = mock_broker

        await subscription.initialize()

        with caplog.at_level(logging.ERROR):
            result = await subscription.get_next_batch_of_messages()

        assert result == []
        assert "Error reading messages from stream" in caplog.text
        assert "Read blocking failed" in caplog.text

    async def test_acknowledge_message_failure(self, test_domain, caplog):
        """Test when message acknowledgment fails."""
        engine = Engine(test_domain, test_mode=True)
        subscription = StreamSubscription(
            engine=engine,
            stream_category="test-stream",
            handler=EdgeCaseEventHandler,
        )

        # Initialize with a mock broker
        mock_broker = MagicMock()
        mock_broker._ensure_group = MagicMock()
        mock_broker.ack.return_value = False  # ACK fails
        engine.domain.brokers["default"] = mock_broker

        await subscription.initialize()

        with caplog.at_level(logging.WARNING):
            result = await subscription._acknowledge_message("test-message-id")

        assert result is False
        assert "Failed to acknowledge message test-message-id" in caplog.text

    async def test_process_batch_skip_failed_deserialization(self, test_domain):
        """Test process_batch skips messages that fail deserialization."""
        engine = Engine(test_domain, test_mode=True)
        subscription = StreamSubscription(
            engine=engine,
            stream_category="test-stream",
            handler=EdgeCaseEventHandler,
        )

        # Initialize with a mock broker
        mock_broker = MagicMock()
        mock_broker._ensure_group = MagicMock()
        mock_broker.ack.return_value = True
        mock_broker.publish = MagicMock()  # For DLQ
        engine.domain.brokers["default"] = mock_broker

        await subscription.initialize()

        # Create messages - one valid, one that will fail deserialization
        messages = [
            ("msg-1", {"invalid": "structure"}),  # Will fail deserialization
            (
                "msg-2",
                {  # Valid message
                    "metadata": {
                        "headers": {
                            "id": str(uuid4()),
                            "type": "EdgeCaseEvent",
                            "time": "2024-01-01T00:00:00Z",
                        }
                    },
                    "data": {"test_id": str(uuid4()), "message": "test"},
                },
            ),
        ]

        # Mock handle_message to track calls
        handle_message_calls = []

        async def mock_handle_message(handler, message):
            handle_message_calls.append(message)
            return True

        engine.handle_message = mock_handle_message

        # Process batch
        result = await subscription.process_batch(messages)

        # Should process only the valid message
        assert len(handle_message_calls) == 1
        assert result == 1  # Only one successful

    async def test_move_to_dlq_publish_failure(self, test_domain, caplog):
        """Test move_to_dlq when publish to DLQ fails."""
        engine = Engine(test_domain, test_mode=True)
        subscription = StreamSubscription(
            engine=engine,
            stream_category="test-stream",
            handler=EdgeCaseEventHandler,
            enable_dlq=True,
        )

        # Initialize with a mock broker
        mock_broker = MagicMock()
        mock_broker._ensure_group = MagicMock()
        mock_broker.publish.side_effect = Exception("DLQ publish failed")
        engine.domain.brokers["default"] = mock_broker

        await subscription.initialize()

        with caplog.at_level(logging.ERROR):
            await subscription.move_to_dlq("failed-msg-id", {"test": "data"})

        assert "Failed to move message failed-msg-id to DLQ" in caplog.text
        assert "DLQ publish failed" in caplog.text

    async def test_move_to_dlq_success(self, test_domain, caplog):
        """Test successful move_to_dlq."""
        engine = Engine(test_domain, test_mode=True)
        subscription = StreamSubscription(
            engine=engine,
            stream_category="test-stream",
            handler=EdgeCaseEventHandler,
            enable_dlq=True,
        )

        # Initialize with a mock broker
        mock_broker = MagicMock()
        mock_broker._ensure_group = MagicMock()
        mock_broker.publish.return_value = "dlq-msg-id"
        engine.domain.brokers["default"] = mock_broker

        await subscription.initialize()

        with caplog.at_level(logging.INFO):
            await subscription.move_to_dlq("failed-msg-id", {"test": "data"})

        assert (
            "Moved message failed-msg-id to DLQ stream test-stream:dlq" in caplog.text
        )
        mock_broker.publish.assert_called_once()

        # Verify DLQ message structure
        dlq_message = mock_broker.publish.call_args[0][1]
        assert "_dlq_metadata" in dlq_message
        assert dlq_message["_dlq_metadata"]["original_id"] == "failed-msg-id"
        assert dlq_message["_dlq_metadata"]["original_stream"] == "test-stream"
