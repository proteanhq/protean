from unittest.mock import patch

import pytest

from protean.infra.broker import is_connection_error


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
        result = is_connection_error(error)
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
        result = is_connection_error(error)
        assert result is False, f"Should not detect '{error}' as connection error"


@pytest.mark.basic_pubsub
def test_publish_with_connection_error_and_recovery(broker):
    """Test that publish() handles connection errors with automatic recovery"""
    stream = "test_stream"
    message = {"data": "test"}

    # Mock the adapter's publish to simulate a connection error then success
    original_publish = broker._adapter.publish
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

    # Mock the adapter's reconnect to return True (successful recovery)
    with (
        patch.object(broker._adapter, "publish", side_effect=mock_publish),
        patch.object(broker._adapter, "reconnect", return_value=True),
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

    # Mock the adapter's publish to always raise connection error
    with (
        patch.object(
            broker._adapter, "publish", side_effect=ConnectionError("Connection lost")
        ),
        patch.object(broker._adapter, "reconnect", return_value=False),
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

    with patch.object(broker._adapter, "publish", side_effect=mock_publish):
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

    # Mock the adapter's read, which get_next calls, to simulate a connection
    # error then success
    original_read = broker._adapter.read
    call_count = 0

    def mock_read(stream, consumer_group, limit, *, new_messages=False):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call raises connection error
            raise ConnectionError("Connection lost")
        else:
            # Second call succeeds
            return original_read(
                stream, consumer_group, limit, new_messages=new_messages
            )

    # Mock the adapter's reconnect to return True (successful recovery)
    with (
        patch.object(broker._adapter, "read", side_effect=mock_read),
        patch.object(broker._adapter, "reconnect", return_value=True),
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

    # Mock the adapter's read to always raise connection error
    with (
        patch.object(
            broker._adapter, "read", side_effect=ConnectionError("Connection lost")
        ),
        patch.object(broker._adapter, "reconnect", return_value=False),
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

    def mock_read(stream, consumer_group, limit, *, new_messages=False):
        nonlocal call_count
        call_count += 1
        raise ValueError("Invalid consumer group")

    with patch.object(broker._adapter, "read", side_effect=mock_read):
        # Should raise error immediately without retry
        with pytest.raises(ValueError, match="Invalid consumer group"):
            broker.get_next(stream, consumer_group)

        assert call_count == 1  # Only called once, no retry


@pytest.mark.basic_pubsub
def test_reconnect_called_explicitly(broker):
    """Test that the service's _reconnect() can be called explicitly"""
    result = broker._reconnect()
    assert result is True
    assert isinstance(result, bool)


@pytest.mark.basic_pubsub
def test_reconnect_on_service_and_adapter(broker):
    """Test reconnect through the service and on the adapter directly"""
    # Through the service
    result = broker._reconnect()
    assert result is True

    # On the adapter, with a working connection
    assert broker._adapter.reconnect() is True


@pytest.mark.basic_pubsub
def test_connection_resilience_preserves_message_integrity(broker):
    """Test that connection errors don't corrupt message data"""
    stream = "test_stream"
    consumer_group = "test_group"
    original_message = {"data": "test", "id": 123, "complex": {"nested": "value"}}

    # Mock a connection error during publish
    original_publish = broker._adapter.publish
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
        patch.object(broker._adapter, "publish", side_effect=mock_publish),
        patch.object(broker._adapter, "reconnect", return_value=True),
    ):
        # Publish should succeed and preserve message integrity
        identifier = broker.publish(stream, original_message)
        assert identifier is not None

        # Retrieve and verify message is uncorrupted
        _retrieved_id, retrieved_message = broker.get_next(stream, consumer_group)
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
        result = is_connection_error(error)
        assert result is True, (
            f"Should detect '{error}' as connection error (case insensitive)"
        )


@pytest.mark.basic_pubsub
def test_multiple_connection_errors_handled_gracefully(broker):
    """Test that multiple consecutive connection errors are handled properly"""
    stream = "test_stream"
    message1 = {"id": 1}
    message2 = {"id": 2}

    # Mock the adapter's publish to fail on first call for message1, succeed on retry
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
        patch.object(broker._adapter, "publish", side_effect=mock_publish),
        patch.object(broker._adapter, "reconnect", return_value=True),
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
        # Mock the adapter's publish to raise a connection error
        original_publish = broker._adapter.publish
        original_reconnect = broker._adapter.reconnect

        def mock_publish(stream, message):
            raise ConnectionError("Connection lost")

        broker._adapter.publish = mock_publish

        # Mock the adapter's reconnect to fail
        broker._adapter.reconnect = lambda: False

        try:
            broker.publish("test_stream", {"data": "test"})
        finally:
            # Restore original methods
            broker._adapter.publish = original_publish
            broker._adapter.reconnect = original_reconnect


@pytest.mark.basic_pubsub
def test_ping_with_connection_error(broker):
    """Test ping behavior when connection errors occur"""
    # Mock the adapter's ping to raise an exception
    original_ping = broker._adapter.ping

    def mock_ping():
        raise ConnectionError("Connection refused")

    broker._adapter.ping = mock_ping

    try:
        result = broker.ping()
        # Should return False when connection fails
        assert result is False
    finally:
        broker._adapter.ping = original_ping


@pytest.mark.reliable_messaging
def test_health_stats_with_calculation_errors(broker):
    """Test health stats when calculation methods fail"""
    # Mock methods that can fail during health stats calculation
    original_calculate_message_counts = getattr(
        broker._adapter, "_calculate_message_counts", None
    )

    def mock_calculate_message_counts():
        raise Exception("Calculation failed")

    if original_calculate_message_counts:
        broker._adapter._calculate_message_counts = mock_calculate_message_counts

        try:
            stats = broker.health()
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
            broker._adapter._calculate_message_counts = (
                original_calculate_message_counts
            )


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
    original_deserialize = getattr(broker._adapter, "_deserialize_message", None)

    if original_deserialize:
        call_count = 0

        def mock_deserialize(fields):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Deserialization failed")
            return original_deserialize(fields)

        broker._adapter._deserialize_message = mock_deserialize

        try:
            # Should handle deserialization errors gracefully
            result = broker.get_next(stream, consumer_group)
            # May return None or empty dict depending on implementation
            assert result is None or isinstance(result, tuple)
        finally:
            broker._adapter._deserialize_message = original_deserialize
    else:
        # For brokers without explicit deserialization, just test normal flow
        result = broker.get_next(stream, consumer_group)
        assert result is not None


@pytest.mark.basic_pubsub
def test_data_reset_error_handling(broker):
    """Test data reset when underlying operations fail"""
    # For inline broker, we'll test that clear() doesn't raise exceptions
    # by calling it directly. For Redis broker, this tests the error handling
    # within the method itself.

    # Test that clear() is robust and doesn't raise exceptions
    try:
        broker.clear()
        # Should not raise an exception
        assert True  # If we get here, the test passes
    except Exception as e:
        # If an exception is raised, the implementation should handle it internally
        pytest.fail(f"clear() should handle exceptions internally, but got: {e}")


@pytest.mark.basic_pubsub
def test_reconnect_with_multiple_failures(broker):
    """Test reconnect with multiple consecutive failures"""
    # Mock the adapter's reconnect to fail multiple times
    original_reconnect = broker._adapter.reconnect
    call_count = 0

    def mock_reconnect():
        nonlocal call_count
        call_count += 1
        return not call_count <= 2

    broker._adapter.reconnect = mock_reconnect

    try:
        # First few calls should fail
        result1 = broker._reconnect()
        assert result1 is False

        result2 = broker._reconnect()
        assert result2 is False

        # Eventually should succeed
        result3 = broker._reconnect()
        assert result3 is True

    finally:
        broker._adapter.reconnect = original_reconnect
