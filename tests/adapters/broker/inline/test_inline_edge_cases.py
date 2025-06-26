"""Test cases specifically for InlineBroker edge cases and implementation details"""

import time


def test_remove_in_flight_message_when_not_exists(broker):
    """Test removing in-flight message when it doesn't exist"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Ensure group exists
    broker._ensure_group(consumer_group, stream)

    # Add some actual in-flight messages to verify they remain unchanged
    identifier1 = broker.publish(stream, {"data": "message1"})
    identifier2 = broker.publish(stream, {"data": "message2"})

    # Get messages to put them in flight
    broker.get_next(stream, consumer_group)
    broker.get_next(stream, consumer_group)

    # Capture initial state
    initial_in_flight_count = len(broker._in_flight[f"{stream}:{consumer_group}"])
    initial_identifiers = set(broker._in_flight[f"{stream}:{consumer_group}"].keys())

    # Try to remove non-existent message - this should be a no-op
    non_existent_id = "non-existent-message-id"
    assert non_existent_id not in initial_identifiers  # Ensure it's truly non-existent

    # This should not raise an error and should not modify state
    broker._remove_in_flight_message(stream, consumer_group, non_existent_id)

    # Verify state is unchanged
    assert (
        len(broker._in_flight[f"{stream}:{consumer_group}"]) == initial_in_flight_count
    )
    assert (
        set(broker._in_flight[f"{stream}:{consumer_group}"].keys())
        == initial_identifiers
    )

    # Verify the existing messages are still there
    assert identifier1 in broker._in_flight[f"{stream}:{consumer_group}"]
    assert identifier2 in broker._in_flight[f"{stream}:{consumer_group}"]


def test_get_in_flight_message_not_exists(broker):
    """Test getting in-flight message when it doesn't exist"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Ensure group exists
    broker._ensure_group(consumer_group, stream)

    # Try to get non-existent message
    result = broker._get_in_flight_message(stream, consumer_group, "non-existent-id")
    assert result is None


def test_cleanup_message_ownership_full_cleanup(broker):
    """Test cleanup of message ownership when no consumers left"""
    identifier = "test-id"
    consumer_group = "test_consumer_group"

    # Set up message ownership - it's actually a dict, not a set
    broker._message_ownership[identifier] = {consumer_group: True}

    # Clean up
    broker._cleanup_message_ownership(identifier, consumer_group)

    # Verify the entire identifier entry is removed
    assert identifier not in broker._message_ownership


def test_cleanup_message_ownership_partial_cleanup(broker):
    """Test cleanup of message ownership when other consumers remain"""
    identifier = "test-id"
    consumer_group_1 = "group-1"
    consumer_group_2 = "group-2"

    # Set up message ownership with multiple groups
    broker._message_ownership[identifier] = {
        consumer_group_1: True,
        consumer_group_2: True,
    }

    # Clean up one group
    broker._cleanup_message_ownership(identifier, consumer_group_1)

    # Verify only the specific group is removed
    assert identifier in broker._message_ownership
    assert consumer_group_1 not in broker._message_ownership[identifier]
    assert consumer_group_2 in broker._message_ownership[identifier]


def test_remove_retry_count_when_not_exists(broker):
    """Test removing retry count when it doesn't exist"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Ensure group exists
    broker._ensure_group(consumer_group, stream)

    # Try to remove non-existent retry count
    broker._remove_retry_count(stream, consumer_group, "non-existent-id")
    # Should not raise an error


def test_stale_message_cleanup_with_dlq_disabled(broker):
    """Test stale message cleanup when DLQ is disabled"""
    broker._enable_dlq = False  # Disable DLQ

    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Publish and get a message
    identifier = broker.publish(stream, {"data": "test"})
    broker.get_next(stream, consumer_group)

    # Manually make it stale by setting old timestamp
    old_timestamp = time.time() - broker._message_timeout - 100
    broker._in_flight[f"{stream}:{consumer_group}"][identifier] = (
        identifier,
        {"data": "test"},
        old_timestamp,
    )

    # Run cleanup
    broker._cleanup_stale_messages(consumer_group, broker._message_timeout)

    # Verify message was removed but not in DLQ
    assert identifier not in broker._in_flight[f"{stream}:{consumer_group}"]
    assert len(broker._dead_letter_queue[f"{stream}:{consumer_group}"]) == 0


def test_clear_operation_state_when_not_exists(broker):
    """Test clearing operation state when it doesn't exist"""
    consumer_group = "test_consumer_group"
    stream = "test_stream"

    # Ensure group exists
    broker._ensure_group(consumer_group, stream)

    # Set up some existing operation state by creating actual in-flight messages
    identifier1 = broker.publish(stream, {"data": "message1"})
    identifier2 = broker.publish(stream, {"data": "message2"})

    # Get messages to create operation state
    broker.get_next(stream, consumer_group)
    broker.get_next(stream, consumer_group)

    # Store some operation states to test with
    from protean.port.broker import OperationState

    broker._store_operation_state(consumer_group, identifier1, OperationState.PENDING)
    broker._store_operation_state(consumer_group, identifier2, OperationState.PENDING)

    # Capture initial state
    initial_in_flight_count = len(broker._in_flight[f"{stream}:{consumer_group}"])
    initial_message_ownership = broker._message_ownership.copy()
    initial_operation_states = dict(broker._operation_states[consumer_group])

    # Try to clear non-existent operation state
    non_existent_id = "non-existent-operation-id"
    assert non_existent_id not in broker._operation_states[consumer_group]

    # This should not raise an error and should not modify existing state
    broker._clear_operation_state(consumer_group, non_existent_id)

    # Verify that existing state is unchanged
    assert (
        len(broker._in_flight[f"{stream}:{consumer_group}"]) == initial_in_flight_count
    )
    assert broker._message_ownership == initial_message_ownership
    assert dict(broker._operation_states[consumer_group]) == initial_operation_states

    # Verify specific messages are still in flight (clear_operation_state doesn't affect in-flight)
    assert identifier1 in broker._in_flight[f"{stream}:{consumer_group}"]
    assert identifier2 in broker._in_flight[f"{stream}:{consumer_group}"]

    # Verify that we can still clear existing operation state normally
    broker._clear_operation_state(consumer_group, identifier1)
    assert identifier1 not in broker._operation_states[consumer_group]
    assert identifier2 in broker._operation_states[consumer_group]
    # In-flight messages should remain (clear_operation_state only clears operation states)
    assert identifier1 in broker._in_flight[f"{stream}:{consumer_group}"]
    assert identifier2 in broker._in_flight[f"{stream}:{consumer_group}"]


def test_requeue_messages_with_multiple_groups(broker):
    """Test message requeuing with position adjustment for multiple consumer groups"""
    stream = "test_stream"
    consumer_group_1 = "group-1"
    consumer_group_2 = "group-2"

    # Set up multiple consumer groups
    broker._ensure_group(consumer_group_1, stream)
    broker._ensure_group(consumer_group_2, stream)

    # Set initial positions
    broker._consumer_positions[f"{stream}:{consumer_group_1}"] = 2
    broker._consumer_positions[f"{stream}:{consumer_group_2}"] = 2

    # Requeue a message for group 1
    messages = [("retry-id", {"data": "retry"})]
    broker._requeue_messages(stream, consumer_group_1, messages)

    # Verify group 2's position was adjusted
    assert broker._consumer_positions[f"{stream}:{consumer_group_2}"] == 3
    # Group 1's position should remain the same
    assert broker._consumer_positions[f"{stream}:{consumer_group_1}"] == 2


def test_requeue_messages_empty_list(broker):
    """Test requeuing with empty message list"""
    stream = "test_stream"
    consumer_group_1 = "group-1"
    consumer_group_2 = "group-2"

    # Set up multiple consumer groups
    broker._ensure_group(consumer_group_1, stream)
    broker._ensure_group(consumer_group_2, stream)

    # Publish some messages and set up initial state
    for i in range(3):
        broker.publish(stream, {"data": f"message_{i}"})

    # Consume some messages with both groups
    broker.get_next(stream, consumer_group_1)
    broker.get_next(stream, consumer_group_2)

    # Capture initial state before requeuing empty list
    initial_messages_count = len(broker._messages[stream])
    initial_position_1 = broker._consumer_positions[f"{stream}:{consumer_group_1}"]
    initial_position_2 = broker._consumer_positions[f"{stream}:{consumer_group_2}"]
    initial_in_flight_1 = dict(broker._in_flight[f"{stream}:{consumer_group_1}"])
    initial_in_flight_2 = dict(broker._in_flight[f"{stream}:{consumer_group_2}"])
    initial_messages_copy = list(broker._messages[stream])

    # Requeue empty list - this should be a complete no-op
    broker._requeue_messages(stream, consumer_group_1, [])

    # Verify absolutely nothing changed
    assert len(broker._messages[stream]) == initial_messages_count
    assert (
        broker._consumer_positions[f"{stream}:{consumer_group_1}"] == initial_position_1
    )
    assert (
        broker._consumer_positions[f"{stream}:{consumer_group_2}"] == initial_position_2
    )
    assert (
        dict(broker._in_flight[f"{stream}:{consumer_group_1}"]) == initial_in_flight_1
    )
    assert (
        dict(broker._in_flight[f"{stream}:{consumer_group_2}"]) == initial_in_flight_2
    )
    assert broker._messages[stream] == initial_messages_copy

    # Verify that requeuing still works normally with actual messages
    test_message = ("test-id", {"data": "test_requeue"})
    broker._requeue_messages(stream, consumer_group_1, [test_message])

    # Verify the test message was actually requeued at the correct position
    assert len(broker._messages[stream]) == initial_messages_count + 1
    # The message should be inserted at consumer_group_1's current position
    expected_position = initial_position_1
    assert broker._messages[stream][expected_position] == test_message

    # Verify other consumer group's position was adjusted
    assert (
        broker._consumer_positions[f"{stream}:{consumer_group_2}"]
        == initial_position_2 + 1
    )


def test_validate_consumer_group_not_exists(broker):
    """Test validation when consumer group doesn't exist"""

    result = broker._validate_consumer_group("non-existent-group")
    assert result is False


def test_validate_message_ownership_not_exists(broker):
    """Test validation when message ownership doesn't exist"""

    result = broker._validate_message_ownership("non-existent-id", "test-group")
    assert result is False


def test_validate_message_ownership_wrong_group(broker):
    """Test validation when message belongs to different group"""
    identifier = "test-id"

    # Set up message ownership for different group
    broker._message_ownership[identifier] = {"other-group": True}

    result = broker._validate_message_ownership(identifier, "test-group")
    assert result is False


def test_get_dlq_messages_specific_stream(broker):
    """Test getting DLQ messages for specific stream"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Ensure group exists
    broker._ensure_group(consumer_group, stream)

    # Add DLQ message directly
    broker._dead_letter_queue[f"{stream}:{consumer_group}"].append(
        ("id1", {"data": "test"}, "failure", time.time())
    )
    broker._dead_letter_queue[f"other-stream:{consumer_group}"].append(
        ("id2", {"data": "test2"}, "failure", time.time())
    )

    # Get DLQ messages for specific stream
    result = broker._get_dlq_messages(consumer_group, stream)

    assert stream in result
    assert len(result[stream]) == 1
    assert "other-stream" not in result


def test_get_dlq_messages_all_streams(broker):
    """Test getting DLQ messages for all streams"""
    consumer_group = "test_consumer_group"

    # Ensure group exists
    broker._ensure_group(
        consumer_group, "stream1"
    )  # Need to pick a stream for group creation

    # Add DLQ messages to multiple streams directly
    broker._dead_letter_queue[f"stream1:{consumer_group}"].append(
        ("id1", {"data": "test1"}, "failure", time.time())
    )
    broker._dead_letter_queue[f"stream2:{consumer_group}"].append(
        ("id2", {"data": "test2"}, "failure", time.time())
    )

    # Get all DLQ messages
    result = broker._get_dlq_messages(consumer_group)

    assert "stream1" in result
    assert "stream2" in result
    assert len(result["stream1"]) == 1
    assert len(result["stream2"]) == 1


def test_inline_broker_message_storage_format(broker):
    """Test inline broker's internal message storage format"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get the message
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Verify internal storage format
    assert identifier in broker._in_flight[f"{stream}:{consumer_group}"]
    stored_message = broker._in_flight[f"{stream}:{consumer_group}"][identifier]
    assert len(stored_message) == 3  # (id, message, timestamp)
    assert stored_message[0] == identifier
    assert stored_message[1] == message
    assert isinstance(stored_message[2], float)  # timestamp


def test_inline_broker_consumer_position_tracking(broker):
    """Test inline broker's consumer position tracking"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Publish multiple messages
    for i in range(3):
        broker.publish(stream, {"data": f"message_{i}"})

    # Get messages and verify position tracking
    for i in range(3):
        message = broker.get_next(stream, consumer_group)
        assert message is not None
        assert broker._consumer_positions[f"{stream}:{consumer_group}"] == i + 1
