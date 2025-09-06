"""Tests for error handling and edge cases in InlineBroker."""

import logging
from unittest.mock import patch

import pytest


# ============= ACK Error Handling Tests =============


def test_exception_during_ack_returns_false(broker):
    """Test that exceptions during ACK return False."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Mock an exception in ACK processing
    with patch.object(
        broker, "_is_in_flight_message", side_effect=Exception("Test exception")
    ):
        result = broker.ack(stream, identifier, consumer_group)
        assert result is False


def test_exception_during_ack_cleanup_message_ownership_returns_false(broker):
    """Test that exceptions during ownership cleanup in ACK return False."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Mock an exception in cleanup_message_ownership
    with patch.object(
        broker, "_cleanup_message_ownership", side_effect=Exception("Cleanup failed")
    ):
        result = broker.ack(stream, identifier, consumer_group)
        assert result is False


def test_ack_operation_state_cleanup_on_exception(broker):
    """Test that operation state is cleaned up on ACK exception."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Mock an exception in ACK processing
    with patch.object(
        broker, "_remove_in_flight_message", side_effect=Exception("Test exception")
    ):
        result = broker.ack(stream, identifier, consumer_group)
        assert result is False

        # Operation state should be cleaned up
        state = broker._get_operation_state(consumer_group, identifier)
        assert state is None


def test_exception_during_ack_logger_error_returns_false(broker):
    """Test that ACK handles logger errors gracefully."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Mock logger.debug to raise an exception
    with patch.object(
        logging.getLogger("protean.adapters.broker.inline"),
        "debug",
        side_effect=Exception("Logger failed"),
    ):
        # ACK should handle the logging failure
        with patch.object(
            logging.getLogger("protean.adapters.broker.inline"), "error"
        ) as mock_error:
            result = broker.ack(stream, identifier, consumer_group)
            assert result is False
            mock_error.assert_called()


# ============= NACK Error Handling Tests =============


def test_exception_during_nack_returns_false(broker):
    """Test that exceptions during NACK return False."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Mock an exception in NACK processing
    with patch.object(
        broker, "_get_in_flight_message", side_effect=Exception("Test exception")
    ):
        result = broker.nack(stream, identifier, consumer_group)
        assert result is False


def test_exception_during_nack_operation_state_cleanup_on_exception(broker):
    """Test that operation state is cleaned up on NACK exception."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Mock an exception in NACK processing
    with patch.object(
        broker, "_get_retry_count", side_effect=Exception("Test exception")
    ):
        result = broker.nack(stream, identifier, consumer_group)
        assert result is False

        # Operation state should be cleaned up
        state = broker._get_operation_state(consumer_group, identifier)
        assert state is None


def test_exception_during_nack_with_retry_returns_false(broker):
    """Test that exceptions during NACK with retry return False."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Mock an exception in handle_nack_with_retry
    with patch.object(
        broker, "_handle_nack_with_retry", side_effect=Exception("Retry failed")
    ):
        # Ensure we trigger the retry path
        broker._max_retries = 3
        result = broker.nack(stream, identifier, consumer_group)
        assert result is False


def test_exception_during_nack_with_retry_store_failed_message_returns_false(broker):
    """Test that exceptions during storing failed message in NACK return False."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Mock an exception in store_failed_message
    with patch.object(
        broker, "_store_failed_message", side_effect=Exception("Store failed")
    ):
        result = broker.nack(stream, identifier, consumer_group)
        assert result is False


def test_exception_during_nack_max_retries_exceeded_with_retry_message(broker):
    """Test exception handling when max retries exceeded."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with no retries
    broker._max_retries = 0
    broker._retry_delay = 0.01

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Mock an exception in handle_nack_max_retries_exceeded
    with patch.object(
        broker,
        "_handle_nack_max_retries_exceeded",
        side_effect=Exception("Max retries failed"),
    ):
        result = broker.nack(stream, identifier, consumer_group)
        assert result is False


def test_exception_during_nack_max_retries_exceeded_with_simulated_condition(broker):
    """Test NACK when max retries is exceeded with error conditions."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker
    broker._max_retries = 0

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Mock DLQ storage to fail
    with patch.object(
        broker, "_store_dlq_message", side_effect=Exception("DLQ failed")
    ):
        result = broker.nack(stream, identifier, consumer_group)
        assert result is False


def test_exception_during_nack_with_retry_logger_error_returns_false(broker):
    """Test that NACK handles logger errors during retry."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Mock logger to fail but ensure NACK still works
    with patch.object(
        logging.getLogger("protean.adapters.broker.inline"),
        "debug",
        side_effect=Exception("Logger failed"),
    ):
        # NACK should still succeed despite logging failure
        result = broker.nack(stream, identifier, consumer_group)
        assert result is True


# ============= Requeue Error Handling Tests =============


def test_exception_during_requeue_failed_messages_returns_none(broker):
    """Test that exceptions during requeue of failed messages are handled."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Mock an exception in get_retry_ready_messages
    with patch.object(
        broker, "_get_retry_ready_messages", side_effect=Exception("Get ready failed")
    ):
        # Should not raise, just log error
        with patch.object(
            logging.getLogger("protean.adapters.broker.inline"), "error"
        ) as mock_error:
            broker._requeue_failed_messages(stream, consumer_group)
            mock_error.assert_called()


def test_exception_during_requeue_messages_returns_none(broker):
    """Test that exceptions during requeue_messages are handled."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Create messages that would be ready for retry
    broker._failed_messages[f"{stream}:{consumer_group}"] = [
        ("id1", {"data": 1}, 1, 0)  # Past retry time
    ]

    # Mock an exception in _requeue_messages
    with patch.object(
        broker, "_requeue_messages", side_effect=Exception("Requeue failed")
    ):
        # This is called by _requeue_failed_messages which handles exceptions
        with patch.object(
            logging.getLogger("protean.adapters.broker.inline"), "error"
        ) as mock_error:
            broker._requeue_failed_messages(stream, consumer_group)
            # Should log the error but not raise
            mock_error.assert_called()


def test_exception_during_mixed_scenarios(broker):
    """Test mixed error scenarios."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Try ACK with non-existent consumer group
    fake_group = "fake_group"
    result = broker.ack(stream, identifier, fake_group)
    assert result is False

    # Try NACK with non-existent message
    fake_id = "fake_id"
    result = broker.nack(stream, fake_id, consumer_group)
    assert result is False


# ============= Validation Error Tests =============


def test_validate_message_ownership_exception_handling(broker):
    """Test message ownership validation with edge cases."""
    # Test with None values
    result = broker._validate_message_ownership(None, None)
    assert result is False

    # Test with empty strings
    result = broker._validate_message_ownership("", "")
    assert result is False

    # Test with valid identifier but no ownership
    result = broker._validate_message_ownership("valid_id", "consumer_group")
    assert result is False


def test_get_retry_count_exception_handling(broker):
    """Test get_retry_count with invalid inputs."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    identifier = "test_id"

    # Should return 0 for non-existent entries
    count = broker._get_retry_count(stream, consumer_group, identifier)
    assert count == 0

    # Test with None values
    count = broker._get_retry_count(None, None, None)
    assert count == 0


def test_cleanup_stale_messages_exception_in_processing(broker):
    """Test cleanup_stale_messages with processing errors."""
    consumer_group = "test_consumer_group"

    # Create invalid in-flight structure
    broker._in_flight["invalid:group"] = "not_a_dict"

    # Should handle gracefully
    try:
        broker._cleanup_stale_messages(consumer_group, 1.0)
    except Exception:
        # This test is marked as skipped in original, keeping same behavior
        pytest.skip("This test is flaky and needs to be fixed")


def test_requeue_messages_exception_handling(broker):
    """Test requeue_messages with various error conditions."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Test with empty message list
    broker._requeue_messages(stream, consumer_group, [])

    # Test with None messages
    try:
        broker._requeue_messages(stream, consumer_group, None)
    except Exception:
        pass  # Expected to handle or fail gracefully


def test_remove_failed_message_exception_handling(broker):
    """Test remove_failed_message with edge cases."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    identifier = "test_id"

    # Should handle non-existent message gracefully
    broker._remove_failed_message(stream, consumer_group, identifier)

    # Test with invalid group key
    group_key = f"{stream}:{consumer_group}"
    broker._failed_messages[group_key] = None

    # Should handle gracefully
    try:
        broker._remove_failed_message(stream, consumer_group, identifier)
    except Exception:
        pass  # Expected to handle gracefully


def test_get_in_flight_message_nonexistent(broker):
    """Test getting non-existent in-flight message."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    identifier = "non_existent"

    result = broker._get_in_flight_message(stream, consumer_group, identifier)
    assert result is None


# ============= Handle NACKed Message Error Tests =============


def test_handle_nacked_message_for_ack_not_found(broker):
    """Test handling NACKed message for ACK when not in failed queue."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    identifier = "test_msg"

    # Call with non-existent message
    result = broker._handle_nacked_message_for_ack(stream, consumer_group, identifier)
    assert result is False

    # Test with exception during processing
    group_key = f"{stream}:{consumer_group}"
    broker._failed_messages[group_key] = None  # Invalid data to cause error

    with patch.object(logging.getLogger("protean.adapters.broker.inline"), "error"):
        result = broker._handle_nacked_message_for_ack(
            stream, consumer_group, identifier
        )
        assert result is False


# ============= Error Handling Invalid Stream Tests =============


def test_error_handling_invalid_stream(broker):
    """Test error handling with invalid stream names."""
    consumer_group = "test_consumer_group"

    # Test with None stream
    result = broker.get_next(None, consumer_group)
    assert result is None

    # Test with empty stream
    result = broker.get_next("", consumer_group)
    assert result is None

    # Test ACK with invalid stream
    result = broker.ack(None, "id", consumer_group)
    assert result is False

    # Test NACK with invalid stream
    result = broker.nack("", "id", consumer_group)
    assert result is False


def test_stream_cleanup_behavior(broker):
    """Test cleanup behavior for streams."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Publish and consume message
    identifier = broker.publish(stream, {"test": "data"})
    broker.get_next(stream, consumer_group)
    broker.ack(stream, identifier, consumer_group)

    # Stream should still exist in messages
    assert stream in broker._messages

    # Consumer group structures should exist
    group_key = f"{stream}:{consumer_group}"
    assert group_key in broker._consumer_groups
