import pytest


@pytest.mark.broker
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


@pytest.mark.broker
def test_ack_unknown_message(broker):
    """Test that acknowledging an unknown message returns False"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    unknown_identifier = "unknown-message-id"

    # Ensure consumer group exists
    broker._ensure_group(consumer_group)

    # Try to acknowledge a message that doesn't exist
    ack_result = broker.ack(stream, unknown_identifier, consumer_group)
    assert ack_result is False


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
def test_ack_removes_from_in_flight_tracking(broker):
    """Test that acknowledging a message removes it from in-flight tracking"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message1 = {"id": 1}
    message2 = {"id": 2}

    # Publish two messages
    id1 = broker.publish(stream, message1)
    broker.publish(stream, message2)

    # Get both messages (both in-flight)
    msg1 = broker.get_next(stream, consumer_group)
    msg2 = broker.get_next(stream, consumer_group)

    assert msg1 is not None
    assert msg2 is not None

    # Check broker info shows in-flight messages
    info = broker.info()
    if consumer_group in info["consumer_groups"]:
        in_flight_info = info["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            assert in_flight_info[stream] == 2

    # Acknowledge first message
    ack_result = broker.ack(stream, id1, consumer_group)
    assert ack_result is True

    # Check that in-flight count decreased
    info = broker.info()
    if consumer_group in info["consumer_groups"]:
        in_flight_info = info["consumer_groups"][consumer_group].get(
            "in_flight_messages", {}
        )
        if stream in in_flight_info:
            assert in_flight_info[stream] == 1


@pytest.mark.broker
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


@pytest.mark.broker
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


@pytest.mark.broker
def test_ack_cleans_up_message_ownership(broker):
    """Test that acknowledging a message cleans up ownership tracking"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Verify ownership is tracked (implementation-specific check)
    if hasattr(broker, "_message_ownership"):
        assert identifier in broker._message_ownership
        assert consumer_group in broker._message_ownership[identifier]

    # Acknowledge the message
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Verify ownership is cleaned up
    if hasattr(broker, "_message_ownership"):
        assert identifier not in broker._message_ownership


@pytest.mark.broker
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


@pytest.mark.broker
def test_ack_message_already_nacked(broker):
    """Test ack when message already nacked"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Nack first
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is True

    # Try to ack after nack - should fail
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is False


@pytest.mark.broker
def test_ack_with_invalid_consumer_group(broker):
    """Test ack with non-existent consumer group"""
    stream = "test_stream"
    identifier = "test-id"
    consumer_group = "non-existent-group"

    result = broker.ack(stream, identifier, consumer_group)
    assert result is False


@pytest.mark.broker
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


@pytest.mark.broker
def test_ack_message_already_acknowledged_idempotent(broker):
    """Test ack idempotency when message already acknowledged"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Acknowledge once
    result1 = broker.ack(stream, identifier, consumer_group)
    assert result1 is True

    # Try to acknowledge again - should be idempotent
    result2 = broker.ack(stream, identifier, consumer_group)
    assert result2 is False
