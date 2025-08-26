"""Test cases for broker error handling scenarios"""

import time
import uuid
from unittest.mock import patch

import pytest


def test_uuid_generation_in_publish(broker):
    """Test that the default _publish method generates UUID identifiers"""
    stream = "test_stream"
    message = {"foo": "bar"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Verify identifier is a valid UUID
    try:
        uuid_obj = uuid.UUID(identifier)
        assert isinstance(uuid_obj, uuid.UUID)
    except ValueError:
        pytest.fail("Identifier is not a valid UUID")

    # Publish another message and verify identifiers are unique
    identifier2 = broker.publish(stream, message)
    assert identifier != identifier2


def test_reliable_messaging_broker_publish_generates_uuid_format(broker):
    """Test that reliable messaging brokers generate UUID identifiers with correct format"""
    stream = "test_stream"
    message = {"data": "test"}

    # The publish method should generate a UUID
    identifier = broker.publish(stream, message)

    # Verify it's a valid UUID
    uuid.UUID(identifier)  # This will raise ValueError if invalid


def test_reliable_messaging_broker_retrieved_message_has_uuid_identifier(broker):
    """Test that retrieved messages have UUID identifiers for manual brokers"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    original_message = {"foo": "bar", "data": {"count": 42}}

    broker.publish(stream, original_message)
    identifier, retrieved_message = broker.get_next(stream, consumer_group)

    # Verify retrieved message matches original
    assert retrieved_message == original_message

    # Verify identifier is a UUID
    assert uuid.UUID(identifier) is not None


def test_reliable_messaging_broker_get_next_generates_uuid_identifier(broker):
    """Test that get_next returns messages with UUID identifiers for manual brokers"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get the message
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    retrieved_identifier, retrieved_payload = retrieved_message

    assert retrieved_identifier == identifier
    assert uuid.UUID(retrieved_identifier) is not None


def test_exception_during_ack_returns_false(broker):
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Mock _validate_consumer_group to raise an exception
    with patch.object(
        broker,
        "_validate_consumer_group",
        side_effect=Exception("Test exception"),
    ):
        # This should catch the exception and return False
        ack_result = broker.ack(stream, identifier, consumer_group)
        assert ack_result is False


def test_exception_during_ack_cleanup_message_ownership_returns_false(broker):
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Mock _cleanup_message_ownership to raise an exception at the very end of ack processing
    with patch.object(
        broker,
        "_cleanup_message_ownership",
        side_effect=Exception("Cleanup failed"),
    ):
        # Mock _clear_operation_state to verify the cleanup in exception block is called
        with patch.object(broker, "_clear_operation_state") as mock_clear:
            ack_result = broker.ack(stream, identifier, consumer_group)
            assert ack_result is False
            # Verify that the exception handler called _clear_operation_state
            mock_clear.assert_called_once_with(consumer_group, identifier)


def test_ack_operation_state_cleanup_on_exception(broker):
    """Test that operation state is cleaned up when exception occurs in ack"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Mock _remove_in_flight_message to raise an exception after validation passes
    original_remove = broker._remove_in_flight_message

    def mock_remove(*args, **kwargs):
        # First call the original to pass validation
        original_remove(*args, **kwargs)
        # Then raise exception
        raise Exception("Test exception during cleanup")

    with patch.object(
        broker,
        "_remove_in_flight_message",
        side_effect=mock_remove,
    ):
        # Mock _clear_operation_state to verify it gets called
        with patch.object(broker, "_clear_operation_state") as mock_clear:
            ack_result = broker.ack(stream, identifier, consumer_group)
            assert ack_result is False
            # Verify cleanup was called
            mock_clear.assert_called_once_with(consumer_group, identifier)


def test_exception_during_nack_returns_false(broker):
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Mock _validate_consumer_group to raise an exception
    with patch.object(
        broker,
        "_validate_consumer_group",
        side_effect=Exception("Test exception"),
    ):
        # This should catch the exception and return False
        nack_result = broker.nack(stream, identifier, consumer_group)
        assert nack_result is False


def test_exception_during_nack_operation_state_cleanup_on_exception(broker):
    """Test that operation state is cleaned up when exception occurs in nack"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Mock _get_in_flight_message to raise an exception after validation passes
    with patch.object(
        broker,
        "_get_in_flight_message",
        side_effect=Exception("Test exception"),
    ):
        # Mock _clear_operation_state to verify it gets called
        with patch.object(broker, "_clear_operation_state") as mock_clear:
            nack_result = broker.nack(stream, identifier, consumer_group)
            assert nack_result is False
            # Verify cleanup was called
            mock_clear.assert_called_once_with(consumer_group, identifier)


def test_exception_during_nack_with_retry_returns_false(broker):
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Mock _store_operation_state to raise an exception
    with patch.object(
        broker,
        "_store_operation_state",
        side_effect=Exception("Test exception"),
    ):
        # Mock _clear_operation_state to verify it gets called
        with patch.object(broker, "_clear_operation_state") as mock_clear:
            nack_result = broker.nack(stream, identifier, consumer_group)
            assert nack_result is False
            # Verify cleanup was called
            mock_clear.assert_called_once_with(consumer_group, identifier)


def test_exception_during_nack_with_retry_store_failed_message_returns_false(
    broker,
):
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Mock _store_failed_message to raise an exception at the very end of _handle_nack_with_retry
    with patch.object(
        broker,
        "_store_failed_message",
        side_effect=Exception("Store failed message failed"),
    ):
        # Mock _clear_operation_state to verify the cleanup in exception block is called
        with patch.object(broker, "_clear_operation_state") as mock_clear:
            nack_result = broker.nack(stream, identifier, consumer_group)
            assert nack_result is False
            # Verify that the exception handler called _clear_operation_state
            mock_clear.assert_called_once_with(consumer_group, identifier)


def test_exception_during_nack_max_retries_exceeded_with_retry_message(broker):
    """Test exception handling in _handle_nack_max_retries_exceeded method when retry message is available"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with max retries = 1 for quick testing
    broker._max_retries = 1
    broker._retry_delay = 0.01  # Very short delay

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # First nack - should succeed
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Wait for retry and get message again
    time.sleep(0.02)
    retrieved_message = broker.get_next(stream, consumer_group)

    assert retrieved_message is not None

    # Mock _store_operation_state to raise an exception on the second nack (max retries exceeded)
    with patch.object(
        broker,
        "_store_operation_state",
        side_effect=Exception("Test exception"),
    ):
        # Mock _clear_operation_state to verify it gets called
        with patch.object(broker, "_clear_operation_state") as mock_clear:
            # Second nack should trigger max retries exceeded path and handle exception
            nack_result = broker.nack(stream, identifier, consumer_group)
            assert nack_result is False
            # Verify cleanup was called
            mock_clear.assert_called_once_with(consumer_group, identifier)


def test_exception_during_nack_max_retries_exceeded_with_simulated_condition(
    broker,
):
    """Test exception handling in _handle_nack_max_retries_exceeded method by simulating max retries condition"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with max retries = 1 for quick testing
    broker._max_retries = 1

    # Create a new message to test the exception path
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Mock the retry count to simulate max retries exceeded condition
    with patch.object(
        broker,
        "_get_retry_count",
        return_value=broker._max_retries,
    ):
        # Mock _store_operation_state to raise an exception
        with patch.object(
            broker,
            "_store_operation_state",
            side_effect=Exception("Test exception"),
        ):
            # Mock _clear_operation_state to verify it gets called
            with patch.object(broker, "_clear_operation_state") as mock_clear:
                nack_result = broker.nack(stream, identifier, consumer_group)
                assert nack_result is False
                # Verify cleanup was called
                mock_clear.assert_called_once_with(consumer_group, identifier)


def test_exception_during_requeue_failed_messages_returns_none(broker):
    """Test exception handling in _requeue_failed_messages method"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker for testing
    broker._retry_delay = 0.01  # Very short delay

    # Publish and nack a message to create a failed message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Wait for retry delay
    time.sleep(0.02)

    # Mock _get_retry_ready_messages to raise an exception
    with patch.object(
        broker,
        "_get_retry_ready_messages",
        side_effect=Exception("Test exception"),
    ):
        # This should catch the exception and continue (not crash)
        # The get_next call will trigger _requeue_failed_messages internally
        result = broker.get_next(stream, consumer_group)
        # Should not crash and return None due to exception
        assert result is None


def test_exception_during_requeue_messages_returns_none(broker):
    """Test exception handling when _requeue_messages raises exception"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker for testing
    broker._retry_delay = 0.01  # Very short delay

    # Publish and nack a message to create a failed message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Wait for retry delay
    time.sleep(0.02)

    # Mock _requeue_messages to raise an exception
    with patch.object(
        broker,
        "_requeue_messages",
        side_effect=Exception("Test exception"),
    ):
        # This should catch the exception in _requeue_failed_messages and continue
        # The get_next call will trigger _requeue_failed_messages internally
        result = broker.get_next(stream, consumer_group)
        # Should not crash but may return None due to exception
        # The important thing is that it doesn't propagate the exception
        assert result is None


def test_exception_during_mixed_scenarios(broker):
    """Test various exception scenarios in sequence to ensure robustness"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Test that the broker continues to work even after exceptions

    # 1. Publish succeeds
    identifier1 = broker.publish(stream, message)
    assert identifier1 is not None

    # 2. Get message and cause ack exception
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    with patch.object(
        broker,
        "_validate_consumer_group",
        side_effect=Exception("Test exception"),
    ):
        ack_result = broker.ack(stream, identifier1, consumer_group)
        assert ack_result is False

    # 3. The message should still be in-flight due to exception, but broker should continue to work
    # Publish a new message to test that the broker is still functioning
    identifier_new = broker.publish(stream, {"new": "message"})
    retrieved_message_new = broker.get_next(stream, consumer_group)
    assert retrieved_message_new is not None

    # 4. Normal ack should work on the new message
    ack_result = broker.ack(stream, identifier_new, consumer_group)
    assert ack_result is True

    # 5. Try to manually cleanup the original message
    try:
        # Try to ack the original message again (should still be in-flight)
        ack_result = broker.ack(stream, identifier1, consumer_group)
        # May succeed or fail depending on broker state, but shouldn't crash
    except Exception:
        # Exception is acceptable here since the message is in an inconsistent state
        pass

    # 6. Publish another message and test nack exception
    identifier2 = broker.publish(stream, message)
    retrieved_message3 = broker.get_next(stream, consumer_group)
    assert retrieved_message3 is not None

    with patch.object(
        broker,
        "_validate_consumer_group",
        side_effect=Exception("Test exception"),
    ):
        nack_result = broker.nack(stream, identifier2, consumer_group)
        assert nack_result is False

    # 7. Normal nack should work after exception (create fresh message)
    identifier3 = broker.publish(stream, message)
    retrieved_message4 = broker.get_next(stream, consumer_group)
    assert retrieved_message4 is not None
    nack_result = broker.nack(stream, identifier3, consumer_group)
    assert nack_result is True


def test_exception_during_ack_logger_error_returns_false(broker):
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Mock logger.debug to raise an exception at the very end of successful ack processing
    import protean.adapters.broker.inline

    original_debug = protean.adapters.broker.inline.logger.debug

    def mock_debug(msg, *args, **kwargs):
        if "acknowledged by consumer group" in msg:
            raise Exception("Logger debug failed")
        return original_debug(msg, *args, **kwargs)

    with patch.object(
        protean.adapters.broker.inline.logger, "debug", side_effect=mock_debug
    ):
        # Mock _clear_operation_state to verify the cleanup in exception block is called
        with patch.object(broker, "_clear_operation_state") as mock_clear:
            ack_result = broker.ack(stream, identifier, consumer_group)
            assert ack_result is False
            # Verify that the exception handler called _clear_operation_state
            mock_clear.assert_called_once_with(consumer_group, identifier)


def test_exception_during_nack_with_retry_logger_error_returns_false(broker):
    # Simulates logger.debug with exception
    import logging

    def mock_debug(msg, *args, **kwargs):
        raise Exception("Logger debug failed")

    with patch.object(logging.getLogger(), "debug", side_effect=mock_debug):
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"foo": "bar"}

        # Publish and get a message
        identifier = broker.publish(stream, message)
        retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message is not None

        # Nack should still work despite logger error
        nack_result = broker.nack(stream, identifier, consumer_group)
        # The operation should succeed despite logger error
        assert nack_result is True


def test_validate_message_ownership_exception_handling(broker):
    """Test that _validate_message_ownership handles exceptions gracefully"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message to set up ownership
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Mock underlying ownership validation to raise exception (for Redis-specific brokers)
    if hasattr(broker, "redis_instance"):
        with patch.object(
            broker.redis_instance, "smembers", side_effect=Exception("Redis error")
        ):
            # Should return False when exception occurs
            result = broker._validate_message_ownership(identifier, consumer_group)
            assert result is False
    elif hasattr(broker, "_message_ownership"):
        # For inline broker, test the exception in the validation logic
        # This is harder to trigger but we can test with corrupted data
        original_ownership = broker._message_ownership[identifier]
        try:
            # Replace with a non-dict value to trigger exception in validation
            broker._message_ownership[identifier] = "corrupted_data"
            result = broker._validate_message_ownership(identifier, consumer_group)
            # Should handle gracefully and return False
            assert result is False
        finally:
            # Restore original state
            broker._message_ownership[identifier] = original_ownership


def test_get_retry_count_exception_handling(broker):
    """Test that _get_retry_count handles exceptions gracefully"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    identifier = "test_identifier"

    # For Redis-based brokers, test exception handling
    if hasattr(broker, "redis_instance"):
        with patch.object(
            broker.redis_instance,
            "hget",
            side_effect=Exception("Redis connection error"),
        ):
            # Should return 0 when exception occurs
            result = broker._get_retry_count(stream, consumer_group, identifier)
            assert result == 0
    else:
        # For inline broker, this is harder to trigger exceptions
        # But we can test the exception path by corrupting internal state
        group_key = f"{stream}:{consumer_group}"
        original_data = broker._retry_counts.get(group_key, {})
        try:
            # Create a scenario that might cause exception in counting
            broker._retry_counts[group_key] = {"corrupted": "non_integer_value"}
            # This should still work and return 0 for non-existent identifier
            result = broker._get_retry_count(stream, consumer_group, identifier)
            assert result == 0
        finally:
            # Restore original state
            broker._retry_counts[group_key] = original_data


@pytest.mark.skip(reason="This test is flaky and needs to be fixed")
def test_cleanup_stale_messages_exception_in_processing(broker):
    """Test exception handling during stale message processing"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message to create in-flight status
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # For Redis-based brokers, test JSON parsing exceptions
    if hasattr(broker, "redis_instance"):
        # Mock hgetall to return corrupted JSON data
        def mock_hgetall(key):
            if b"in_flight" in key or "in_flight" in str(key):
                return {identifier.encode(): b"corrupted_json_data"}
            return {}

        with patch.object(broker.redis_instance, "hgetall", side_effect=mock_hgetall):
            # Should handle JSON parsing exceptions gracefully
            try:
                broker._cleanup_stale_messages(consumer_group, 10.0)
                # Should not raise exception
            except Exception as e:
                pytest.fail(
                    f"_cleanup_stale_messages should handle JSON exceptions gracefully: {e}"
                )

    # Test exception in general cleanup processing
    with patch.object(
        broker, "_store_dlq_message", side_effect=Exception("DLQ storage failed")
    ):
        try:
            broker._cleanup_stale_messages(consumer_group, 0.001)  # Very short timeout
            # Should handle DLQ storage exceptions gracefully
        except Exception as e:
            pytest.fail(
                f"_cleanup_stale_messages should handle DLQ exceptions gracefully: {e}"
            )


def test_requeue_messages_exception_handling(broker):
    """Test that _requeue_messages handles exceptions gracefully"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    messages = [("test_id", {"data": "test"})]

    # For Redis-based brokers, test Redis operation exceptions
    if hasattr(broker, "redis_instance"):
        with patch.object(
            broker.redis_instance, "get", side_effect=Exception("Redis get failed")
        ):
            # Should handle Redis exceptions gracefully and not crash
            try:
                broker._requeue_messages(stream, consumer_group, messages)
                # Should complete without raising exception
            except Exception as e:
                pytest.fail(
                    f"_requeue_messages should handle Redis exceptions gracefully: {e}"
                )

    # Test with empty messages (should return early)
    try:
        broker._requeue_messages(stream, consumer_group, [])
        # Should handle empty list gracefully
    except Exception as e:
        pytest.fail(f"_requeue_messages should handle empty messages gracefully: {e}")


def test_remove_failed_message_exception_handling(broker):
    """Test that _remove_failed_message handles exceptions gracefully"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    identifier = "test_identifier"

    # For Redis-based brokers, test exception handling
    if hasattr(broker, "redis_instance"):
        with patch.object(
            broker.redis_instance,
            "lrange",
            side_effect=Exception("Redis lrange failed"),
        ):
            # Should handle exceptions gracefully and not crash
            try:
                broker._remove_failed_message(stream, consumer_group, identifier)
                # Should complete without raising exception
            except Exception as e:
                pytest.fail(
                    f"_remove_failed_message should handle Redis exceptions gracefully: {e}"
                )

    # Test removal of non-existent message
    try:
        broker._remove_failed_message(stream, consumer_group, "non_existent_id")
        # Should handle non-existent messages gracefully
    except Exception as e:
        pytest.fail(
            f"_remove_failed_message should handle non-existent messages gracefully: {e}"
        )


def test_get_in_flight_message_nonexistent(broker):
    """Test getting in-flight message data when message doesn't exist"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    non_existent_identifier = "non-existent-id"

    # Ensure consumer group exists
    broker._ensure_group(consumer_group, stream)

    # Try to get non-existent in-flight message
    result = broker._get_in_flight_message(
        stream, consumer_group, non_existent_identifier
    )

    # Should return None for non-existent message
    assert result is None
