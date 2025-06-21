import pytest


@pytest.mark.broker
def test_for_no_error_on_no_message(broker):
    message = broker.get_next("test_stream", "test_consumer_group")
    assert message is None


@pytest.mark.broker
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


@pytest.mark.broker
def test_read_with_no_messages_available(broker):
    """Test read method when no messages are available"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Try to read from empty stream
    messages = broker.read(stream, consumer_group, 5)
    assert len(messages) == 0


@pytest.mark.broker
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


@pytest.mark.broker
def test_read_multiple_messages(broker):
    """Test read method with multiple messages"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Publish multiple messages
    broker.publish(stream, {"data": "msg1"})
    broker.publish(stream, {"data": "msg2"})
    broker.publish(stream, {"data": "msg3"})

    # Read multiple messages
    messages = broker.read(stream, consumer_group, 2)
    assert len(messages) == 2
    assert messages[0][1]["data"] == "msg1"
    assert messages[1][1]["data"] == "msg2"


@pytest.mark.broker
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

    # Should be a string UUID format
    assert isinstance(retrieved_identifier, str)
    assert len(retrieved_identifier) == 36  # Standard UUID length with hyphens
    assert retrieved_identifier.count("-") == 4  # UUID has 4 hyphens
    assert retrieved_identifier == identifier
