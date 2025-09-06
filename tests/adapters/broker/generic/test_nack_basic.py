import pytest


@pytest.mark.reliable_messaging
def test_nack_unknown_message(broker):
    """Test that nacking an unknown message returns False"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    unknown_identifier = "unknown-message-id"

    # Ensure consumer group exists
    broker._ensure_group(consumer_group, stream)

    # Try to nack a message that doesn't exist
    nack_result = broker.nack(stream, unknown_identifier, consumer_group)
    assert nack_result is False


@pytest.mark.reliable_messaging
def test_nack_already_processed_message(broker):
    """Test that nacking an already acknowledged message returns False"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Acknowledge the message
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Try to nack the acknowledged message
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is False


@pytest.mark.reliable_messaging
def test_mixed_ack_nack_workflow(broker):
    """Test mixed ack and nack operations"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message1 = {"id": 1}
    message2 = {"id": 2}

    # Publish two messages
    id1 = broker.publish(stream, message1)
    id2 = broker.publish(stream, message2)

    # Get both messages
    msg1 = broker.get_next(stream, consumer_group)
    msg2 = broker.get_next(stream, consumer_group)

    assert msg1 is not None
    assert msg2 is not None

    # Ack first message
    ack_result = broker.ack(stream, id1, consumer_group)
    assert ack_result is True

    # Nack second message
    nack_result = broker.nack(stream, id2, consumer_group)
    assert nack_result is True


@pytest.mark.reliable_messaging
def test_nack_nonexistent_consumer_group(broker):
    """Test that nacking from a non-existent consumer group returns False"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    nonexistent_group = "nonexistent_group"
    message = {"foo": "bar"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    # Try to nack from a non-existent consumer group
    nack_result = broker.nack(stream, identifier, nonexistent_group)
    assert nack_result is False


@pytest.mark.reliable_messaging
def test_nack_message_ownership_validation(broker):
    """Test that messages can only be nacked by the consumer group that received them"""
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

    # Group 2 should not be able to nack a message it didn't receive
    nack_result = broker.nack(stream, identifier, consumer_group_2)
    assert nack_result is False

    # Group 1 should be able to nack its own message
    nack_result = broker.nack(stream, identifier, consumer_group_1)
    assert nack_result is True


@pytest.mark.reliable_messaging
def test_nack_with_invalid_consumer_group(broker):
    """Test nack with non-existent consumer group"""
    stream = "test_stream"
    identifier = "test-id"
    consumer_group = "non-existent-group"

    result = broker.nack(stream, identifier, consumer_group)
    assert result is False


@pytest.mark.reliable_messaging
def test_nack_with_wrong_message_ownership(broker):
    """Test nack with message not owned by consumer group"""
    stream = "test_stream"
    consumer_group = "test_group"
    other_group = "other_group"
    message = {"data": "test"}

    # Publish and consume with different group
    identifier = broker.publish(stream, message)
    broker.get_next(stream, other_group)  # Different group consumes

    # Try to nack with original group
    result = broker.nack(stream, identifier, consumer_group)
    assert result is False


@pytest.mark.reliable_messaging
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

    # Try to ack after nack
    # In Redis Streams, a NACKed (pending) message can still be ACKed
    # This is the correct behavior - NACK just means the message stays pending
    ack_result = broker.ack(stream, identifier, consumer_group)
    # For Redis, this should succeed
    assert ack_result is True


@pytest.mark.reliable_messaging
def test_nack_message_already_acknowledged(broker):
    """Test nack when message already acknowledged"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish and get message
    identifier = broker.publish(stream, message)
    broker.get_next(stream, consumer_group)

    # Ack first
    ack_result = broker.ack(stream, identifier, consumer_group)
    assert ack_result is True

    # Try to nack after ack - should fail
    nack_result = broker.nack(stream, identifier, consumer_group)
    assert nack_result is False
