"""Tests for internal state management and tracking in InlineBroker."""

import time

from protean.port.broker import OperationState


class TestInlineBrokerInternalState:
    """Test internal state management of InlineBroker."""

    def test_message_ownership_tracking(self, broker):
        """Test message ownership is properly tracked."""
        stream = "test_stream"
        consumer_group1 = "group1"
        consumer_group2 = "group2"
        message = {"test": "data"}

        # Publish message
        identifier = broker.publish(stream, message)

        # Group1 gets the message
        result = broker.get_next(stream, consumer_group1)
        assert result is not None

        # Verify ownership is tracked for group1
        assert broker._validate_message_ownership(identifier, consumer_group1)
        assert not broker._validate_message_ownership(identifier, consumer_group2)

        # Group2 gets the message
        result = broker.get_next(stream, consumer_group2)
        assert result is not None

        # Now both groups have ownership
        assert broker._validate_message_ownership(identifier, consumer_group1)
        assert broker._validate_message_ownership(identifier, consumer_group2)

    def test_retry_count_tracking(self, broker):
        """Test retry count is properly tracked."""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "data"}

        # Configure short retry delay
        broker._retry_delay = 0.01

        # Publish and get message
        identifier = broker.publish(stream, message)
        broker.get_next(stream, consumer_group)

        # Initial retry count should be 0
        count = broker._get_retry_count(stream, consumer_group, identifier)
        assert count == 0

        # NACK and check count increments
        broker.nack(stream, identifier, consumer_group)
        count = broker._get_retry_count(stream, consumer_group, identifier)
        assert count == 1

        # Get and NACK again
        time.sleep(0.02)
        broker.get_next(stream, consumer_group)
        broker.nack(stream, identifier, consumer_group)
        count = broker._get_retry_count(stream, consumer_group, identifier)
        assert count == 2

    def test_consumer_position_tracking(self, broker):
        """Test consumer position is properly tracked."""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        messages = [{"id": i} for i in range(5)]

        # Publish messages
        for msg in messages:
            broker.publish(stream, msg)

        # Initial position should be 0
        group_key = f"{stream}:{consumer_group}"
        assert broker._consumer_positions.get(group_key, 0) == 0

        # Consume messages and verify position updates
        for i in range(3):
            broker.get_next(stream, consumer_group)
            assert broker._consumer_positions[group_key] == i + 1

    def test_failed_messages_structure(self, broker):
        """Test failed messages data structure."""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "data"}

        # Configure short retry
        broker._retry_delay = 0.01

        # Publish, get, and NACK
        identifier = broker.publish(stream, message)
        broker.get_next(stream, consumer_group)
        broker.nack(stream, identifier, consumer_group)

        # Check failed messages structure
        group_key = f"{stream}:{consumer_group}"
        assert group_key in broker._failed_messages
        assert len(broker._failed_messages[group_key]) == 1

        failed_entry = broker._failed_messages[group_key][0]
        assert failed_entry[0] == identifier  # Message ID
        assert failed_entry[1] == message  # Message content
        assert failed_entry[2] == 1  # Retry count
        assert isinstance(failed_entry[3], float)  # Next retry time

    def test_dlq_structure(self, broker):
        """Test DLQ data structure."""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "data"}

        # Configure to send straight to DLQ
        broker._max_retries = 0

        # Publish, get, and NACK
        identifier = broker.publish(stream, message)
        broker.get_next(stream, consumer_group)
        broker.nack(stream, identifier, consumer_group)

        # Check DLQ structure
        group_key = f"{stream}:{consumer_group}"
        assert group_key in broker._dead_letter_queue
        assert len(broker._dead_letter_queue[group_key]) == 1

        dlq_entry = broker._dead_letter_queue[group_key][0]
        assert dlq_entry[0] == identifier  # Message ID
        assert dlq_entry[1] == message  # Message content
        assert dlq_entry[2] == "max_retries_exceeded"  # Failure reason
        assert isinstance(dlq_entry[3], float)  # Timestamp

    def test_stale_message_cleanup(self, broker):
        """Test cleanup of stale in-flight messages."""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "data"}

        # Configure very short timeout
        broker._message_timeout = 0.01  # 10ms
        broker._enable_dlq = True

        # Publish and get message
        identifier = broker.publish(stream, message)
        broker.get_next(stream, consumer_group)

        # Wait for timeout
        time.sleep(0.02)

        # Cleanup stale messages
        broker._cleanup_stale_messages(consumer_group, broker._message_timeout)

        # Message should be moved to DLQ
        group_key = f"{stream}:{consumer_group}"
        assert identifier not in broker._in_flight.get(group_key, {})
        assert len(broker._dead_letter_queue[group_key]) == 1

    def test_requeue_failed_messages_logic(self, broker):
        """Test logic for requeuing failed messages."""
        stream = "test_stream"
        consumer_group = "test_consumer_group"
        message = {"test": "data"}

        # Configure short retry
        broker._retry_delay = 0.01

        # Publish, get, and NACK
        identifier = broker.publish(stream, message)
        broker.get_next(stream, consumer_group)
        broker.nack(stream, identifier, consumer_group)

        # Immediately check - message should not be ready
        ready = broker._get_retry_ready_messages(stream, consumer_group)
        assert len(ready) == 0

        # Wait for retry delay
        time.sleep(0.02)

        # Now message should be ready
        ready = broker._get_retry_ready_messages(stream, consumer_group)
        assert len(ready) == 1
        assert ready[0] == (identifier, message)

    def test_multiple_consumer_group_position_adjustment(self, broker):
        """Test position adjustment for multiple consumer groups."""
        stream = "test_stream"
        consumer_group1 = "group1"
        consumer_group2 = "group2"

        # Publish initial messages
        broker.publish(stream, {"id": 1})
        broker.publish(stream, {"id": 2})

        # Both groups consume first message
        broker.get_next(stream, consumer_group1)
        broker.get_next(stream, consumer_group2)

        # Verify positions
        assert broker._consumer_positions[f"{stream}:{consumer_group1}"] == 1
        assert broker._consumer_positions[f"{stream}:{consumer_group2}"] == 1

        # Insert message at position 1 for group1
        broker._messages[stream].insert(1, ("new_id", {"new": "data"}))

        # Manually adjust positions as would happen in requeue
        for group_key in broker._consumer_positions:
            if (
                group_key.startswith(f"{stream}:")
                and group_key != f"{stream}:{consumer_group1}"
            ):
                if broker._consumer_positions[group_key] >= 1:
                    broker._consumer_positions[group_key] += 1

        # Verify adjustment
        assert broker._consumer_positions[f"{stream}:{consumer_group1}"] == 1
        assert broker._consumer_positions[f"{stream}:{consumer_group2}"] == 2


# ============= Edge Cases for Internal State =============


def test_remove_in_flight_message_when_not_exists(broker):
    """Test removing non-existent in-flight message."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    identifier = "non_existent"

    # Should not raise error
    broker._remove_in_flight_message(stream, consumer_group, identifier)

    # Verify no side effects
    group_key = f"{stream}:{consumer_group}"
    assert group_key not in broker._in_flight or len(broker._in_flight[group_key]) == 0


def test_get_in_flight_message_not_exists(broker):
    """Test getting non-existent in-flight message."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    identifier = "non_existent"

    result = broker._get_in_flight_message(stream, consumer_group, identifier)
    assert result is None


def test_cleanup_message_ownership_full_cleanup(broker):
    """Test full cleanup of message ownership."""
    identifier = "test_id"
    consumer_group = "test_group"

    # Add ownership
    broker._message_ownership[identifier] = {consumer_group: True}

    # Clean up
    broker._cleanup_message_ownership(identifier, consumer_group)

    # Entire identifier entry should be removed
    assert identifier not in broker._message_ownership


def test_cleanup_message_ownership_partial_cleanup(broker):
    """Test partial cleanup of message ownership."""
    identifier = "test_id"
    consumer_group1 = "group1"
    consumer_group2 = "group2"

    # Add ownership for multiple groups
    broker._message_ownership[identifier] = {
        consumer_group1: True,
        consumer_group2: True,
    }

    # Clean up only group1
    broker._cleanup_message_ownership(identifier, consumer_group1)

    # Only group1 should be removed
    assert identifier in broker._message_ownership
    assert consumer_group1 not in broker._message_ownership[identifier]
    assert consumer_group2 in broker._message_ownership[identifier]


def test_cleanup_message_ownership_edge_cases(broker):
    """Test message ownership cleanup edge cases."""
    identifier = "test_msg"
    consumer_group1 = "group1"
    consumer_group2 = "group2"

    # Add ownership for multiple groups
    broker._message_ownership[identifier] = {
        consumer_group1: True,
        consumer_group2: True,
    }

    # Clean up for group1
    broker._cleanup_message_ownership(identifier, consumer_group1)
    assert consumer_group1 not in broker._message_ownership[identifier]
    assert consumer_group2 in broker._message_ownership[identifier]

    # Clean up for group2 - should remove entire identifier entry
    broker._cleanup_message_ownership(identifier, consumer_group2)
    assert identifier not in broker._message_ownership

    # Test cleanup for non-existent entries (should not error)
    broker._cleanup_message_ownership("non_existent", "group")
    broker._cleanup_message_ownership(identifier, "non_existent_group")


def test_remove_retry_count_when_not_exists(broker):
    """Test removing non-existent retry count."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    identifier = "non_existent"

    # Should not raise error
    broker._remove_retry_count(stream, consumer_group, identifier)


def test_stale_message_cleanup_with_dlq_disabled(broker):
    """Test stale message cleanup when DLQ is disabled."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"test": "data"}

    # Configure with DLQ disabled
    broker._message_timeout = 0.01
    broker._enable_dlq = False

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Wait for timeout
    time.sleep(0.02)

    # Cleanup stale messages
    broker._cleanup_stale_messages(consumer_group, broker._message_timeout)

    # Message should be removed but not in DLQ
    group_key = f"{stream}:{consumer_group}"
    assert identifier not in broker._in_flight.get(group_key, {})
    assert (
        group_key not in broker._dead_letter_queue
        or len(broker._dead_letter_queue[group_key]) == 0
    )


def test_clear_operation_state_when_not_exists(broker):
    """Test clearing non-existent operation state."""
    consumer_group = "test_consumer_group"
    identifier = "non_existent"

    # Should not raise error
    broker._clear_operation_state(consumer_group, identifier)


def test_requeue_messages_empty_list(broker):
    """Test requeuing empty message list."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Should handle empty list gracefully
    broker._requeue_messages(stream, consumer_group, [])


def test_expired_operation_state_cleanup(broker):
    """Test cleanup of expired operation states."""
    consumer_group = "test_consumer_group"
    identifier1 = "msg1"
    identifier2 = "msg2"

    # Set operation state TTL to very short for testing
    broker._operation_state_ttl = 0.01  # 10ms

    # Store operation states
    broker._store_operation_state(
        consumer_group, identifier1, OperationState.ACKNOWLEDGED
    )
    time.sleep(0.02)  # Wait for expiry
    broker._store_operation_state(consumer_group, identifier2, OperationState.NACKED)

    # Try to get expired state - should return None and clean up
    state1 = broker._get_operation_state(consumer_group, identifier1)
    assert state1 is None
    assert identifier1 not in broker._operation_states[consumer_group]

    # Non-expired state should still be there
    state2 = broker._get_operation_state(consumer_group, identifier2)
    assert state2 == OperationState.NACKED

    # Test cleanup of all expired states
    time.sleep(0.02)
    broker._cleanup_expired_operation_states()

    # Consumer group should be removed when empty
    assert consumer_group not in broker._operation_states


def test_validate_message_ownership_not_exists(broker):
    """Test validating non-existent message ownership."""
    identifier = "non_existent"
    consumer_group = "test_consumer_group"

    result = broker._validate_message_ownership(identifier, consumer_group)
    assert result is False


def test_validate_message_ownership_wrong_group(broker):
    """Test validating message ownership for wrong group."""
    identifier = "test_id"
    consumer_group1 = "group1"
    consumer_group2 = "group2"

    # Add ownership for group1 only
    broker._message_ownership[identifier] = {consumer_group1: True}

    # Validate for group1 - should be True
    assert broker._validate_message_ownership(identifier, consumer_group1) is True

    # Validate for group2 - should be False
    assert broker._validate_message_ownership(identifier, consumer_group2) is False


def test_inline_broker_consumer_position_tracking(broker):
    """Test consumer position tracking across operations."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Publish messages
    for i in range(5):
        broker.publish(stream, {"id": i})

    # Track position through consumption
    group_key = f"{stream}:{consumer_group}"
    for expected_pos in range(1, 4):
        broker.get_next(stream, consumer_group)
        assert broker._consumer_positions[group_key] == expected_pos
