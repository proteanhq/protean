import pytest


@pytest.mark.reliable_messaging
def test_ack_successful_message_processing(broker):
    """Test that successfully processed messages can be acknowledged"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get the message (moves to in-flight)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    retrieved_identifier, retrieved_payload = retrieved_message
    assert retrieved_identifier == identifier
    assert retrieved_payload == message

    # Acknowledge the message
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Verify message is no longer available
    next_message = broker.get_next(stream, consumer_group)
    assert next_message is None


@pytest.mark.reliable_messaging
def test_ack_unknown_message(broker):
    """Test that acknowledging an unknown message returns False"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    unknown_identifier = "unknown-message-id"

    # Ensure consumer group exists
    broker._ensure_group(consumer_group, stream)

    # Try to acknowledge a message that doesn't exist
    ack_result = broker.ack(stream, unknown_identifier, consumer_group)
    assert ack_result is False


@pytest.mark.reliable_messaging
def test_ack_already_processed_message(broker):
    """Test that acknowledging an already acknowledged message returns False"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Acknowledge the message once
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Try to acknowledge the same message again
    ack_result_second = broker.ack(stream, identifier, consumer_group)
    assert ack_result_second is False


@pytest.mark.reliable_messaging
def test_multiple_consumers_different_groups(broker):
    """Test that different consumer groups can independently acknowledge messages"""
    stream = "test_stream"
    consumer_group_1 = "group_1"
    consumer_group_2 = "group_2"
    message = {"foo": "bar"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Each consumer group gets its own copy of the message
    retrieved_message_1 = broker.get_next(stream, consumer_group_1)
    retrieved_message_2 = broker.get_next(stream, consumer_group_2)

    # Both should get the same message with the same identifier
    assert retrieved_message_1 is not None
    assert retrieved_message_2 is not None
    assert retrieved_message_1[0] == identifier
    assert retrieved_message_2[0] == identifier

    # Acknowledge from group 1
    ack_result_1 = broker.ack(stream, identifier, consumer_group_1)
    assert ack_result_1 is True

    # Acknowledge from group 2 should still work
    ack_result_2 = broker.ack(stream, identifier, consumer_group_2)
    assert ack_result_2 is True


@pytest.mark.reliable_messaging
def test_ack_nonexistent_consumer_group(broker):
    """Test that acknowledging from a non-existent consumer group returns False"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    nonexistent_group = "nonexistent_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Try to acknowledge from a non-existent consumer group
    ack_result = broker.ack(stream, identifier, nonexistent_group)
    assert ack_result is False


@pytest.mark.reliable_messaging
def test_ack_message_ownership_validation(broker):
    """Test that messages can only be acknowledged by the consumer group that received them"""
    stream = "test_stream"
    consumer_group_1 = "group_1"
    consumer_group_2 = "group_2"
    message = {"foo": "bar"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Group 1 gets the message
    retrieved_message = broker.get_next(stream, consumer_group_1)
    assert retrieved_message is not None
    assert retrieved_message[0] == identifier

    # Group 2 should not be able to acknowledge a message it didn't receive
    ack_result = broker.ack(stream, identifier, consumer_group_2)
    assert ack_result is False

    # Group 1 should be able to acknowledge its own message
    ack_result = broker.ack(stream, identifier, consumer_group_1)
    assert ack_result is True


@pytest.mark.reliable_messaging
def test_ack_cross_stream_isolation(broker):
    """Test that acknowledging messages from different streams works correctly"""
    stream1 = "test_stream_1"
    stream2 = "test_stream_2"
    consumer_group = "test_consumer_group"
    message1 = {"stream": 1}
    message2 = {"stream": 2}

    # Publish messages to different streams
    id1 = broker.publish(stream1, message1)
    id2 = broker.publish(stream2, message2)

    # Get messages from both streams
    msg1 = broker.get_next(stream1, consumer_group)
    msg2 = broker.get_next(stream2, consumer_group)

    assert msg1 is not None
    assert msg2 is not None
    assert msg1[0] == id1
    assert msg2[0] == id2

    # Acknowledge both messages
    ack_result1 = broker.ack(stream1, id1, consumer_group)
    ack_result2 = broker.ack(stream2, id2, consumer_group)

    assert ack_result1 is True
    assert ack_result2 is True


@pytest.mark.reliable_messaging
def test_ack_with_invalid_consumer_group(broker):
    """Test ack with non-existent consumer group"""
    stream = "test_stream"
    identifier = "test-id"
    consumer_group = "non-existent-group"

    result = broker.ack(stream, identifier, consumer_group)
    assert result is False


@pytest.mark.reliable_messaging
def test_ack_with_wrong_message_ownership(broker):
    """Test ack with message not owned by consumer group"""
    stream = "test_stream"
    consumer_group = "test_group"
    other_group = "other_group"
    message = {"data": "test"}

    # Publish and consume with different group
    identifier = broker.publish(stream, message)
    broker.get_next(stream, other_group)  # Different group consumes

    # Try to ack with original group
    result = broker.ack(stream, identifier, consumer_group)
    assert result is False
