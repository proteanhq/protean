"""Tests for consumer group management in InlineBroker."""

import time


def test_consumer_group_creation_during_operations(broker):
    """Test that consumer groups are created automatically during operations."""
    stream = "test_stream"
    consumer_group = "new_consumer_group"
    message = {"foo": "bar"}

    # Initially, consumer group doesn't exist
    assert not broker._validate_consumer_group(consumer_group)

    # Publish a message
    broker.publish(stream, message)

    # Get message - should create consumer group automatically
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None

    # Consumer group should now exist
    assert broker._validate_consumer_group(consumer_group)

    # Verify in internal structures
    group_key = f"{stream}:{consumer_group}"
    assert group_key in broker._consumer_groups


def test_multiple_consumer_groups_independent_processing(broker):
    """Test that multiple consumer groups can process messages independently."""
    stream = "test_stream"
    consumer_group1 = "group1"
    consumer_group2 = "group2"
    messages = [{"id": i} for i in range(3)]

    # Publish messages
    identifiers = []
    for msg in messages:
        identifiers.append(broker.publish(stream, msg))

    # Group 1 consumes first two messages
    for i in range(2):
        result = broker.get_next(stream, consumer_group1)
        assert result is not None
        msg_id, msg = result
        assert msg_id == identifiers[i]
        assert msg == messages[i]
        broker.ack(stream, msg_id, consumer_group1)

    # Group 2 can still consume all messages from the beginning
    for i in range(3):
        result = broker.get_next(stream, consumer_group2)
        assert result is not None
        msg_id, msg = result
        assert msg_id == identifiers[i]
        assert msg == messages[i]
        broker.ack(stream, msg_id, consumer_group2)

    # Group 1 consumes the third message
    result = broker.get_next(stream, consumer_group1)
    assert result is not None
    msg_id, msg = result
    assert msg_id == identifiers[2]
    assert msg == messages[2]


def test_consumer_position_tracking(broker):
    """Test that consumer positions are tracked independently per group."""
    stream = "test_stream"
    consumer_group1 = "group1"
    consumer_group2 = "group2"
    messages = [{"id": i} for i in range(5)]

    # Publish messages
    for msg in messages:
        broker.publish(stream, msg)

    # Group 1 consumes 3 messages
    for _ in range(3):
        result = broker.get_next(stream, consumer_group1)
        assert result is not None

    # Group 2 consumes 1 message
    result = broker.get_next(stream, consumer_group2)
    assert result is not None

    # Check positions
    group_key1 = f"{stream}:{consumer_group1}"
    group_key2 = f"{stream}:{consumer_group2}"
    assert broker._consumer_positions[group_key1] == 3
    assert broker._consumer_positions[group_key2] == 1


def test_validate_consumer_group_not_exists(broker):
    """Test validation of non-existent consumer group."""
    non_existent_group = "non_existent_group"

    # Should return False for non-existent group
    result = broker._validate_consumer_group(non_existent_group)
    assert result is False

    # Create a consumer group
    stream = "test_stream"
    existing_group = "existing_group"
    broker._ensure_group(existing_group, stream)

    # Should return True for existing group
    result = broker._validate_consumer_group(existing_group)
    assert result is True

    # Should still return False for non-existent group
    result = broker._validate_consumer_group(non_existent_group)
    assert result is False


def test_consumer_group_isolation_for_ack_nack(broker):
    """Test that ACK/NACK operations are isolated per consumer group."""
    stream = "test_stream"
    consumer_group1 = "group1"
    consumer_group2 = "group2"
    message = {"foo": "bar"}

    # Publish message
    identifier = broker.publish(stream, message)

    # Both groups get the message
    result1 = broker.get_next(stream, consumer_group1)
    assert result1 is not None

    result2 = broker.get_next(stream, consumer_group2)
    assert result2 is not None

    # Group 1 ACKs the message
    ack_result = broker.ack(stream, identifier, consumer_group1)
    assert ack_result is True

    # Group 2 can still NACK the message
    nack_result = broker.nack(stream, identifier, consumer_group2)
    assert nack_result is True

    # Verify operations are independent
    # Group 1 can't ACK again (already ACKed)
    ack_result = broker.ack(stream, identifier, consumer_group1)
    assert ack_result is False  # Idempotent

    # Group 2 can't NACK again (already NACKed)
    nack_result = broker.nack(stream, identifier, consumer_group2)
    assert nack_result is False  # Idempotent


def test_multiple_consumer_group_position_adjustment(broker):
    """Test position adjustment when messages are requeued for multiple groups."""
    stream = "test_stream"
    consumer_group1 = "group1"
    consumer_group2 = "group2"
    consumer_group3 = "group3"

    # Publish initial messages
    for i in range(3):
        broker.publish(stream, {"id": i})

    # All groups consume first message
    for group in [consumer_group1, consumer_group2, consumer_group3]:
        result = broker.get_next(stream, group)
        assert result is not None

    # Check initial positions
    assert broker._consumer_positions[f"{stream}:{consumer_group1}"] == 1
    assert broker._consumer_positions[f"{stream}:{consumer_group2}"] == 1
    assert broker._consumer_positions[f"{stream}:{consumer_group3}"] == 1

    # Requeue a message at position 1 for group1
    broker._requeue_messages(stream, consumer_group1, [("new_msg", {"new": "data"})])

    # Positions for other groups at or beyond insertion point should be adjusted
    assert broker._consumer_positions[f"{stream}:{consumer_group1}"] == 1  # No change
    assert broker._consumer_positions[f"{stream}:{consumer_group2}"] == 2  # Adjusted
    assert broker._consumer_positions[f"{stream}:{consumer_group3}"] == 2  # Adjusted


def test_requeue_messages_with_multiple_groups(broker):
    """Test requeuing messages with multiple consumer groups."""
    stream = "test_stream"
    consumer_group1 = "group1"
    consumer_group2 = "group2"

    # Publish initial messages
    broker.publish(stream, {"id": 1})
    broker.publish(stream, {"id": 2})

    # Both groups consume first message
    broker.get_next(stream, consumer_group1)
    broker.get_next(stream, consumer_group2)

    # Group2 consumes second message
    broker.get_next(stream, consumer_group2)

    # Positions: group1=1, group2=2
    group_key1 = f"{stream}:{consumer_group1}"
    group_key2 = f"{stream}:{consumer_group2}"
    assert broker._consumer_positions[group_key1] == 1
    assert broker._consumer_positions[group_key2] == 2

    # Requeue messages for group1
    messages_to_requeue = [("retry1", {"retry": 1}), ("retry2", {"retry": 2})]
    broker._requeue_messages(stream, consumer_group1, messages_to_requeue)

    # Group1 position unchanged, group2 position adjusted
    assert broker._consumer_positions[group_key1] == 1
    assert broker._consumer_positions[group_key2] == 4  # 2 + 2 requeued messages

    # Verify messages were inserted correctly
    assert len(broker._messages[stream]) == 4


def test_empty_consumer_group_cleanup(broker):
    """Test cleanup of empty consumer group entries in operation states."""
    consumer_group = "test_consumer_group"
    identifier1 = "msg1"
    identifier2 = "msg2"

    # Set operation state TTL to very short for testing
    broker._operation_state_ttl = 0.01  # 10ms

    # Store operation states
    broker._store_operation_state(consumer_group, identifier1, "ACKNOWLEDGED")
    broker._store_operation_state(consumer_group, identifier2, "NACKED")

    # Wait for expiry
    time.sleep(0.02)

    # Clean up expired states
    broker._cleanup_expired_operation_states()

    # Consumer group should be removed when empty
    assert consumer_group not in broker._operation_states


def test_consumer_group_info_tracking(broker):
    """Test that consumer group information is properly tracked."""
    stream1 = "stream1"
    stream2 = "stream2"
    consumer_group = "test_group"

    # Create consumer group for multiple streams
    broker._ensure_group(consumer_group, stream1)
    broker._ensure_group(consumer_group, stream2)

    # Publish and consume messages
    broker.publish(stream1, {"stream": 1})
    broker.publish(stream2, {"stream": 2})

    broker.get_next(stream1, consumer_group)
    broker.get_next(stream2, consumer_group)

    # Get info
    info = broker._info()

    # Verify consumer group info
    assert "consumer_groups" in info
    assert consumer_group in info["consumer_groups"]

    group_info = info["consumer_groups"][consumer_group]
    assert "in_flight_messages" in group_info
    assert stream1 in group_info["in_flight_messages"]
    assert stream2 in group_info["in_flight_messages"]
    assert group_info["in_flight_messages"][stream1] == 1
    assert group_info["in_flight_messages"][stream2] == 1
