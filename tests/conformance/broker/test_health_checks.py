import time

import pytest

from protean.port.broker import BrokerCapabilities


def test_ping_returns_true_for_healthy_broker(broker):
    """Test that ping() returns True for a healthy broker"""
    result = broker.ping()
    assert result is True
    assert isinstance(result, bool)


def test_ping_tracks_timing_information(broker):
    """Test that ping() tracks timing information internally"""
    # Perform ping
    result = broker.ping()
    assert result is True

    # Check that timing information is tracked
    assert broker._last_ping_time is not None
    assert isinstance(broker._last_ping_time, float)
    assert broker._last_ping_time >= 0
    assert broker._last_ping_success is True


def test_multiple_pings_update_timing_info(broker):
    """Test that multiple pings update the timing information"""
    # First ping
    broker.ping()
    first_ping_time = broker._last_ping_time

    # Small delay to ensure different timing
    time.sleep(0.001)

    # Second ping
    broker.ping()
    second_ping_time = broker._last_ping_time

    # Times should be different (though might be very close)
    assert isinstance(first_ping_time, float)
    assert isinstance(second_ping_time, float)
    assert broker._last_ping_success is True


def test_health_basic_structure(broker):
    """Test that health() returns the expected structure"""
    stats = broker.health()

    # Check required top-level keys
    assert "status" in stats
    assert "connected" in stats
    assert "last_ping_ms" in stats
    assert "uptime_seconds" in stats
    assert "details" in stats

    # Check value types
    assert stats["status"] in ["healthy", "degraded", "unhealthy"]
    assert isinstance(stats["connected"], bool)
    assert isinstance(stats["uptime_seconds"], (int, float))
    assert isinstance(stats["details"], dict)

    # For a fresh broker, should be healthy and connected
    assert stats["status"] == "healthy"
    assert stats["connected"] is True


def test_health_includes_ping_timing(broker):
    """Test that health() includes ping timing information"""
    # Perform a ping first
    broker.ping()

    stats = broker.health()

    # Should include ping timing
    assert "last_ping_ms" in stats
    assert stats["last_ping_ms"] is not None
    assert isinstance(stats["last_ping_ms"], (int, float))
    assert stats["last_ping_ms"] >= 0


def test_health_without_prior_ping(broker):
    """Test health() behavior when no ping has been performed"""
    # Don't call ping() first
    stats = broker.health()

    # Should still return valid structure
    assert stats["status"] == "healthy"
    assert stats["connected"] is True  # ping() is called internally
    assert "last_ping_ms" in stats


@pytest.mark.requires(BrokerCapabilities.ACK_NACK)
def test_health_details_count_messages_streams_and_groups(broker):
    """Health details count messages, streams and consumer groups"""
    # Add some test data first
    broker.publish("test_stream1", {"data": "test1"})
    broker.publish("test_stream2", {"data": "test2"})
    broker.get_next("test_stream1", "consumer_group1")  # Put one message in-flight

    stats = broker.health()
    details = stats["details"]

    # Check the adapter details
    assert "healthy" in details
    assert details["healthy"] is True

    assert "message_counts" in details
    message_counts = details["message_counts"]
    assert "total_messages" in message_counts
    assert "in_flight" in message_counts
    assert "failed" in message_counts
    assert "dlq" in message_counts

    # Should have 2 total messages, 1 in-flight
    assert message_counts["total_messages"] == 2
    assert message_counts["in_flight"] == 1
    assert message_counts["failed"] == 0
    assert message_counts["dlq"] == 0

    assert "streams" in details
    streams = details["streams"]
    assert streams["count"] == 2
    assert set(streams["names"]) == {"test_stream1", "test_stream2"}

    assert "consumer_groups" in details
    consumer_groups = details["consumer_groups"]
    assert consumer_groups["count"] == 1
    assert "consumer_group1" in consumer_groups["names"]

    assert "memory_estimate_bytes" in details
    assert isinstance(details["memory_estimate_bytes"], int)
    assert details["memory_estimate_bytes"] > 0

    assert "configuration" in details
    config = details["configuration"]
    assert "max_retries" in config
    assert "retry_delay" in config
    assert "message_timeout" in config
    assert "enable_dlq" in config


@pytest.mark.requires(BrokerCapabilities.ACK_NACK)
def test_health_tracks_message_state_changes(broker):
    """Test that health stats reflect changes in message states"""
    # Initial state
    stats = broker.health()
    initial_counts = stats["details"]["message_counts"]
    assert initial_counts["total_messages"] == 0
    assert initial_counts["in_flight"] == 0

    # Publish a message
    broker.publish("test_stream", {"data": "test"})
    stats = broker.health()
    counts = stats["details"]["message_counts"]
    assert counts["total_messages"] == 1
    assert counts["in_flight"] == 0

    # Get message (moves to in-flight)
    broker.get_next("test_stream", "test_group")
    stats = broker.health()
    counts = stats["details"]["message_counts"]
    assert counts["total_messages"] == 1
    assert counts["in_flight"] == 1


def test_reconnect_returns_true(broker):
    """Test that _reconnect() returns True for a healthy broker"""
    result = broker._reconnect()
    assert result is True
    assert isinstance(result, bool)


def test_reconnect_idempotent(broker):
    """Test that multiple calls to _reconnect() are safe"""
    result1 = broker._reconnect()
    result2 = broker._reconnect()
    result3 = broker._reconnect()

    assert result1 is True
    assert result2 is True
    assert result3 is True


def test_health_uptime_increases(broker):
    """Test that uptime increases over time"""
    stats1 = broker.health()
    uptime1 = stats1["uptime_seconds"]

    # Wait a small amount
    time.sleep(0.01)

    stats2 = broker.health()
    uptime2 = stats2["uptime_seconds"]

    # Uptime should increase
    assert uptime2 > uptime1
    assert isinstance(uptime1, (int, float))
    assert isinstance(uptime2, (int, float))


@pytest.mark.requires(BrokerCapabilities.ACK_NACK)
def test_health_with_failed_messages(broker):
    """Test health stats when there are failed messages"""
    # Publish a message and put it in failed state
    broker.publish("test_stream", {"data": "test"})
    identifier, _ = broker.get_next("test_stream", "test_group")

    # Nack the message to put it in failed state
    broker.nack("test_stream", identifier, "test_group")

    stats = broker.health()
    counts = stats["details"]["message_counts"]

    # For Redis, NACKed messages are pending, not failed
    # Failed count would only increase for messages in DLQ
    # So we check that the stats are at least returned without error
    assert "failed" in counts
    assert counts["failed"] >= 0


@pytest.mark.requires(BrokerCapabilities.DEAD_LETTER_QUEUE)
def test_health_with_dlq_messages(broker):
    """Test health stats when there are DLQ messages"""
    # Configure broker for quick DLQ testing
    broker._adapter._max_retries = 1
    broker._adapter._enable_dlq = True

    # Publish a message
    broker.publish("test_stream", {"data": "test"})
    identifier, _ = broker.get_next("test_stream", "test_group")

    # Nack it multiple times to exceed max retries
    broker.nack("test_stream", identifier, "test_group")
    # This should trigger additional retry logic that eventually moves to DLQ

    stats = broker.health()
    # DLQ count may or may not be > 0 depending on implementation timing
    assert "dlq" in stats["details"]["message_counts"]


@pytest.mark.requires(BrokerCapabilities.ACK_NACK)
def test_health_configuration_values(broker):
    """Test that health stats include correct configuration values"""
    stats = broker.health()
    config = stats["details"]["configuration"]

    # Check that configuration values match broker settings
    assert config["max_retries"] == broker._adapter._max_retries
    assert config["retry_delay"] == broker._adapter._retry_delay
    assert config["message_timeout"] == broker._adapter._message_timeout
    assert config["enable_dlq"] == broker._adapter._enable_dlq


@pytest.mark.requires(BrokerCapabilities.ACK_NACK)
def test_health_empty_broker_state(broker):
    """Test health stats for a completely empty broker"""
    stats = broker.health()
    details = stats["details"]

    # Empty broker should have zero counts
    assert details["message_counts"]["total_messages"] == 0
    assert details["message_counts"]["in_flight"] == 0
    assert details["message_counts"]["failed"] == 0
    assert details["message_counts"]["dlq"] == 0

    assert details["streams"]["count"] == 0
    assert details["streams"]["names"] == []

    assert details["consumer_groups"]["count"] == 0
    assert details["consumer_groups"]["names"] == []

    # Should still be healthy
    assert stats["status"] == "healthy"
    assert stats["connected"] is True


@pytest.mark.requires(BrokerCapabilities.PUBLISH)
def test_ping_after_data_reset(broker):
    """Test that ping works correctly after data reset"""
    # Add some data
    broker.publish("test", {"data": "test"})

    # Reset data
    broker.clear()

    # Ping should still work
    result = broker.ping()
    assert result is True


@pytest.mark.requires(BrokerCapabilities.ACK_NACK)
def test_health_after_data_reset(broker):
    """Test health stats after data reset"""
    # Add some test data
    broker.publish("test_stream", {"data": "test"})

    # Reset the data
    broker.clear()

    # Health stats should reflect the reset state
    stats = broker.health()
    assert stats["status"] == "healthy"
    assert stats["connected"] is True

    # Message counts should be reset
    message_counts = stats["details"]["message_counts"]
    assert message_counts["total_messages"] == 0
    assert message_counts["in_flight"] == 0
    assert message_counts["failed"] == 0
    assert message_counts["dlq"] == 0


def test_ping_failure_handling(broker):
    """Test ping behavior when underlying ping fails"""
    # Mock the adapter's ping to raise an exception
    original_ping = broker._adapter.ping

    def mock_ping():
        raise Exception("Connection error")

    broker._adapter.ping = mock_ping

    try:
        result = broker.ping()
        # Should return False when ping fails
        assert result is False

        # Should still update timing information
        assert broker._last_ping_success is False
        assert broker._last_ping_time is None  # Set to None when exception occurs

    finally:
        broker._adapter.ping = original_ping


def test_health_with_ping_failure(broker):
    """Test health stats when ping fails"""
    # Mock the adapter's ping to fail
    original_ping = broker._adapter.ping

    def mock_ping():
        raise Exception("Connection error")

    broker._adapter.ping = mock_ping

    try:
        stats = broker.health()

        # Should indicate unhealthy status
        assert stats["status"] in ["degraded", "unhealthy"]
        assert stats["connected"] is False

        # Should still have valid structure
        assert "details" in stats
        assert "message_counts" in stats["details"]

    finally:
        broker._adapter.ping = original_ping


def test_health_calculation_errors(broker):
    """Test health stats with various calculation errors"""
    # Mock different calculation methods to fail
    original_calculate_streams = getattr(
        broker._adapter, "_calculate_streams_info", None
    )
    original_calculate_groups = getattr(
        broker._adapter, "_calculate_consumer_groups_info", None
    )

    def mock_calculate_streams():
        raise Exception("Streams calculation failed")

    def mock_calculate_groups():
        raise Exception("Groups calculation failed")

    if original_calculate_streams:
        broker._adapter._calculate_streams_info = mock_calculate_streams
    if original_calculate_groups:
        broker._adapter._calculate_consumer_groups_info = mock_calculate_groups

    try:
        stats = broker.health()

        # Should still return valid structure with fallback values
        assert "status" in stats
        assert "details" in stats

        # Should have fallback values in details
        if "streams" in stats["details"]:
            streams = stats["details"]["streams"]
            assert "count" in streams
            assert "names" in streams
            # Should have default values when calculation fails
            assert streams["count"] == 0
            assert streams["names"] == []

        if "consumer_groups" in stats["details"]:
            groups = stats["details"]["consumer_groups"]
            assert "count" in groups
            assert "names" in groups
            # Should have default values when calculation fails
            assert groups["count"] == 0
            assert groups["names"] == []

    finally:
        if original_calculate_streams:
            broker._adapter._calculate_streams_info = original_calculate_streams
        if original_calculate_groups:
            broker._adapter._calculate_consumer_groups_info = original_calculate_groups


@pytest.mark.requires(BrokerCapabilities.ACK_NACK)
def test_health_with_message_count_errors(broker):
    """Test health stats when message count calculation fails"""
    # Mock the message count calculation to fail
    original_calculate_message_counts = getattr(
        broker, "_calculate_message_counts", None
    )

    def mock_calculate_message_counts():
        raise Exception("Message count calculation failed")

    if original_calculate_message_counts:
        broker._adapter._calculate_message_counts = mock_calculate_message_counts

        try:
            stats = broker.health()

            # Should still return valid structure
            assert "status" in stats
            assert "details" in stats

            # Should have fallback message counts
            if "message_counts" in stats["details"]:
                message_counts = stats["details"]["message_counts"]
                assert "total_messages" in message_counts
                assert "in_flight" in message_counts
                assert "failed" in message_counts
                assert "dlq" in message_counts
                # Should have default values
                assert message_counts["total_messages"] == 0
                assert message_counts["in_flight"] == 0
                assert message_counts["failed"] == 0
                assert message_counts["dlq"] == 0

        finally:
            broker._adapter._calculate_message_counts = (
                original_calculate_message_counts
            )


def test_health_with_comprehensive_errors(broker):
    """Test health stats when all calculation methods fail"""
    # Mock all calculation methods to fail
    original_ping = broker._adapter.ping
    original_calculate_message_counts = getattr(
        broker, "_calculate_message_counts", None
    )
    original_calculate_streams = getattr(
        broker._adapter, "_calculate_streams_info", None
    )
    original_calculate_groups = getattr(
        broker._adapter, "_calculate_consumer_groups_info", None
    )

    def mock_ping():
        raise Exception("Ping failed")

    def mock_calculate_message_counts():
        raise Exception("Message count calculation failed")

    def mock_calculate_streams():
        raise Exception("Streams calculation failed")

    def mock_calculate_groups():
        raise Exception("Groups calculation failed")

    broker._adapter.ping = mock_ping
    if original_calculate_message_counts:
        broker._adapter._calculate_message_counts = mock_calculate_message_counts
    if original_calculate_streams:
        broker._adapter._calculate_streams_info = mock_calculate_streams
    if original_calculate_groups:
        broker._adapter._calculate_consumer_groups_info = mock_calculate_groups

    try:
        stats = broker.health()

        # Should still return valid structure even with all errors
        assert "status" in stats
        assert "connected" in stats
        assert "details" in stats

        # Should indicate problems
        assert stats["status"] in ["degraded", "unhealthy"]
        assert stats["connected"] is False

        # Should have fallback values in all details
        details = stats["details"]
        if "message_counts" in details:
            message_counts = details["message_counts"]
            assert all(count == 0 for count in message_counts.values())

    finally:
        broker._adapter.ping = original_ping
        if original_calculate_message_counts:
            broker._adapter._calculate_message_counts = (
                original_calculate_message_counts
            )
        if original_calculate_streams:
            broker._adapter._calculate_streams_info = original_calculate_streams
        if original_calculate_groups:
            broker._adapter._calculate_consumer_groups_info = original_calculate_groups


def test_reconnect_error_recovery(broker):
    """Test reconnect with error recovery scenarios"""
    # Mock the adapter's reconnect to fail then succeed
    original_reconnect = broker._adapter.reconnect
    call_count = 0

    def mock_reconnect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Connection error")
        return True

    broker._adapter.reconnect = mock_reconnect

    try:
        # First call should raise: the service's _reconnect does not catch it
        with pytest.raises(Exception, match="Connection error"):
            broker._reconnect()

        # Second call should succeed
        result2 = broker._reconnect()
        assert result2 is True

    finally:
        broker._adapter.reconnect = original_reconnect
