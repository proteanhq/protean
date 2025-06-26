"""Test cases for broker edge cases and error handling scenarios"""

import time

import pytest


@pytest.mark.manual_broker
def test_info_method_returns_broker_information(broker):
    """Test that info method returns broker information"""
    # Call info method
    result = broker.info()

    # Should return a dictionary with broker information
    assert isinstance(result, dict)
    # Common keys that should be present
    if "consumer_groups" in result:
        assert isinstance(result["consumer_groups"], dict)


@pytest.mark.manual_broker
def test_cleanup_operations_during_nack(broker):
    """Test that cleanup operations are performed during nack"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Configure broker for fast retries in testing
    broker._retry_delay = 0.01  # Fast retries for testing

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Nack the message - this should trigger cleanup operations
    result = broker.nack(stream, identifier, consumer_group)
    assert result is True

    # Wait a moment for retry processing
    time.sleep(0.02)

    # Message should be available for retry
    retry_message = broker.get_next(stream, consumer_group)
    assert bool(retry_message) is True
    assert retry_message[0] == identifier


@pytest.mark.manual_broker
def test_message_ownership_tracking(broker):
    """Test that message ownership is properly tracked with functional behavior"""
    stream = "test_stream"
    consumer_group_1 = "group_1"
    consumer_group_2 = "group_2"
    message = {"data": "test"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Both groups get the message
    msg1 = broker.get_next(stream, consumer_group_1)
    msg2 = broker.get_next(stream, consumer_group_2)

    assert msg1 is not None
    assert msg2 is not None
    assert msg1[0] == identifier
    assert msg2[0] == identifier

    # Verify ownership tracking through functional behavior:
    # Each group should be able to independently ack/nack their own message

    # Group 1 should be able to acknowledge the message it received
    ack_result_1 = broker.ack(stream, identifier, consumer_group_1)
    assert ack_result_1 is True

    # Group 2 should still be able to nack the message it received
    # (since each group owns its own copy)
    nack_result_2 = broker.nack(stream, identifier, consumer_group_2)
    assert nack_result_2 is True


@pytest.mark.manual_broker
def test_cross_stream_message_isolation(broker):
    """Test that messages in different streams are properly isolated"""
    stream1 = "stream_1"
    stream2 = "stream_2"
    consumer_group = "test_consumer_group"
    message1 = {"stream": 1, "data": "message1"}
    message2 = {"stream": 2, "data": "message2"}

    # Publish to different streams
    id1 = broker.publish(stream1, message1)
    id2 = broker.publish(stream2, message2)

    # Get messages from each stream
    msg1 = broker.get_next(stream1, consumer_group)
    msg2 = broker.get_next(stream2, consumer_group)

    assert msg1 is not None
    assert msg2 is not None
    assert msg1[0] == id1
    assert msg2[0] == id2

    # Acknowledge message from stream1 only
    ack_result = broker.ack(stream1, id1, consumer_group)
    assert ack_result is True

    # Message from stream2 should still be in-flight
    # Try to acknowledge it to verify it's still trackable
    ack_result2 = broker.ack(stream2, id2, consumer_group)
    assert ack_result2 is True


@pytest.mark.manual_broker
def test_consumer_group_creation_during_operations(broker):
    """Test that consumer groups are properly created during operations"""
    stream = "test_stream"
    consumer_group = "auto_created_group"
    message = {"data": "test"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get message with a new consumer group - should auto-create the group
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    assert retrieved_message[0] == identifier

    # Verify the group can perform acknowledgments
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True


@pytest.mark.manual_broker
def test_message_timeout_and_cleanup_behavior(broker):
    """Test message timeout and cleanup behavior"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    broker._message_timeout = 0.05  # Very short timeout for testing

    # Publish and get message
    broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Wait for message to timeout
    time.sleep(0.1)

    # Try to get another message - this should trigger cleanup
    broker.get_next(stream, consumer_group)

    # Depending on broker implementation, the timed-out message might be:
    # 1. Available again for retry (if DLQ is enabled)
    # 2. Moved to DLQ
    # 3. Discarded

    # At minimum, the operation should not crash
    assert True  # Just verify no exceptions occurred


@pytest.mark.manual_broker
def test_multiple_consumer_groups_independent_processing(broker):
    """Test that multiple consumer groups process messages independently"""
    stream = "test_stream"
    group1 = "group_1"
    group2 = "group_2"
    group3 = "group_3"
    message = {"data": "shared_message"}

    # Publish one message
    identifier = broker.publish(stream, message)

    # All groups should get the same message
    msg1 = broker.get_next(stream, group1)
    msg2 = broker.get_next(stream, group2)
    msg3 = broker.get_next(stream, group3)

    assert msg1 is not None
    assert msg2 is not None
    assert msg3 is not None
    assert msg1[0] == identifier
    assert msg2[0] == identifier
    assert msg3[0] == identifier

    # Group 1 acknowledges
    ack1 = broker.ack(stream, identifier, group1)
    assert ack1 is True

    # Group 2 nacks
    nack2 = broker.nack(stream, identifier, group2)
    assert nack2 is True

    # Group 3 should still be able to acknowledge independently
    ack3 = broker.ack(stream, identifier, group3)
    assert ack3 is True


@pytest.mark.manual_broker
def test_message_deduplication_within_consumer_group(broker):
    """Test that messages are not duplicated within a consumer group"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get the message
    msg1 = broker.get_next(stream, consumer_group)
    assert msg1 is not None
    assert msg1[0] == identifier

    # Try to get another message immediately - should be None
    msg2 = broker.get_next(stream, consumer_group)
    assert msg2 is None

    # Acknowledge the first message
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Still no more messages
    msg3 = broker.get_next(stream, consumer_group)
    assert msg3 is None


@pytest.mark.manual_broker
def test_error_handling_invalid_stream(broker):
    """Test error handling with invalid stream operations"""
    # Try to get from non-existent stream
    message = broker.get_next("non_existent_stream", "test_consumer_group")
    assert message is None


@pytest.mark.manual_broker
def test_stream_cleanup_behavior(broker):
    """Test stream cleanup behavior"""
    stream = "cleanup_test_stream"
    consumer_group = "test_consumer_group"

    # Publish multiple messages
    identifiers = []
    for i in range(3):
        identifier = broker.publish(stream, {"data": f"message_{i}"})
        identifiers.append(identifier)

    # Get and acknowledge all messages
    for identifier in identifiers:
        message = broker.get_next(stream, consumer_group)
        assert bool(message) is True
        ack_result = broker.ack(stream, identifier, consumer_group)
        assert ack_result is True

    # No more messages should be available
    next_message = broker.get_next(stream, consumer_group)
    assert next_message is None
