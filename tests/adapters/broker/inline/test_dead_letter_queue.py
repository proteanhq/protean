"""Tests for Dead Letter Queue (DLQ) functionality in InlineBroker."""

import logging
import time
from unittest.mock import patch


def test_dlq_message_inspection(broker):
    """Test that messages in DLQ can be inspected."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with no retries to send straight to DLQ
    broker._max_retries = 0

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None

    # NACK message - should go straight to DLQ
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Inspect DLQ messages
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert stream in dlq_messages
    assert len(dlq_messages[stream]) == 1

    dlq_entry = dlq_messages[stream][0]
    assert dlq_entry[0] == identifier  # Message ID
    assert dlq_entry[1] == message  # Message content
    assert dlq_entry[2] == "max_retries_exceeded"  # Failure reason
    assert isinstance(dlq_entry[3], float)  # Timestamp


def test_dlq_message_reprocessing(broker):
    """Test that messages can be moved from DLQ back to main queue."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with no retries
    broker._max_retries = 0

    # Publish, get, and NACK message to send to DLQ
    identifier = broker.publish(stream, message)
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None
    broker.nack(stream, identifier, consumer_group)

    # Verify message is in DLQ
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert len(dlq_messages[stream]) == 1

    # Reprocess message from DLQ
    reprocess_result = broker.reprocess_dlq_message(identifier, consumer_group, stream)
    assert reprocess_result is True

    # Verify message is no longer in DLQ
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert len(dlq_messages[stream]) == 0

    # Message should be available for consumption again
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None
    retrieved_id, retrieved_msg = retrieved
    assert retrieved_id == identifier
    assert retrieved_msg == message


def test_dlq_multiple_messages(broker):
    """Test DLQ can handle multiple messages."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    messages = [{"id": i} for i in range(5)]

    # Configure broker with no retries
    broker._max_retries = 0

    # Publish all messages
    identifiers = []
    for msg in messages:
        identifiers.append(broker.publish(stream, msg))

    # Get and NACK all messages
    for _ in messages:
        retrieved = broker.get_next(stream, consumer_group)
        assert retrieved is not None
        msg_id, _ = retrieved
        broker.nack(stream, msg_id, consumer_group)

    # All messages should be in DLQ
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert len(dlq_messages[stream]) == 5

    # Verify all messages are present
    dlq_ids = [entry[0] for entry in dlq_messages[stream]]
    for identifier in identifiers:
        assert identifier in dlq_ids


def test_dlq_cross_consumer_group_isolation(broker):
    """Test that DLQ messages are isolated per consumer group."""
    stream = "test_stream"
    consumer_group1 = "group1"
    consumer_group2 = "group2"
    message = {"foo": "bar"}

    # Configure broker with no retries
    broker._max_retries = 0

    # Publish message
    identifier = broker.publish(stream, message)

    # Group 1: Get and NACK message
    retrieved = broker.get_next(stream, consumer_group1)
    assert retrieved is not None
    broker.nack(stream, identifier, consumer_group1)

    # Group 2: Get and ACK message
    retrieved = broker.get_next(stream, consumer_group2)
    assert retrieved is not None
    broker.ack(stream, identifier, consumer_group2)

    # Only group1 should have message in DLQ
    dlq_messages1 = broker.get_dlq_messages(consumer_group1, stream)
    assert len(dlq_messages1[stream]) == 1

    dlq_messages2 = broker.get_dlq_messages(consumer_group2, stream)
    assert stream not in dlq_messages2 or len(dlq_messages2.get(stream, [])) == 0


def test_dlq_info_tracking(broker):
    """Test that DLQ messages are tracked in broker info."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with no retries
    broker._max_retries = 0

    # Publish, get, and NACK message
    identifier = broker.publish(stream, message)
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None
    broker.nack(stream, identifier, consumer_group)

    # Check broker info
    info = broker.info()
    assert consumer_group in info["consumer_groups"]
    group_info = info["consumer_groups"][consumer_group]
    assert "dlq_messages" in group_info
    assert stream in group_info["dlq_messages"]
    assert group_info["dlq_messages"][stream] == 1


def test_get_dlq_messages_no_messages(broker):
    """Test getting DLQ messages when there are none."""
    consumer_group = "test_consumer_group"
    stream = "test_stream"

    # Get all DLQ messages (without specifying stream) first
    # This should return empty dict when no DLQ entries exist
    dlq_messages = broker.get_dlq_messages(consumer_group)
    assert dlq_messages == {}

    # Get DLQ messages for specific stream
    # This creates an entry with empty list for the stream
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert stream in dlq_messages
    assert dlq_messages[stream] == []


def test_get_dlq_messages_specific_stream(broker):
    """Test getting DLQ messages for a specific stream."""
    stream1 = "stream1"
    stream2 = "stream2"
    consumer_group = "test_consumer_group"

    # Configure broker with no retries
    broker._max_retries = 0

    # Publish to both streams
    id1 = broker.publish(stream1, {"stream": 1})
    id2 = broker.publish(stream2, {"stream": 2})

    # Get and NACK from both streams
    broker.get_next(stream1, consumer_group)
    broker.nack(stream1, id1, consumer_group)

    broker.get_next(stream2, consumer_group)
    broker.nack(stream2, id2, consumer_group)

    # Get DLQ messages for specific stream
    dlq_messages = broker.get_dlq_messages(consumer_group, stream1)
    assert stream1 in dlq_messages
    assert len(dlq_messages[stream1]) == 1
    assert stream2 not in dlq_messages


def test_get_dlq_messages_all_streams(broker):
    """Test getting DLQ messages for all streams."""
    stream1 = "stream1"
    stream2 = "stream2"
    consumer_group = "test_consumer_group"

    # Configure broker with no retries
    broker._max_retries = 0

    # Publish to both streams
    id1 = broker.publish(stream1, {"stream": 1})
    id2 = broker.publish(stream2, {"stream": 2})

    # Get and NACK from both streams
    broker.get_next(stream1, consumer_group)
    broker.nack(stream1, id1, consumer_group)

    broker.get_next(stream2, consumer_group)
    broker.nack(stream2, id2, consumer_group)

    # Get all DLQ messages
    dlq_messages = broker.get_dlq_messages(consumer_group)
    assert stream1 in dlq_messages
    assert stream2 in dlq_messages
    assert len(dlq_messages[stream1]) == 1
    assert len(dlq_messages[stream2]) == 1


def test_reprocess_dlq_message_not_found(broker):
    """Test reprocessing a DLQ message that doesn't exist."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Try to reprocess non-existent message
    result = broker.reprocess_dlq_message("non_existent", consumer_group, stream)
    assert result is False


def test_max_retries_exceeded_dlq_disabled(broker):
    """Test behavior when max retries exceeded but DLQ is disabled."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Configure broker with DLQ disabled
    broker._max_retries = 0
    broker._enable_dlq = False

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None

    # NACK message - should be discarded, not moved to DLQ
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Verify no message in DLQ
    dlq_messages = broker.get_dlq_messages(consumer_group, stream)
    assert stream not in dlq_messages or len(dlq_messages.get(stream, [])) == 0

    # Message should not be available for consumption
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is None


def test_get_dlq_messages_consumer_group_not_found(broker):
    """Test getting DLQ messages for non-existent consumer group."""
    consumer_group = "non_existent_group"
    stream = "test_stream"

    # Get all DLQ messages for consumer group (should be empty)
    result = broker._get_dlq_messages(consumer_group)
    assert result == {}

    # Add some DLQ messages for a different group
    other_group = "other_group"
    group_key = f"{stream}:{other_group}"
    broker._dead_letter_queue[group_key].append(
        ("msg1", {"data": "test"}, "timeout", time.time())
    )

    # Should still return empty for non_existent_group
    result = broker._get_dlq_messages(consumer_group)
    assert result == {}

    # But should return data for other_group
    result = broker._get_dlq_messages(other_group)
    assert stream in result
    assert len(result[stream]) == 1


def test_reprocess_dlq_message_position_adjustment(broker):
    """Test DLQ message reprocessing with position adjustments."""
    stream = "test_stream"
    consumer_group1 = "group1"
    consumer_group2 = "group2"

    # Setup initial messages
    broker._messages[stream] = [
        ("msg1", {"data": "1"}),
        ("msg2", {"data": "2"}),
    ]

    # Set positions for multiple consumer groups
    group_key1 = f"{stream}:{consumer_group1}"
    group_key2 = f"{stream}:{consumer_group2}"
    broker._consumer_positions[group_key1] = 1
    broker._consumer_positions[group_key2] = 1

    # Add message to DLQ
    dlq_msg_id = "dlq_msg"
    dlq_msg_data = {"data": "dlq"}
    broker._dead_letter_queue[group_key1].append(
        (dlq_msg_id, dlq_msg_data, "timeout", time.time())
    )

    # Reprocess the message
    result = broker._reprocess_dlq_message(dlq_msg_id, consumer_group1, stream)
    assert result is True

    # Verify message was inserted at correct position
    assert broker._messages[stream][1] == (dlq_msg_id, dlq_msg_data)

    # Verify other consumer group position was adjusted
    assert broker._consumer_positions[group_key2] == 2
    # Group1 position should not change (it's at the insertion point)
    assert broker._consumer_positions[group_key1] == 1


def test_reprocess_dlq_message_error_handling(broker):
    """Test reprocessing DLQ message with error conditions."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    identifier = "test_msg"

    # Test with exception during processing
    group_key = f"{stream}:{consumer_group}"
    broker._dead_letter_queue[group_key] = None  # Invalid data to cause error

    with patch.object(logging.getLogger("protean.adapters.broker.inline"), "error"):
        result = broker._reprocess_dlq_message(identifier, consumer_group, stream)
        assert result is False
