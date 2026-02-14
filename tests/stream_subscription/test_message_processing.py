"""Tests for StreamSubscription message processing functionality.

This module tests message polling, processing, acknowledgment, and retry logic
without using mocks, focusing on real message flow scenarios.
"""

import asyncio
from uuid import uuid4

import pytest

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, Integer, String
from protean.server.engine import Engine
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils.eventing import Message


class Order(BaseAggregate):
    """Test aggregate for message processing tests."""

    order_id = Identifier(required=True, identifier=True)
    customer_id = String()
    amount = Integer()

    def place_order(self):
        """Place an order and raise an event."""
        self.raise_(
            OrderEvent(
                order_id=self.order_id, customer_id=self.customer_id, amount=self.amount
            )
        )


class Payment(BaseAggregate):
    """Test aggregate for message processing tests."""

    payment_id = Identifier(required=True, identifier=True)
    order_id = Identifier(required=True)
    amount = Integer()

    def process_payment(self):
        """Process a payment by issuing a command."""
        # Commands are typically not raised from aggregates, but for testing
        # we can simulate the command creation
        pass


class OrderEvent(BaseEvent):
    """Test event for message processing tests."""

    order_id = Identifier(required=True)
    customer_id = String()
    amount = Integer()


class PaymentCommand(BaseCommand):
    """Test command for message processing tests."""

    payment_id = Identifier(required=True)
    order_id = Identifier(required=True)
    amount = Integer()


class OrderEventHandler(BaseEventHandler):
    """Test handler that processes order events."""

    processed_events = []
    should_fail = False

    @handle(OrderEvent)
    def handle_order_event(self, event):
        if self.should_fail:
            raise Exception("Simulated processing failure")
        self.processed_events.append(event)


class PaymentCommandHandler(BaseCommandHandler):
    """Test handler that processes payment commands."""

    processed_commands = []
    should_fail = False

    @handle(PaymentCommand)
    def handle_payment_command(self, command):
        if self.should_fail:
            raise Exception("Simulated processing failure")
        self.processed_commands.append(command)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    """Register domain elements for testing."""
    test_domain.register(Order)
    test_domain.register(Payment)
    test_domain.register(OrderEvent, part_of=Order)
    test_domain.register(PaymentCommand, part_of=Payment)
    test_domain.register(OrderEventHandler, part_of=Order)
    test_domain.register(PaymentCommandHandler, part_of=Payment)
    test_domain.init(traverse=False)


@pytest.fixture
def engine(test_domain):
    """Create test engine."""
    with test_domain.domain_context():
        return Engine(test_domain, test_mode=True)


@pytest.fixture
def order_event_handler():
    """Create a fresh OrderEventHandler instance."""
    handler = OrderEventHandler()
    # Reset class variables
    OrderEventHandler.processed_events = []
    OrderEventHandler.should_fail = False
    return handler


@pytest.fixture
def payment_command_handler():
    """Create a fresh PaymentCommandHandler instance."""
    handler = PaymentCommandHandler()
    # Reset class variables
    PaymentCommandHandler.processed_commands = []
    PaymentCommandHandler.should_fail = False
    return handler


@pytest.fixture
def valid_order_message(test_domain):
    """Create a valid order event message."""
    order_id = str(uuid4())
    order = Order(order_id=order_id, customer_id="cust-456", amount=100)
    order.place_order()
    # Get the raised event and create a message from it
    return Message.from_domain_object(order._events[-1])


@pytest.fixture
def valid_payment_message(test_domain):
    """Create a valid payment command message."""
    payment_command = PaymentCommand(
        payment_id=str(uuid4()),
        order_id=str(uuid4()),
        amount=200,
    )
    # Enrich the command to get proper metadata
    enriched_command = test_domain._enrich_command(payment_command, track_source=True)
    return Message.from_domain_object(enriched_command)


# Test Message Deserialization
@pytest.mark.redis
async def test_valid_message_deserialization(test_domain, engine, valid_order_message):
    """Test successful deserialization of valid messages."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="order",
            handler=OrderEventHandler,
        )

        await subscription.initialize()

        # Test deserialization
        result = await subscription._deserialize_message(
            "msg-1", valid_order_message.to_dict()
        )

        assert result is not None
        assert isinstance(result, Message)
        assert result.data["customer_id"] == "cust-456"


@pytest.mark.redis
async def test_invalid_message_moves_to_dlq(test_domain, engine):
    """Test that invalid messages are moved to DLQ."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=OrderEventHandler,
            enable_dlq=True,
        )

        await subscription.initialize()

        # Track DLQ messages
        dlq_messages = []
        original_publish = subscription.broker.publish

        def track_dlq_publish(stream, message):
            if stream.endswith(":dlq"):
                dlq_messages.append((stream, message))
            return original_publish(stream, message)

        subscription.broker.publish = track_dlq_publish

        # Test invalid message
        invalid_payload = {"completely": "invalid", "structure": True}
        result = await subscription._deserialize_message("msg-invalid", invalid_payload)

        assert result is None  # Should return None for invalid message
        assert len(dlq_messages) == 1  # Should be moved to DLQ
        assert dlq_messages[0][0] == "orders:dlq"


# Test Message Acknowledgment
@pytest.mark.redis
async def test_successful_message_acknowledgment(
    test_domain, engine, valid_order_message
):
    """Test successful message acknowledgment."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=OrderEventHandler,
        )

        await subscription.initialize()

        # First publish a message to get a valid message ID
        subscription.broker.publish("orders", valid_order_message.to_dict())

        # Read the message to make it pending
        messages = subscription.broker.read_blocking(
            "orders",
            subscription.consumer_group,
            subscription.consumer_name,
            timeout_ms=100,
            count=1,
        )

        if messages:
            actual_msg_id = messages[0][0]

            # Add a retry count to verify it gets cleared
            subscription.retry_counts[actual_msg_id] = 2

            # Test acknowledgment with real message ID
            result = await subscription._acknowledge_message(actual_msg_id)

            assert result is True
            assert actual_msg_id not in subscription.retry_counts  # Should be cleared


# Test Batch Processing
@pytest.mark.redis
async def test_process_batch_with_mixed_messages(
    test_domain, engine, order_event_handler, valid_order_message
):
    """Test processing a batch with valid and invalid messages."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=OrderEventHandler,
            enable_dlq=True,
        )

        await subscription.initialize()

        # Mock the broker ack method to always return True
        original_ack = subscription.broker.ack

        def mock_ack(stream, identifier, consumer_group):
            return True

        subscription.broker.ack = mock_ack

        # Create mixed batch
        order_2 = Order(order_id=str(uuid4()), customer_id="cust-2", amount=200)
        order_2.place_order()
        valid_message_2 = Message.from_domain_object(order_2._events[-1])

        messages = [
            ("msg-1", valid_order_message.to_dict()),
            ("msg-2", {"invalid": "message"}),  # Invalid
            ("msg-3", valid_message_2.to_dict()),
        ]

        # Process batch
        result = await subscription.process_batch(messages)

        # Restore original method
        subscription.broker.ack = original_ack

        # Should process 2 valid messages
        assert result == 2
        assert len(OrderEventHandler.processed_events) == 2


@pytest.mark.redis
async def test_process_batch_with_processing_failures(
    test_domain, engine, order_event_handler, valid_order_message
):
    """Test batch processing with handler failures."""
    with test_domain.domain_context():
        OrderEventHandler.should_fail = True  # Make handler fail

        subscription = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=OrderEventHandler,
            max_retries=1,
            retry_delay_seconds=0.001,
        )

        await subscription.initialize()

        # Mock the broker methods
        subscription.broker.ack = lambda *args: True
        subscription.broker.nack = lambda *args: True

        messages = [("msg-fail", valid_order_message.to_dict())]

        # Process batch - should handle failure
        result = await subscription.process_batch(messages)

        # Should not succeed due to handler failure
        assert result == 0
        assert len(OrderEventHandler.processed_events) == 0


@pytest.mark.redis
async def test_empty_batch_processing(test_domain, engine, order_event_handler):
    """Test processing an empty batch."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=OrderEventHandler,
        )

        await subscription.initialize()

        # Process empty batch
        result = await subscription.process_batch([])

        assert result == 0
        assert len(OrderEventHandler.processed_events) == 0


# Test Retry Mechanism
@pytest.mark.redis
def test_retry_count_increment(test_domain, engine):
    """Test that retry counts are properly incremented."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=OrderEventHandler,
            max_retries=3,
        )

        # Test retry count increment
        count1 = subscription._increment_retry_count("msg-retry-test")
        assert count1 == 1
        assert subscription.retry_counts["msg-retry-test"] == 1

        count2 = subscription._increment_retry_count("msg-retry-test")
        assert count2 == 2
        assert subscription.retry_counts["msg-retry-test"] == 2


@pytest.mark.redis
async def test_retry_message_nack_behavior(test_domain, engine):
    """Test that retry message calls nack on broker."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=OrderEventHandler,
            retry_delay_seconds=0.001,  # Fast for testing
        )

        await subscription.initialize()

        # Track nack calls
        nack_calls = []
        original_nack = subscription.broker.nack

        def track_nack(stream, identifier, consumer_group):
            nack_calls.append((stream, identifier, consumer_group))
            return original_nack(stream, identifier, consumer_group)

        subscription.broker.nack = track_nack

        # Test retry
        await subscription._retry_message("msg-retry", 1)

        assert len(nack_calls) == 1
        assert nack_calls[0][0] == "orders"
        assert nack_calls[0][1] == "msg-retry"
        assert nack_calls[0][2] == subscription.consumer_group


@pytest.mark.redis
async def test_exhaust_retries_workflow(test_domain, engine):
    """Test the complete workflow when retries are exhausted."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=OrderEventHandler,
            max_retries=2,
            enable_dlq=True,
        )

        await subscription.initialize()

        # Track broker operations
        ack_calls = []
        dlq_messages = []

        original_ack = subscription.broker.ack
        original_publish = subscription.broker.publish

        def track_ack(stream, identifier, consumer_group):
            ack_calls.append((stream, identifier, consumer_group))
            return original_ack(stream, identifier, consumer_group)

        def track_publish(stream, message):
            if stream.endswith(":dlq"):
                dlq_messages.append((stream, message))
            return original_publish(stream, message)

        subscription.broker.ack = track_ack
        subscription.broker.publish = track_publish

        # Set up retry count
        subscription.retry_counts["msg-exhaust"] = 2

        # Create test payload
        test_payload = {"test": "data"}

        # Exhaust retries
        await subscription._exhaust_retries("msg-exhaust", test_payload)

        # Verify DLQ and ack behavior
        assert len(dlq_messages) == 1
        assert len(ack_calls) == 1
        assert "msg-exhaust" not in subscription.retry_counts


# Test DLQ Message Format
@pytest.mark.redis
def test_dlq_message_metadata(test_domain, engine):
    """Test that DLQ messages contain proper metadata."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=OrderEventHandler,
        )

        # Set up retry count
        subscription.retry_counts["msg-dlq-test"] = 3

        # Create test payload with metadata
        test_payload = {
            "data": {"order_id": "order-123"},
            "metadata": {"headers": {"time": "2024-01-01T10:00:00Z"}},
        }

        # Create DLQ message
        dlq_message = subscription._create_dlq_message("msg-dlq-test", test_payload)

        # Verify DLQ metadata
        assert "_dlq_metadata" in dlq_message
        dlq_meta = dlq_message["_dlq_metadata"]

        assert dlq_meta["original_stream"] == "orders"
        assert dlq_meta["original_id"] == "msg-dlq-test"
        assert dlq_meta["consumer_group"] == subscription.consumer_group
        assert dlq_meta["consumer"] == subscription.consumer_name
        assert dlq_meta["failed_at"] == "2024-01-01T10:00:00Z"
        assert dlq_meta["retry_count"] == 3

        # Original payload should be preserved
        assert dlq_message["data"] == test_payload["data"]
        assert dlq_message["metadata"] == test_payload["metadata"]


# Test Polling Behavior
@pytest.mark.redis
async def test_poll_with_no_messages(test_domain, engine):
    """Test polling behavior when no messages are available."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=OrderEventHandler,
            blocking_timeout_ms=100,  # Short timeout for testing
        )

        await subscription.initialize()

        # Mock broker to return no messages
        original_read = subscription.broker.read_blocking

        def no_messages(*args, **kwargs):
            return []

        subscription.broker.read_blocking = no_messages

        # Get messages - should return empty list
        messages = await subscription.get_next_batch_of_messages()
        assert messages == []

        # Restore original method
        subscription.broker.read_blocking = original_read


@pytest.mark.redis
async def test_poll_iteration_in_test_mode(test_domain, engine):
    """Test that polling yields control in test mode."""
    with test_domain.domain_context():
        subscription = StreamSubscription(
            engine=engine,
            stream_category="orders",
            handler=OrderEventHandler,
        )

        await subscription.initialize()

        # Set up to stop after one iteration
        iteration_count = 0

        async def count_iterations():
            nonlocal iteration_count
            iteration_count += 1
            if iteration_count >= 2:
                subscription.keep_going = False
            return []

        subscription.get_next_batch_of_messages = count_iterations

        # Run poll for a short time
        try:
            await asyncio.wait_for(subscription.poll(), timeout=1.0)
        except asyncio.TimeoutError:
            pass  # Expected if poll doesn't stop naturally

        # Should have completed at least one iteration
        assert iteration_count >= 2
