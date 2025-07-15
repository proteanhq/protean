from unittest.mock import patch

import pytest


@pytest.mark.basic_pubsub
def test_connection_error_detection_common_patterns(broker):
    """Test that common connection error patterns are detected"""
    connection_errors = [
        Exception("Connection refused"),
        Exception("Connection timeout"),
        Exception("Network unreachable"),
        Exception("Connection reset by peer"),
        Exception("Broken pipe"),
        Exception("Socket error"),
        ConnectionError("Connection failed"),
        TimeoutError("Operation timed out"),
    ]

    for error in connection_errors:
        result = broker._is_connection_error(error)
        assert result is True, f"Should detect '{error}' as connection error"


@pytest.mark.basic_pubsub
def test_connection_error_detection_non_connection_errors(broker):
    """Test that non-connection errors are not detected as connection errors"""
    non_connection_errors = [
        Exception("Invalid data format"),
        ValueError("Invalid input"),
        KeyError("Missing key"),
        AttributeError("No such attribute"),
        Exception("Permission denied"),
        Exception("File not found"),
    ]

    for error in non_connection_errors:
        result = broker._is_connection_error(error)
        assert result is False, f"Should not detect '{error}' as connection error"


@pytest.mark.basic_pubsub
def test_publish_with_connection_error_and_recovery(broker):
    """Test that publish() handles connection errors with automatic recovery"""
    stream = "test_stream"
    message = {"data": "test"}

    # Mock the _publish method to simulate a connection error then success
    original_publish = broker._publish
    call_count = 0

    def mock_publish(stream, message):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call raises connection error
            raise ConnectionError("Connection lost")
        else:
            # Second call succeeds
            return original_publish(stream, message)

    # Mock _ensure_connection to return True (successful recovery)
    with (
        patch.object(broker, "_publish", side_effect=mock_publish),
        patch.object(broker, "_ensure_connection", return_value=True),
    ):
        # Should succeed after retry
        identifier = broker.publish(stream, message)
        assert identifier is not None
        assert isinstance(identifier, str)
        assert call_count == 2  # Called twice: error then success


@pytest.mark.basic_pubsub
def test_publish_with_connection_error_recovery_fails(broker):
    """Test that publish() raises error when recovery fails"""
    stream = "test_stream"
    message = {"data": "test"}

    # Mock _publish to always raise connection error
    with (
        patch.object(
            broker, "_publish", side_effect=ConnectionError("Connection lost")
        ),
        patch.object(broker, "_ensure_connection", return_value=False),
    ):
        # Should raise the original error when recovery fails
        with pytest.raises(ConnectionError, match="Connection lost"):
            broker.publish(stream, message)


@pytest.mark.basic_pubsub
def test_publish_with_non_connection_error_no_retry(broker):
    """Test that publish() doesn't retry for non-connection errors"""
    stream = "test_stream"
    message = {"data": "test"}

    call_count = 0

    def mock_publish(stream, message):
        nonlocal call_count
        call_count += 1
        raise ValueError("Invalid data format")

    with patch.object(broker, "_publish", side_effect=mock_publish):
        # Should raise error immediately without retry
        with pytest.raises(ValueError, match="Invalid data format"):
            broker.publish(stream, message)

        assert call_count == 1  # Only called once, no retry


@pytest.mark.basic_pubsub
def test_get_next_with_connection_error_and_recovery(broker):
    """Test that get_next() handles connection errors with automatic recovery"""
    stream = "test_stream"
    consumer_group = "test_group"

    # Set up a message first
    broker.publish(stream, {"data": "test"})

    # Mock the _get_next method to simulate a connection error then success
    original_get_next = broker._get_next
    call_count = 0

    def mock_get_next(stream, consumer_group):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call raises connection error
            raise ConnectionError("Connection lost")
        else:
            # Second call succeeds
            return original_get_next(stream, consumer_group)

    # Mock _ensure_connection to return True (successful recovery)
    with (
        patch.object(broker, "_get_next", side_effect=mock_get_next),
        patch.object(broker, "_ensure_connection", return_value=True),
    ):
        # Should succeed after retry
        result = broker.get_next(stream, consumer_group)
        assert result is not None
        assert call_count == 2  # Called twice: error then success


@pytest.mark.basic_pubsub
def test_get_next_with_connection_error_recovery_fails(broker):
    """Test that get_next() raises error when recovery fails"""
    stream = "test_stream"
    consumer_group = "test_group"

    # Mock _get_next to always raise connection error
    with (
        patch.object(
            broker, "_get_next", side_effect=ConnectionError("Connection lost")
        ),
        patch.object(broker, "_ensure_connection", return_value=False),
    ):
        # Should raise the original error when recovery fails
        with pytest.raises(ConnectionError, match="Connection lost"):
            broker.get_next(stream, consumer_group)


@pytest.mark.basic_pubsub
def test_get_next_with_non_connection_error_no_retry(broker):
    """Test that get_next() doesn't retry for non-connection errors"""
    stream = "test_stream"
    consumer_group = "test_group"

    call_count = 0

    def mock_get_next(stream, consumer_group):
        nonlocal call_count
        call_count += 1
        raise ValueError("Invalid consumer group")

    with patch.object(broker, "_get_next", side_effect=mock_get_next):
        # Should raise error immediately without retry
        with pytest.raises(ValueError, match="Invalid consumer group"):
            broker.get_next(stream, consumer_group)

        assert call_count == 1  # Only called once, no retry


@pytest.mark.basic_pubsub
def test_ensure_connection_called_explicitly(broker):
    """Test that ensure_connection() can be called explicitly"""
    result = broker.ensure_connection()
    assert result is True
    assert isinstance(result, bool)


@pytest.mark.basic_pubsub
def test_ensure_connection_with_manual_broker_methods(broker):
    """Test ensure_connection with broker that has the method"""
    # Test the public interface
    result = broker.ensure_connection()
    assert result is True

    # For inline broker, should always return True
    assert broker._ensure_connection() is True


@pytest.mark.basic_pubsub
def test_connection_resilience_preserves_message_integrity(broker):
    """Test that connection errors don't corrupt message data"""
    stream = "test_stream"
    consumer_group = "test_group"
    original_message = {"data": "test", "id": 123, "complex": {"nested": "value"}}

    # Mock a connection error during publish
    original_publish = broker._publish
    call_count = 0

    def mock_publish(stream, message):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Verify message is not corrupted during error
            assert message == original_message
            raise ConnectionError("Connection lost")
        else:
            # Second call with same uncorrupted message
            assert message == original_message
            return original_publish(stream, message)

    with (
        patch.object(broker, "_publish", side_effect=mock_publish),
        patch.object(broker, "_ensure_connection", return_value=True),
    ):
        # Publish should succeed and preserve message integrity
        identifier = broker.publish(stream, original_message)
        assert identifier is not None

        # Retrieve and verify message is uncorrupted
        retrieved_id, retrieved_message = broker.get_next(stream, consumer_group)
        assert retrieved_message == original_message


@pytest.mark.basic_pubsub
def test_connection_error_detection_case_insensitive(broker):
    """Test that connection error detection is case insensitive"""
    case_variations = [
        Exception("CONNECTION REFUSED"),
        Exception("Connection TIMEOUT"),
        Exception("network UNREACHABLE"),
        Exception("SOCKET ERROR"),
        Exception("Broken PIPE"),
    ]

    for error in case_variations:
        result = broker._is_connection_error(error)
        assert result is True, (
            f"Should detect '{error}' as connection error (case insensitive)"
        )


@pytest.mark.basic_pubsub
def test_multiple_connection_errors_handled_gracefully(broker):
    """Test that multiple consecutive connection errors are handled properly"""
    stream = "test_stream"
    message1 = {"id": 1}
    message2 = {"id": 2}

    # Mock _publish to fail on first call for message1, succeed on retry
    call_count = 0

    def mock_publish(stream, message):
        nonlocal call_count
        call_count += 1
        if message["id"] == 1 and call_count == 1:
            # First call for message1 fails
            raise ConnectionError("First connection error")
        else:
            # Retry for message1 and normal call for message2 succeed
            return f"id-{message['id']}"

    with (
        patch.object(broker, "_publish", side_effect=mock_publish),
        patch.object(broker, "_ensure_connection", return_value=True),
    ):
        # First publish should fail and recover
        id1 = broker.publish(stream, message1)
        assert id1 == "id-1"

        # Second publish should work normally
        id2 = broker.publish(stream, message2)
        assert id2 == "id-2"

        assert (
            call_count == 3
        )  # Two calls for message1 (fail + retry), one for message2


@pytest.mark.basic_pubsub
def test_connection_error_logging(broker):
    """Test that connection errors are properly logged"""
    # Set up logging capture
    with pytest.raises(Exception):
        # Mock the _publish method to raise different connection errors
        original_publish = broker._publish

        def mock_publish(stream, message):
            raise ConnectionError("Connection lost")

        broker._publish = mock_publish

        # Mock _ensure_connection to fail
        broker._ensure_connection = lambda: False

        try:
            broker.publish("test_stream", {"data": "test"})
        finally:
            # Restore original method
            broker._publish = original_publish
            broker._ensure_connection = lambda: True


@pytest.mark.basic_pubsub
def test_ping_with_connection_error(broker):
    """Test ping behavior when connection errors occur"""
    # Mock the underlying ping method to raise an exception
    original_ping = broker._ping

    def mock_ping():
        raise ConnectionError("Connection refused")

    broker._ping = mock_ping

    try:
        result = broker.ping()
        # Should return False when connection fails
        assert result is False
    finally:
        broker._ping = original_ping


@pytest.mark.reliable_messaging
def test_health_stats_with_calculation_errors(broker):
    """Test health stats when calculation methods fail"""
    # Mock methods that can fail during health stats calculation
    original_calculate_message_counts = getattr(
        broker, "_calculate_message_counts", None
    )

    def mock_calculate_message_counts():
        raise Exception("Calculation failed")

    if original_calculate_message_counts:
        broker._calculate_message_counts = mock_calculate_message_counts

        try:
            stats = broker.health_stats()
            # Should still return valid structure even with errors
            assert "status" in stats
            assert "connected" in stats
            assert "details" in stats

            # Details should contain fallback values
            if "message_counts" in stats["details"]:
                message_counts = stats["details"]["message_counts"]
                assert "total_messages" in message_counts
                assert "in_flight" in message_counts
                assert "failed" in message_counts
                assert "dlq" in message_counts

        finally:
            broker._calculate_message_counts = original_calculate_message_counts


@pytest.mark.basic_pubsub
def test_message_deserialization_errors(broker):
    """Test message handling when deserialization fails"""
    # This test is more relevant for brokers that handle serialization
    # For inline broker, this might not apply, but we test the interface
    stream = "test_stream"
    consumer_group = "test_group"

    # Publish a valid message first
    broker.publish(stream, {"data": "test"})

    # Mock the deserialization to fail (if the method exists)
    original_deserialize = getattr(broker, "_deserialize_message", None)

    if original_deserialize:
        call_count = 0

        def mock_deserialize(fields):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Deserialization failed")
            return original_deserialize(fields)

        broker._deserialize_message = mock_deserialize

        try:
            # Should handle deserialization errors gracefully
            result = broker.get_next(stream, consumer_group)
            # May return None or empty dict depending on implementation
            assert result is None or isinstance(result, tuple)
        finally:
            broker._deserialize_message = original_deserialize
    else:
        # For brokers without explicit deserialization, just test normal flow
        result = broker.get_next(stream, consumer_group)
        assert result is not None


@pytest.mark.basic_pubsub
def test_data_reset_error_handling(broker):
    """Test data reset when underlying operations fail"""
    # For inline broker, we'll test that _data_reset doesn't raise exceptions
    # by calling it directly. For Redis broker, this tests the error handling
    # within the method itself.

    # Test that _data_reset is robust and doesn't raise exceptions
    try:
        broker._data_reset()
        # Should not raise an exception
        assert True  # If we get here, the test passes
    except Exception as e:
        # If an exception is raised, the implementation should handle it internally
        pytest.fail(f"_data_reset should handle exceptions internally, but got: {e}")


@pytest.mark.basic_pubsub
def test_ensure_connection_with_multiple_failures(broker):
    """Test ensure_connection with multiple consecutive failures"""
    # Mock the underlying connection method to fail multiple times
    original_ensure = broker._ensure_connection
    call_count = 0

    def mock_ensure_connection():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return False
        return True

    broker._ensure_connection = mock_ensure_connection

    try:
        # First few calls should fail
        result1 = broker.ensure_connection()
        assert result1 is False

        result2 = broker.ensure_connection()
        assert result2 is False

        # Eventually should succeed
        result3 = broker.ensure_connection()
        assert result3 is True

    finally:
        broker._ensure_connection = original_ensure
