import time
import uuid
from unittest.mock import patch

import pytest


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
def test_exception_during_ack_logger_error_returns_false(broker):
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Mock logger.debug to raise an exception at the very end of successful ack processing
    import protean.port.broker

    original_debug = protean.port.broker.logger.debug

    def mock_debug(msg, *args, **kwargs):
        if "acknowledged by consumer group" in msg:
            raise Exception("Logger debug failed")
        return original_debug(msg, *args, **kwargs)

    with patch.object(protean.port.broker.logger, "debug", side_effect=mock_debug):
        # Mock _clear_operation_state to verify the cleanup in exception block is called
        with patch.object(broker, "_clear_operation_state") as mock_clear:
            ack_result = broker.ack(stream, identifier, consumer_group)
            assert ack_result is False
            # Verify that the exception handler called _clear_operation_state
            mock_clear.assert_called_once_with(consumer_group, identifier)


@pytest.mark.broker
def test_exception_during_nack_with_retry_logger_error_returns_false(broker):
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Mock logger.debug to raise an exception at the very end of successful _handle_nack_with_retry processing
    import protean.port.broker

    original_debug = protean.port.broker.logger.debug

    def mock_debug(msg, *args, **kwargs):
        if "nacked, retry" in msg and "in" in msg:
            raise Exception("Logger debug failed")
        return original_debug(msg, *args, **kwargs)

    with patch.object(protean.port.broker.logger, "debug", side_effect=mock_debug):
        # Mock _clear_operation_state to verify the cleanup in exception block is called
        with patch.object(broker, "_clear_operation_state") as mock_clear:
            nack_result = broker.nack(stream, identifier, consumer_group)
            assert nack_result is False
            # Verify that the exception handler called _clear_operation_state
            mock_clear.assert_called_once_with(consumer_group, identifier)
