"""Tests for broker info and health statistics in InlineBroker."""

import time


def test_info_method_returns_broker_information(broker):
    """Test that info method returns correct broker information."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Get broker info
    info = broker.info()

    # Verify structure
    assert "consumer_groups" in info
    assert consumer_group in info["consumer_groups"]

    # Verify consumer group info
    group_info = info["consumer_groups"][consumer_group]
    assert "in_flight_messages" in group_info
    assert stream in group_info["in_flight_messages"]
    assert group_info["in_flight_messages"][stream] == 1


def test_info_method_with_multiple_streams_and_groups(broker):
    """Test info method with multiple streams and consumer groups."""
    # Create multiple streams and consumer groups
    stream1 = "stream1"
    stream2 = "stream2"
    group1 = "group1"
    group2 = "group2"

    # Ensure groups exist
    broker._ensure_group(group1, stream1)
    broker._ensure_group(group1, stream2)
    broker._ensure_group(group2, stream1)

    # Add some in-flight messages
    broker._store_in_flight_message(stream1, group1, "msg1", {"data": "1"})
    broker._store_in_flight_message(stream1, group1, "msg2", {"data": "2"})
    broker._store_in_flight_message(stream2, group1, "msg3", {"data": "3"})
    broker._store_in_flight_message(stream1, group2, "msg4", {"data": "4"})

    # Add some failed messages
    group_key1_s1 = f"{stream1}:{group1}"
    group_key1_s2 = f"{stream2}:{group1}"
    broker._failed_messages[group_key1_s1].append(("fail1", {}, 1, time.time()))
    broker._failed_messages[group_key1_s2].append(("fail2", {}, 1, time.time()))

    # Add DLQ messages
    broker._dead_letter_queue[group_key1_s1].append(
        ("dlq1", {}, "timeout", time.time())
    )

    # Get info
    info = broker._info()

    # Verify structure
    assert "consumer_groups" in info
    assert group1 in info["consumer_groups"]
    assert group2 in info["consumer_groups"]

    # Verify counts for group1
    group1_info = info["consumer_groups"][group1]
    assert group1_info["in_flight_messages"][stream1] == 2
    assert group1_info["in_flight_messages"][stream2] == 1
    assert group1_info["failed_messages"][stream1] == 1
    assert group1_info["failed_messages"][stream2] == 1
    assert group1_info["dlq_messages"][stream1] == 1
    assert group1_info["dlq_messages"][stream2] == 0

    # Verify counts for group2
    group2_info = info["consumer_groups"][group2]
    assert group2_info["in_flight_messages"][stream1] == 1
    assert group2_info["failed_messages"][stream1] == 0


def test_health_stats_basic(broker):
    """Test basic health statistics."""
    # Get initial health stats
    stats = broker._health_stats()

    # Verify structure
    assert "healthy" in stats
    assert stats["healthy"] is True
    assert "message_counts" in stats
    assert "streams" in stats
    assert "consumer_groups" in stats
    assert "memory_estimate_bytes" in stats
    assert "configuration" in stats

    # Verify initial counts
    assert stats["message_counts"]["total_messages"] == 0
    assert stats["message_counts"]["in_flight"] == 0
    assert stats["message_counts"]["failed"] == 0
    assert stats["message_counts"]["dlq"] == 0


def test_health_stats_with_various_states(broker):
    """Test health stats calculation with messages in various states."""
    # Add messages to different streams
    broker._messages["stream1"] = [("msg1", {}), ("msg2", {})]
    broker._messages["stream2"] = [("msg3", {})]

    # Create consumer groups
    broker._ensure_group("group1", "stream1")
    broker._ensure_group("group2", "stream2")

    # Add in-flight messages
    broker._in_flight["stream1:group1"] = {"msg1": ("msg1", {}, time.time())}

    # Add failed messages
    broker._failed_messages["stream1:group1"] = [("fail1", {}, 1, time.time())]

    # Add DLQ messages
    broker._dead_letter_queue["stream2:group2"] = [("dlq1", {}, "timeout", time.time())]

    # Get health stats
    stats = broker._health_stats()

    # Verify counts
    assert stats["message_counts"]["total_messages"] == 3
    assert stats["message_counts"]["in_flight"] == 1
    assert stats["message_counts"]["failed"] == 1
    assert stats["message_counts"]["dlq"] == 1

    # Verify streams and consumer groups
    assert stats["streams"]["count"] == 2
    assert "stream1" in stats["streams"]["names"]
    assert "stream2" in stats["streams"]["names"]

    assert stats["consumer_groups"]["count"] == 2
    assert "group1" in stats["consumer_groups"]["names"]
    assert "group2" in stats["consumer_groups"]["names"]

    # Verify configuration is included
    assert stats["configuration"]["max_retries"] == broker._max_retries
    assert stats["configuration"]["enable_dlq"] == broker._enable_dlq


def test_health_stats_memory_estimation(broker):
    """Test memory estimation in health stats."""
    # Add various types of messages
    for i in range(10):
        broker.publish("stream1", {"id": i})

    # Create consumer groups and process messages
    consumer_group = "test_group"

    # Get some messages (creates in-flight)
    for _ in range(3):
        broker.get_next("stream1", consumer_group)

    # NACK one message (creates failed message)
    broker._max_retries = 5
    msg = broker.get_next("stream1", consumer_group)
    if msg:
        broker.nack("stream1", msg[0], consumer_group)

    # Get health stats
    stats = broker._health_stats()

    # Memory estimate should be > 0
    assert stats["memory_estimate_bytes"] > 0

    # Rough check: more messages = more memory
    initial_memory = stats["memory_estimate_bytes"]

    # Add more messages
    for i in range(10):
        broker.publish("stream2", {"id": i})

    stats = broker._health_stats()
    assert stats["memory_estimate_bytes"] > initial_memory


def test_ping_always_available(broker):
    """Test that ping always returns True for inline broker."""
    # InlineBroker is always available (in-memory)
    result = broker._ping()
    assert result is True

    # Even after operations
    broker.publish("stream", {"test": "data"})
    result = broker._ping()
    assert result is True


def test_ensure_connection_always_true(broker):
    """Test that ensure_connection always returns True for inline broker."""
    # InlineBroker doesn't need external connection
    result = broker._ensure_connection()
    assert result is True

    # Even after operations
    broker.publish("stream", {"test": "data"})
    result = broker._ensure_connection()
    assert result is True


def test_data_reset_clears_all_data(broker):
    """Test that data_reset clears all internal data structures."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Add data to all structures
    broker.publish(stream, {"test": "data"})
    broker.get_next(stream, consumer_group)
    broker._failed_messages[f"{stream}:{consumer_group}"] = [("id", {}, 1, time.time())]
    broker._dead_letter_queue[f"{stream}:{consumer_group}"] = [
        ("id", {}, "reason", time.time())
    ]
    broker._operation_states[consumer_group] = {"id": ("state", time.time())}

    # Verify data exists
    assert len(broker._messages) > 0
    assert len(broker._consumer_groups) > 0
    assert len(broker._in_flight) > 0

    # Reset all data
    broker._data_reset()

    # Verify all structures are empty
    assert len(broker._messages) == 0
    assert len(broker._consumer_groups) == 0
    assert len(broker._in_flight) == 0
    assert len(broker._failed_messages) == 0
    assert len(broker._retry_counts) == 0
    assert len(broker._consumer_positions) == 0
    assert len(broker._message_ownership) == 0
    assert len(broker._dead_letter_queue) == 0
    assert len(broker._operation_states) == 0


def test_broker_capabilities(broker):
    """Test that broker reports correct capabilities."""
    from protean.port.broker import BrokerCapabilities

    capabilities = broker.capabilities
    assert capabilities == BrokerCapabilities.RELIABLE_MESSAGING


def test_info_tracking_with_operations(broker):
    """Test info tracking through various operations."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Initial info should be minimal
    info = broker.info()
    assert (
        len(info["consumer_groups"]) == 0
        or consumer_group not in info["consumer_groups"]
    )

    # Publish and consume
    identifier = broker.publish(stream, {"test": "data"})
    broker.get_next(stream, consumer_group)

    # Info should show in-flight message
    info = broker.info()
    assert consumer_group in info["consumer_groups"]
    assert info["consumer_groups"][consumer_group]["in_flight_messages"][stream] == 1

    # ACK the message
    broker.ack(stream, identifier, consumer_group)

    # In-flight should be 0
    info = broker.info()
    assert info["consumer_groups"][consumer_group]["in_flight_messages"][stream] == 0

    # NACK a new message
    broker._max_retries = 0
    identifier = broker.publish(stream, {"test": "data2"})
    broker.get_next(stream, consumer_group)
    broker.nack(stream, identifier, consumer_group)

    # Should show in DLQ
    info = broker.info()
    assert info["consumer_groups"][consumer_group]["dlq_messages"][stream] == 1
