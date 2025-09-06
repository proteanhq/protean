"""Tests for message acknowledgment (ACK/NACK) operations in InlineBroker."""

import logging
import time
from unittest.mock import patch

from protean.port.broker import OperationState


# ============= ACK Tests =============


def test_ack_removes_from_in_flight_tracking(broker):
    """Test that acknowledging a message removes it from in-flight tracking."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message to put it in in-flight status
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Verify message is in-flight
    assert broker._is_in_flight_message(stream, consumer_group, identifier)

    # Acknowledge the message
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Verify message is no longer in-flight
    assert not broker._is_in_flight_message(stream, consumer_group, identifier)


def test_ack_cleans_up_message_ownership(broker):
    """Test that acknowledging a message cleans up ownership tracking."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Verify message ownership exists
    assert broker._validate_message_ownership(identifier, consumer_group)

    # Acknowledge the message
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True


def test_ack_message_already_acknowledged_idempotent(broker):
    """Test ack idempotency when message already acknowledged."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # First ack - should succeed
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Second ack - should be idempotent (return False but not fail)
    ack_result_2 = broker.ack(stream, identifier, consumer_group)
    assert ack_result_2 is False  # Idempotent operation


def test_ack_previously_nacked_message(broker):
    """Test acknowledging a message that was previously NACKed."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with short retry delay
    broker._retry_delay = 0.01

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None

    # NACK the message
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Verify message is in failed queue
    group_key = f"{stream}:{consumer_group}"
    assert len(broker._failed_messages[group_key]) == 1

    # Now ACK the previously NACKed message
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Verify message is removed from failed queue
    assert len(broker._failed_messages[group_key]) == 0

    # Verify operation state is now ACKNOWLEDGED
    state = broker._get_operation_state(consumer_group, identifier)
    assert state == OperationState.ACKNOWLEDGED


def test_ack_nacked_message_not_in_failed_queue(broker):
    """Test ACK of NACKed message that's not in failed queue."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None

    # Store NACKED state but don't add to failed messages
    broker._store_operation_state(consumer_group, identifier, OperationState.NACKED)

    # Remove from in-flight to simulate edge case
    broker._remove_in_flight_message(stream, consumer_group, identifier)

    # Try to ACK - should fail since message is not in failed queue
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is False


# ============= NACK Tests =============


def test_nack_moves_message_to_retry_queue(broker):
    """Test that nacking a message moves it to retry queue for reprocessing."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with short retry delay for testing
    broker._retry_delay = 0.1  # 100ms for fast testing

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get the message (moves to in-flight)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    retrieved_identifier, retrieved_payload = retrieved_message
    assert retrieved_identifier == identifier
    assert retrieved_payload == message

    # Verify message is in in-flight tracking
    info_before_nack = broker.info()
    if consumer_group in info_before_nack["consumer_groups"]:
        in_flight_info = info_before_nack["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            assert in_flight_info[stream] >= 1

    # Nack the message
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Message should no longer be immediately available (it's in retry queue)
    immediate_retry = broker.get_next(stream, consumer_group)
    assert immediate_retry is None

    # Verify message is removed from in-flight tracking
    info_after_nack = broker.info()
    if consumer_group in info_after_nack["consumer_groups"]:
        in_flight_info = info_after_nack["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            # Should be 0 or less than before
            assert in_flight_info[stream] == 0

    # Wait for retry delay and verify message becomes available again
    time.sleep(0.15)  # Wait slightly longer than retry delay

    # The message should now be available for retry
    retry_message = broker.get_next(stream, consumer_group)
    assert retry_message is not None
    retry_identifier, retry_payload = retry_message
    assert retry_identifier == identifier
    assert retry_payload == message


def test_nack_with_retry_mechanism(broker):
    """Test that nacked messages are retried with exponential backoff."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with short retry delay for testing
    broker._retry_delay = 0.1  # 100ms for fast testing

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get and nack the message
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Immediately trying to get next message should return None (message is in retry queue)
    immediate_retry = broker.get_next(stream, consumer_group)
    assert immediate_retry is None

    # Wait for first retry delay
    time.sleep(0.15)

    # Message should be available for retry
    retry_message = broker.get_next(stream, consumer_group)
    assert retry_message is not None
    retry_identifier, _ = retry_message
    assert retry_identifier == identifier

    # Nack again - this should have longer delay (exponential backoff)
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Message should not be available immediately
    immediate_retry = broker.get_next(stream, consumer_group)
    assert immediate_retry is None

    # Wait for second retry delay (should be longer due to exponential backoff)
    time.sleep(0.25)  # 0.1 * 2 = 0.2, plus buffer

    # Message should be available again
    retry_message_2 = broker.get_next(stream, consumer_group)
    assert retry_message_2 is not None
    retry_identifier_2, _ = retry_message_2
    assert retry_identifier_2 == identifier


def test_nack_max_retries_exceeded(broker):
    """Test that messages exceeding max retries are moved to DLQ."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with short retry delay and low max retries
    broker._retry_delay = 0.01  # 10ms for fast testing
    broker._max_retries = 2  # Only 2 retries allowed

    # Publish a message
    identifier = broker.publish(stream, message)

    # First attempt - nack
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Second attempt - nack
    time.sleep(0.02)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Third attempt - should exceed max retries
    time.sleep(0.04)  # Longer delay for exponential backoff
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Message should be in DLQ now
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert stream in dlq_messages
    assert len(dlq_messages[stream]) == 1
    dlq_id, dlq_msg, dlq_reason, _ = dlq_messages[stream][0]
    assert dlq_id == identifier
    assert dlq_msg == message
    assert dlq_reason == "max_retries_exceeded"


def test_nack_removes_from_in_flight_tracking(broker):
    """Test that nacking a message removes it from in-flight tracking."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message to put it in in-flight status
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Verify message is in-flight
    assert broker._is_in_flight_message(stream, consumer_group, identifier)

    # Nack the message
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Verify message is no longer in-flight
    assert not broker._is_in_flight_message(stream, consumer_group, identifier)


def test_nack_retry_count_tracking(broker):
    """Test that retry counts are properly tracked for nacked messages."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with short retry delay
    broker._retry_delay = 0.01  # 10ms for fast testing

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get and nack the message multiple times
    for expected_retry_count in range(1, 4):
        # Get the message
        if expected_retry_count > 1:
            time.sleep(0.02 * (2 ** (expected_retry_count - 2)))  # Exponential backoff
        retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message is not None

        # Check retry count before nack
        retry_count = broker._get_retry_count(stream, consumer_group, identifier)
        assert retry_count == expected_retry_count - 1

        # Nack the message
        nack_result = broker.nack(stream, identifier, consumer_group)
        assert nack_result is True

        # Check retry count after nack
        retry_count = broker._get_retry_count(stream, consumer_group, identifier)
        assert retry_count == expected_retry_count


def test_nack_message_already_nacked_idempotent(broker):
    """Test nack idempotency when message already nacked."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # First nack - should succeed
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Second nack - should be idempotent (return False but not fail)
    nack_result_2 = broker.nack(stream, identifier, consumer_group)
    assert nack_result_2 is False  # Idempotent operation


def test_nack_message_not_in_flight(broker):
    """Test NACKing a message that's not in in-flight status."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish message
    identifier = broker.publish(stream, message)

    # Get message to establish ownership
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None

    # Manually remove from in-flight to simulate edge case
    broker._remove_in_flight_message(stream, consumer_group, identifier)

    # Try to NACK - should fail
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is False


def test_nack_with_logging_failure(broker):
    """Test NACK when logging fails."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None

    # Mock logger.debug to raise an exception
    with patch.object(
        logging.getLogger("protean.adapters.broker.inline"), "debug"
    ) as mock_debug:
        mock_debug.side_effect = Exception("Logging failed")

        # NACK should still succeed despite logging failure
        nack_result = broker.nack(stream, identifier, consumer_group)
        assert nack_result is True

        # Verify message was moved to failed queue
        group_key = f"{stream}:{consumer_group}"
        assert len(broker._failed_messages[group_key]) == 1
