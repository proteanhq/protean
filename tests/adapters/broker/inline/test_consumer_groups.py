"""Tests for consumer group management in InlineBroker."""

import time


def test_consumer_group_creation_during_operations(broker):
    """Test that consumer groups are created automatically during operations."""
    stream = "test_stream"
    consumer_group = "new_consumer_group"
    message = {"foo": "bar"}

    # Initially, consumer group doesn't exist
    assert not broker._adapter._validate_consumer_group(consumer_group)

    # Publish a message
    broker.publish(stream, message)

    # Get message - should create consumer group automatically
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None

    # Consumer group should now exist
    assert broker._adapter._validate_consumer_group(consumer_group)

    # Verify in internal structures
    group_key = f"{stream}:{consumer_group}"
    assert group_key in broker._adapter._consumer_groups


def test_multiple_consumer_groups_independent_processing(broker):
    """Test that multiple consumer groups can process messages independently."""
    stream = "test_stream"
    consumer_group1 = "group1"
    consumer_group2 = "group2"
    messages = [{"id": i} for i in range(3)]

    # Publish messages
    identifiers = [broker.publish(stream, msg) for msg in messages]

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
    assert broker._adapter._consumer_positions[group_key1] == 3
    assert broker._adapter._consumer_positions[group_key2] == 1


def test_validate_consumer_group_not_exists(broker):
    """Test validation of non-existent consumer group."""
    non_existent_group = "non_existent_group"

    # Should return False for non-existent group
    result = broker._adapter._validate_consumer_group(non_existent_group)
    assert result is False

    # Create a consumer group
    stream = "test_stream"
    existing_group = "existing_group"
    broker._create_group(stream, existing_group)

    # Should return True for existing group
    result = broker._adapter._validate_consumer_group(existing_group)
    assert result is True

    # Should still return False for non-existent group
    result = broker._adapter._validate_consumer_group(non_existent_group)
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


def test_requeue_leaves_the_stream_and_other_groups_unchanged(broker):
    """A requeued message goes to its own group, not back onto the stream."""
    stream = "test_stream"

    for i in range(3):
        broker.publish(stream, {"id": i})
    for group in ["group1", "group2"]:
        assert broker.get_next(stream, group) is not None

    broker._adapter._requeue_messages(stream, "group1", [("retry1", {"retry": 1})])

    assert len(broker._adapter._messages[stream]) == 3
    assert broker._adapter._consumer_positions[f"{stream}:group1"] == 1
    assert broker._adapter._consumer_positions[f"{stream}:group2"] == 1
    assert broker.get_next(stream, "group1")[0] == "retry1"
    assert broker.get_next(stream, "group2")[1] == {"id": 1}


def test_requeued_messages_are_redelivered_in_order_before_new_ones(broker):
    """Requeued messages come back in the order given, then the stream resumes."""
    stream = "test_stream"
    broker.publish(stream, {"id": 1})
    broker.publish(stream, {"id": 2})
    broker.get_next(stream, "group1")

    broker._adapter._requeue_messages(
        stream, "group1", [("retry1", {"retry": 1}), ("retry2", {"retry": 2})]
    )

    assert broker.get_next(stream, "group1")[0] == "retry1"
    assert broker.get_next(stream, "group1")[0] == "retry2"
    assert broker.get_next(stream, "group1")[1] == {"id": 2}


def test_empty_consumer_group_cleanup(broker):
    """Test cleanup of empty consumer group entries in operation states."""
    consumer_group = "test_consumer_group"
    identifier1 = "msg1"
    identifier2 = "msg2"

    # Set operation state TTL to very short for testing
    broker._adapter._operation_state_ttl = 0.01  # 10ms

    # Store operation states
    broker._adapter._store_operation_state(consumer_group, identifier1, "ACKNOWLEDGED")
    broker._adapter._store_operation_state(consumer_group, identifier2, "NACKED")

    # Wait for expiry
    time.sleep(0.02)

    # Clean up expired states
    broker._adapter._cleanup_expired_operation_states()

    # Consumer group should be removed when empty
    assert consumer_group not in broker._adapter._operation_states


def test_consumer_group_info_tracking(broker):
    """Test that consumer group information is properly tracked."""
    stream1 = "stream1"
    stream2 = "stream2"
    consumer_group = "test_group"

    # Create consumer group for multiple streams
    broker._create_group(stream1, consumer_group)
    broker._create_group(stream2, consumer_group)

    # Publish and consume messages
    broker.publish(stream1, {"stream": 1})
    broker.publish(stream2, {"stream": 2})

    broker.get_next(stream1, consumer_group)
    broker.get_next(stream2, consumer_group)

    # Get consumer group info
    groups = broker._consumer_groups()

    # Verify consumer group info: one pending message on each stream
    assert consumer_group in groups
    assert groups[consumer_group]["pending"] == 2
    assert len(broker._adapter._in_flight[f"{stream1}:{consumer_group}"]) == 1
    assert len(broker._adapter._in_flight[f"{stream2}:{consumer_group}"]) == 1
