"""Tests for read_blocking functionality in brokers."""

import pytest

from protean.port.broker import BrokerCapabilities


def test_read_blocking_fallback_for_unsupported_brokers(broker):
    """Test that read_blocking falls back to regular read for brokers without blocking support."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    consumer_name = "test_consumer"

    # Publish some messages
    messages = [{"id": i, "data": f"message_{i}"} for i in range(3)]
    for msg in messages:
        broker.publish(stream, msg)

    # For brokers that support blocking reads, we can temporarily disable the capability
    # to test the fallback behavior
    original_capabilities = broker.capabilities
    had_blocking_read = broker.has_capability(BrokerCapabilities.BLOCKING_READ)

    # If broker supports blocking reads, temporarily remove that capability
    if had_blocking_read:
        # Monkey-patch the capabilities property to exclude BLOCKING_READ
        new_capabilities = original_capabilities & ~BrokerCapabilities.BLOCKING_READ
        type(broker).capabilities = property(lambda self: new_capabilities)

    try:
        # Call read_blocking - should either use _read_blocking or fall back to regular _read
        result = broker.read_blocking(
            stream=stream,
            consumer_group=consumer_group,
            consumer_name=consumer_name,
            timeout_ms=1000,
            count=2,
        )

        # Should get messages either way
        assert len(result) <= 2
        if result:
            # Verify we got tuples of (identifier, message)
            for item in result:
                assert isinstance(item, tuple)
                assert len(item) == 2
                identifier, message = item
                assert isinstance(identifier, str)
                assert isinstance(message, dict)

    finally:
        # Restore original capabilities if we modified them
        if had_blocking_read:
            type(broker).capabilities = property(lambda self: original_capabilities)


def test_read_blocking_with_supported_broker(broker):
    """Test read_blocking with brokers that support it."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    consumer_name = "test_consumer"

    # Publish messages
    messages = [{"id": i, "data": f"message_{i}"} for i in range(3)]
    for msg in messages:
        broker.publish(stream, msg)

    # Check if broker supports blocking reads
    if broker.has_capability(BrokerCapabilities.BLOCKING_READ):
        # Test with blocking read
        result = broker.read_blocking(
            stream=stream,
            consumer_group=consumer_group,
            consumer_name=consumer_name,
            timeout_ms=1000,
            count=2,
        )

        # Should get up to 2 messages
        assert len(result) <= 2
        if result:
            for item in result:
                assert isinstance(item, tuple)
                assert len(item) == 2
                identifier, message = item
                assert isinstance(identifier, str)
                assert isinstance(message, dict)
    else:
        # For brokers without blocking support, it should still work via fallback
        result = broker.read_blocking(
            stream=stream,
            consumer_group=consumer_group,
            consumer_name=consumer_name,
            timeout_ms=1000,
            count=2,
        )

        # Should work through fallback
        assert isinstance(result, list)


def test_read_blocking_with_connection_error_recovery(broker):
    """Test that read_blocking handles connection errors and attempts recovery."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    consumer_name = "test_consumer"

    # Publish a message
    broker.publish(stream, {"test": "data"})

    # For brokers that support blocking reads, we need to test connection error handling
    if broker.has_capability(BrokerCapabilities.BLOCKING_READ):
        # Store original method
        original_read_blocking = broker._read_blocking

        # Create a mock that simulates connection error on first call, then succeeds
        call_count = [0]

        def mock_read_blocking(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call raises a connection error
                raise Exception("Connection refused")
            else:
                # Second call succeeds
                return original_read_blocking(*args, **kwargs)

        # Replace the method
        broker._read_blocking = mock_read_blocking

        try:
            # This should trigger error handling and retry
            result = broker.read_blocking(
                stream=stream,
                consumer_group=consumer_group,
                consumer_name=consumer_name,
                timeout_ms=1000,
                count=1,
            )

            # Should eventually succeed
            assert isinstance(result, list)

        finally:
            # Restore original method
            broker._read_blocking = original_read_blocking

    else:
        # For brokers without blocking read support, the fallback path doesn't have
        # connection error handling at the read_blocking level.
        # Just verify the fallback works normally
        result = broker.read_blocking(
            stream=stream,
            consumer_group=consumer_group,
            consumer_name=consumer_name,
            timeout_ms=1000,
            count=1,
        )

        # Should work through fallback
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0][1] == {"test": "data"}


def test_read_blocking_with_non_connection_error(broker):
    """Test that read_blocking properly propagates non-connection errors."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    consumer_name = "test_consumer"

    # Test with an error that's not connection-related
    if broker.has_capability(BrokerCapabilities.BLOCKING_READ):
        original_read_blocking = broker._read_blocking

        def mock_read_blocking_error(*args, **kwargs):  # noqa: ARG001
            raise ValueError("Invalid argument")

        broker._read_blocking = mock_read_blocking_error

        try:
            # This should raise the error without retry
            with pytest.raises(ValueError, match="Invalid argument"):
                broker.read_blocking(
                    stream=stream,
                    consumer_group=consumer_group,
                    consumer_name=consumer_name,
                    timeout_ms=1000,
                    count=1,
                )
        finally:
            broker._read_blocking = original_read_blocking
    else:
        # Test fallback path with non-connection error
        original_read = broker._read

        def mock_read_error(*args, **kwargs):  # noqa: ARG001
            raise ValueError("Invalid argument")

        broker._read = mock_read_error

        try:
            # This should raise the error without retry
            with pytest.raises(ValueError, match="Invalid argument"):
                broker.read_blocking(
                    stream=stream,
                    consumer_group=consumer_group,
                    consumer_name=consumer_name,
                    timeout_ms=1000,
                    count=1,
                )
        finally:
            broker._read = original_read


def test_read_blocking_connection_recovery_failure(broker):
    """Test read_blocking when connection recovery fails."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    consumer_name = "test_consumer"

    # Store original _ensure_connection
    original_ensure_connection = broker._ensure_connection

    # Mock to simulate failed recovery
    def mock_ensure_connection_fail():
        return False

    broker._ensure_connection = mock_ensure_connection_fail

    try:
        if broker.has_capability(BrokerCapabilities.BLOCKING_READ):
            # For brokers with blocking read support
            original_read_blocking = broker._read_blocking

            def mock_read_blocking_error(*args, **kwargs):  # noqa: ARG001
                raise Exception("Connection reset by peer")

            broker._read_blocking = mock_read_blocking_error

            try:
                # Should raise the connection error since recovery fails
                with pytest.raises(Exception, match="Connection reset"):
                    broker.read_blocking(
                        stream=stream,
                        consumer_group=consumer_group,
                        consumer_name=consumer_name,
                        timeout_ms=1000,
                        count=1,
                    )
            finally:
                broker._read_blocking = original_read_blocking
        else:
            # For brokers using fallback
            original_read = broker._read

            def mock_read_error(*args, **kwargs):
                raise Exception("Network unreachable")

            broker._read = mock_read_error

            try:
                # Should raise the connection error since recovery fails
                with pytest.raises(Exception, match="Network unreachable"):
                    broker.read_blocking(
                        stream=stream,
                        consumer_group=consumer_group,
                        consumer_name=consumer_name,
                        timeout_ms=1000,
                        count=1,
                    )
            finally:
                broker._read = original_read

    finally:
        # Restore original method
        broker._ensure_connection = original_ensure_connection


def test_read_blocking_with_zero_timeout(broker):
    """Test read_blocking with zero timeout (block indefinitely)."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    consumer_name = "test_consumer"

    # Publish a message so we don't block forever
    broker.publish(stream, {"test": "data"})

    # Read with zero timeout (would block indefinitely if no messages)
    result = broker.read_blocking(
        stream=stream,
        consumer_group=consumer_group,
        consumer_name=consumer_name,
        timeout_ms=0,  # Block indefinitely (but we have a message)
        count=1,
    )

    # Should get the message
    assert len(result) == 1
    assert isinstance(result[0], tuple)
    assert result[0][1] == {"test": "data"}


def test_read_blocking_successful_retry_after_connection_error(broker):
    """Test that read_blocking successfully retries after connection error recovery."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    consumer_name = "test_consumer"

    # Publish messages
    broker.publish(stream, {"id": 1, "data": "message_1"})
    broker.publish(stream, {"id": 2, "data": "message_2"})

    if broker.has_capability(BrokerCapabilities.BLOCKING_READ):
        # Store original methods
        original_read_blocking = broker._read_blocking
        original_ensure_connection = broker._ensure_connection

        # Track calls
        call_count = [0]
        ensure_called = [False]

        def mock_read_blocking(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call raises a connection error
                raise Exception("Connection timed out")
            else:
                # Second call succeeds after recovery
                return original_read_blocking(*args, **kwargs)

        def mock_ensure_connection():
            ensure_called[0] = True
            return True  # Successful recovery

        # Replace methods
        broker._read_blocking = mock_read_blocking
        broker._ensure_connection = mock_ensure_connection

        try:
            # This should trigger error, recovery, and retry
            result = broker.read_blocking(
                stream=stream,
                consumer_group=consumer_group,
                consumer_name=consumer_name,
                timeout_ms=1000,
                count=2,
            )

            # Should have called ensure_connection
            assert ensure_called[0], "ensure_connection should have been called"

            # Should have retried and succeeded
            assert call_count[0] == 2, "Should have called _read_blocking twice"

            # Should get messages
            assert isinstance(result, list)
            assert len(result) > 0

        finally:
            # Restore original methods
            broker._read_blocking = original_read_blocking
            broker._ensure_connection = original_ensure_connection


def test_read_blocking_connection_error_without_recovery(broker):
    """Test read_blocking raises exception when connection cannot be recovered."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    consumer_name = "test_consumer"

    if broker.has_capability(BrokerCapabilities.BLOCKING_READ):
        # Store original methods
        original_read_blocking = broker._read_blocking
        original_ensure_connection = broker._ensure_connection

        # Track calls
        ensure_called = [False]

        def mock_read_blocking_error(*args, **kwargs):  # noqa: ARG001
            raise Exception("Socket closed")

        def mock_ensure_connection_fail():
            ensure_called[0] = True
            return False  # Recovery fails

        # Replace methods
        broker._read_blocking = mock_read_blocking_error
        broker._ensure_connection = mock_ensure_connection_fail

        try:
            # Should raise the connection error since recovery fails
            with pytest.raises(Exception, match="Socket closed"):
                broker.read_blocking(
                    stream=stream,
                    consumer_group=consumer_group,
                    consumer_name=consumer_name,
                    timeout_ms=1000,
                    count=1,
                )

            # Should have attempted recovery
            assert ensure_called[0], "ensure_connection should have been called"

        finally:
            # Restore original methods
            broker._read_blocking = original_read_blocking
            broker._ensure_connection = original_ensure_connection


def test_read_blocking_with_various_connection_errors(broker):
    """Test read_blocking handles various types of connection errors."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    consumer_name = "test_consumer"

    # Publish a message
    broker.publish(stream, {"test": "data"})

    if broker.has_capability(BrokerCapabilities.BLOCKING_READ):
        # Store original methods
        original_read_blocking = broker._read_blocking
        original_ensure_connection = broker._ensure_connection

        # Test various connection error messages
        connection_errors = [
            "Connection refused",
            "Connection timeout",
            "Network unreachable",
            "Connection reset by peer",
            "Broken pipe",
            "Socket error",
        ]

        for error_msg in connection_errors:
            call_count = [0]

            def mock_read_blocking(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise Exception(error_msg)
                else:
                    return original_read_blocking(*args, **kwargs)

            def mock_ensure_connection():
                return True

            broker._read_blocking = mock_read_blocking
            broker._ensure_connection = mock_ensure_connection

            try:
                # Should handle the connection error and retry
                result = broker.read_blocking(
                    stream=stream,
                    consumer_group=consumer_group,
                    consumer_name=consumer_name,
                    timeout_ms=1000,
                    count=1,
                )

                # Should have retried
                assert call_count[0] == 2, f"Should retry for error: {error_msg}"
                assert isinstance(result, list)

            finally:
                # Restore for next iteration
                broker._read_blocking = original_read_blocking
                broker._ensure_connection = original_ensure_connection


def test_read_blocking_connection_error_logging(broker, caplog):
    """Test that read_blocking logs connection errors properly."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    consumer_name = "test_consumer"

    if broker.has_capability(BrokerCapabilities.BLOCKING_READ):
        original_read_blocking = broker._read_blocking
        original_ensure_connection = broker._ensure_connection

        def mock_read_blocking_error(*args, **kwargs):  # noqa: ARG001
            raise Exception("Connection refused by broker")

        def mock_ensure_connection():
            return True  # Recovery succeeds

        broker._read_blocking = mock_read_blocking_error
        broker._ensure_connection = mock_ensure_connection

        # Temporarily replace _read_blocking to succeed on second call
        call_count = [0]

        def mock_read_blocking_retry(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Connection refused by broker")
            else:
                return []  # Return empty list on retry

        broker._read_blocking = mock_read_blocking_retry

        try:
            with caplog.at_level("WARNING"):
                result = broker.read_blocking(
                    stream=stream,
                    consumer_group=consumer_group,
                    consumer_name=consumer_name,
                    timeout_ms=1000,
                    count=1,
                )

                # Check that connection error was logged
                assert "Connection error during read_blocking" in caplog.text
                assert "Connection refused by broker" in caplog.text
                assert isinstance(result, list)

        finally:
            broker._read_blocking = original_read_blocking
            broker._ensure_connection = original_ensure_connection


def test_read_blocking_retry_after_successful_recovery(broker):
    """Test read_blocking successfully retries operation after connection recovery."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    consumer_name = "test_consumer"

    # Publish test messages
    broker.publish(stream, {"id": 1, "data": "message_1"})

    if broker.has_capability(BrokerCapabilities.BLOCKING_READ):
        original_read_blocking = broker._read_blocking
        original_ensure_connection = broker._ensure_connection

        # Track method calls
        read_blocking_calls = []
        ensure_connection_calls = []

        def mock_read_blocking(*args, **kwargs):
            read_blocking_calls.append((args, kwargs))
            if len(read_blocking_calls) == 1:
                # First call fails with connection error
                raise Exception("Connection timed out waiting for response")
            else:
                # Second call succeeds
                return original_read_blocking(*args, **kwargs)

        def mock_ensure_connection():
            ensure_connection_calls.append(True)
            return True  # Recovery successful

        broker._read_blocking = mock_read_blocking
        broker._ensure_connection = mock_ensure_connection

        try:
            result = broker.read_blocking(
                stream=stream,
                consumer_group=consumer_group,
                consumer_name=consumer_name,
                timeout_ms=1000,
                count=1,
            )

            # Verify the retry sequence
            assert len(read_blocking_calls) == 2, (
                "Should have called _read_blocking twice"
            )
            assert len(ensure_connection_calls) == 1, (
                "Should have called _ensure_connection once"
            )

            # Verify arguments were passed correctly on retry
            first_call_args = read_blocking_calls[0]
            second_call_args = read_blocking_calls[1]
            assert first_call_args == second_call_args, (
                "Retry should use same arguments"
            )

            # Should get results
            assert isinstance(result, list)
            assert len(result) > 0

        finally:
            broker._read_blocking = original_read_blocking
            broker._ensure_connection = original_ensure_connection
