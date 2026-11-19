"""Tests for consumer group info and health records in InlineBroker."""

import time


def test_consumer_groups_returns_broker_information(broker):
    """Test that _consumer_groups returns correct consumer group information."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get a message
    broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Get consumer group info
    groups = broker._consumer_groups()

    # Verify structure
    assert consumer_group in groups

    # Verify consumer group info: the one delivered message is pending
    group_info = groups[consumer_group]
    assert group_info["name"] == consumer_group
    assert group_info["pending"] == 1
    assert len(broker._adapter._in_flight[f"{stream}:{consumer_group}"]) == 1


def test_consumer_groups_with_multiple_streams_and_groups(broker):
    """Test _consumer_groups with multiple streams and consumer groups."""
    # Create multiple streams and consumer groups
    stream1 = "stream1"
    stream2 = "stream2"
    group1 = "group1"
    group2 = "group2"

    # Ensure groups exist
    broker._create_group(stream1, group1)
    broker._create_group(stream2, group1)
    broker._create_group(stream1, group2)

    # Add some in-flight messages
    broker._adapter._store_in_flight_message(stream1, group1, "msg1", {"data": "1"})
    broker._adapter._store_in_flight_message(stream1, group1, "msg2", {"data": "2"})
    broker._adapter._store_in_flight_message(stream2, group1, "msg3", {"data": "3"})
    broker._adapter._store_in_flight_message(stream1, group2, "msg4", {"data": "4"})

    # Add some failed messages
    group_key1_s1 = f"{stream1}:{group1}"
    group_key1_s2 = f"{stream2}:{group1}"
    broker._adapter._failed_messages[group_key1_s1].append(
        ("fail1", {}, 1, time.time())
    )
    broker._adapter._failed_messages[group_key1_s2].append(
        ("fail2", {}, 1, time.time())
    )

    # Get consumer group info
    groups = broker._consumer_groups()

    # Verify structure
    assert group1 in groups
    assert group2 in groups

    # Pending sums the in-flight messages over each group's streams
    assert groups[group1]["pending"] == 3
    assert groups[group2]["pending"] == 1

    # Per-stream counts for group1, read from the adapter's state
    adapter = broker._adapter
    group_key2_s1 = f"{stream1}:{group2}"
    assert len(adapter._in_flight[group_key1_s1]) == 2
    assert len(adapter._in_flight[group_key1_s2]) == 1
    assert len(adapter._failed_messages[group_key1_s1]) == 1
    assert len(adapter._failed_messages[group_key1_s2]) == 1

    # Per-stream counts for group2
    assert len(adapter._in_flight[group_key2_s1]) == 1
    assert len(adapter._failed_messages[group_key2_s1]) == 0


def test_adapter_health_basic(broker):
    """Test basic health statistics."""
    # Get initial health stats
    stats = broker._adapter.health()

    # Verify structure
    assert stats.healthy is True
    assert "streams" in stats.details
    assert "memory_estimate_bytes" in stats.details
    assert "configuration" in stats.details

    # Verify initial counts
    assert stats.message_counts["total_messages"] == 0
    assert stats.message_counts["in_flight"] == 0
    assert stats.message_counts["failed"] == 0
    assert stats.message_counts["dlq"] == 0
    assert stats.consumer_groups["count"] == 0


def test_adapter_health_with_various_states(broker):
    """Test health stats calculation with messages in various states."""
    # Add messages to different streams
    broker._adapter._messages["stream1"] = [("msg1", {}), ("msg2", {})]
    broker._adapter._messages["stream2"] = [("msg3", {})]

    # Create consumer groups
    broker._create_group("stream1", "group1")
    broker._create_group("stream2", "group2")

    # Add in-flight messages
    broker._adapter._in_flight["stream1:group1"] = {"msg1": ("msg1", {}, time.time())}

    # Add failed messages
    broker._adapter._failed_messages["stream1:group1"] = [("fail1", {}, 1, time.time())]

    # Add a DLQ message, which is also a message on a stream
    broker._adapter._messages["stream2:dlq"] = [("dlq1", {}), ("dlq2", {})]

    # Get health stats
    stats = broker._adapter.health()

    # Verify counts
    assert stats.message_counts["total_messages"] == 5
    assert stats.message_counts["in_flight"] == 1
    assert stats.message_counts["failed"] == 1
    assert stats.message_counts["dlq"] == 2
    assert stats.details["memory_estimate_bytes"] == 3 * 100 + 150 + 150 + 2 * 150

    # Verify streams and consumer groups
    assert stats.details["streams"]["count"] == 3
    assert "stream1" in stats.details["streams"]["names"]
    assert "stream2" in stats.details["streams"]["names"]

    assert stats.consumer_groups["count"] == 2
    assert "group1" in stats.consumer_groups["names"]
    assert "group2" in stats.consumer_groups["names"]

    # Verify configuration is included
    configuration = stats.details["configuration"]
    assert configuration["max_retries"] == broker._adapter._max_retries
    assert configuration["enable_dlq"] == broker._adapter._enable_dlq


def test_adapter_health_memory_estimation(broker):
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
    broker._adapter._max_retries = 5
    msg = broker.get_next("stream1", consumer_group)
    if msg:
        broker.nack("stream1", msg[0], consumer_group)

    # Get health stats
    stats = broker._adapter.health()

    # Memory estimate should be > 0
    assert stats.details["memory_estimate_bytes"] > 0

    # Rough check: more messages = more memory
    initial_memory = stats.details["memory_estimate_bytes"]

    # Add more messages
    for i in range(10):
        broker.publish("stream2", {"id": i})

    stats = broker._adapter.health()
    assert stats.details["memory_estimate_bytes"] > initial_memory


def test_ping_always_available(broker):
    """Test that ping always returns True for inline broker."""
    # InlineBroker is always available (in-memory)
    result = broker.ping()
    assert result is True

    # Even after operations
    broker.publish("stream", {"test": "data"})
    result = broker.ping()
    assert result is True


def test_reconnect_always_true(broker):
    """Test that reconnect always returns True for inline broker."""
    # InlineBroker doesn't need external connection
    result = broker._reconnect()
    assert result is True

    # Even after operations
    broker.publish("stream", {"test": "data"})
    result = broker._reconnect()
    assert result is True


def test_clear_removes_all_data(broker):
    """Test that clear empties all internal data structures."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Add data to all structures
    broker.publish(stream, {"test": "data"})
    broker.get_next(stream, consumer_group)
    broker._adapter._failed_messages[f"{stream}:{consumer_group}"] = [
        ("id", {}, 1, time.time())
    ]
    broker._adapter._messages[f"{stream}:dlq"] = [("id", {})]
    broker._adapter._operation_states[consumer_group] = {"id": ("state", time.time())}

    # Verify data exists
    assert len(broker._adapter._messages) > 0
    assert len(broker._adapter._consumer_groups) > 0
    assert len(broker._adapter._in_flight) > 0

    # Reset all data
    broker.clear()

    # Verify all structures are empty
    assert len(broker._adapter._messages) == 0
    assert len(broker._adapter._consumer_groups) == 0
    assert len(broker._adapter._in_flight) == 0
    assert len(broker._adapter._failed_messages) == 0
    assert len(broker._adapter._retry_counts) == 0
    assert len(broker._adapter._consumer_positions) == 0
    assert len(broker._adapter._message_ownership) == 0
    assert len(broker._adapter._operation_states) == 0


def test_broker_capabilities(broker):
    """Test that broker reports correct capabilities."""
    from protean.port.broker import BrokerCapabilities

    capabilities = broker.capabilities
    assert capabilities == (
        BrokerCapabilities.RELIABLE_MESSAGING | BrokerCapabilities.DEAD_LETTER_QUEUE
    )


def test_consumer_group_tracking_with_operations(broker):
    """Test consumer group tracking through various operations."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Initially the group does not exist
    assert consumer_group not in broker._consumer_groups()

    # Publish and consume
    identifier = broker.publish(stream, {"test": "data"})
    broker.get_next(stream, consumer_group)

    # The group should show one pending (in-flight) message
    groups = broker._consumer_groups()
    assert consumer_group in groups
    assert groups[consumer_group]["pending"] == 1

    # ACK the message
    broker.ack(stream, identifier, consumer_group)

    # Pending should be 0
    assert broker._consumer_groups()[consumer_group]["pending"] == 0

    # NACK a new message
    broker._adapter._max_retries = 0
    identifier = broker.publish(stream, {"test": "data2"})
    broker.get_next(stream, consumer_group)
    broker.nack(stream, identifier, consumer_group)

    # Should show in DLQ
    [entry] = broker.dlq_list([f"{stream}:dlq"])
    assert entry.consumer_group == consumer_group
