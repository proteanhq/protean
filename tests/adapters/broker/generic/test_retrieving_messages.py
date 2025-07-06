import pytest


@pytest.mark.simple_queuing
def test_for_no_error_on_no_message(broker):
    message = broker.get_next("test_stream", "test_consumer_group")
    assert message is None


@pytest.mark.simple_queuing
def test_get_next_message(broker):
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message1 = {"key1": "value1"}
    message2 = {"key2": "value2"}

    broker.publish(stream, message1)
    broker.publish(stream, message2)

    # Retrieve the first message
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message[1] == message1

    # Retrieve the second message
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message[1] == message2

    # No more messages, should return an empty dict
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is None


@pytest.mark.simple_queuing
def test_read_with_no_messages_available(broker):
    """Test read method when no messages are available"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Try to read from empty stream
    messages = broker.read(stream, consumer_group, 5)
    assert len(messages) == 0


@pytest.mark.simple_queuing
def test_read_fewer_messages_than_requested(broker):
    """Test read method when fewer messages available than requested"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Publish only 2 messages
    broker.publish(stream, {"data": "msg1"})
    broker.publish(stream, {"data": "msg2"})

    # Try to read 5 messages
    messages = broker.read(stream, consumer_group, 5)
    assert len(messages) == 2


@pytest.mark.simple_queuing
def test_read_multiple_messages(broker):
    """Test reading multiple messages at once"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    messages = [{"id": i, "data": f"message_{i}"} for i in range(5)]

    # Publish messages
    identifiers = []
    for message in messages:
        identifier = broker.publish(stream, message)
        identifiers.append(identifier)

    # Read multiple messages
    retrieved_messages = broker.read(stream, consumer_group, 3)

    # Should get exactly 3 messages
    assert len(retrieved_messages) == 3

    # Verify messages are correct
    for i, (identifier, message) in enumerate(retrieved_messages):
        assert identifier == identifiers[i]
        assert message == messages[i]


@pytest.mark.simple_queuing
def test_read_more_than_available(broker):
    """Test reading more messages than available"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "single message"}

    # Publish only one message
    identifier = broker.publish(stream, message)

    # Try to read 5 messages
    retrieved_messages = broker.read(stream, consumer_group, 5)

    # Should get only the one available message
    assert len(retrieved_messages) == 1
    assert retrieved_messages[0][0] == identifier
    assert retrieved_messages[0][1] == message


@pytest.mark.simple_queuing
def test_read_from_empty_stream(broker):
    """Test reading from empty stream"""
    stream = "empty_stream"
    consumer_group = "test_consumer_group"

    # Try to read from empty stream
    retrieved_messages = broker.read(stream, consumer_group, 3)

    # Should get empty list
    assert len(retrieved_messages) == 0


@pytest.mark.simple_queuing
def test_get_next_generates_uuid_identifier(broker):
    """Test that get_next returns messages with UUID identifiers"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"data": "test"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Get the message
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None

    retrieved_identifier, retrieved_payload = retrieved_message

    # Should be a non-empty string identifier
    assert isinstance(retrieved_identifier, str)
    assert len(retrieved_identifier) > 0
    assert retrieved_identifier == identifier
