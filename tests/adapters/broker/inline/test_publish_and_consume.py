"""Tests for publishing and consuming messages with InlineBroker."""

import uuid

import pytest

from ..elements import Person, PersonAdded


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonAdded, part_of=Person)
    test_domain.init(traverse=False)


# ============= Publishing Tests =============


def test_publish_generic_message_to_stream(test_domain):
    stream = "test_stream"
    message = {"foo": "bar"}

    identifier = test_domain.brokers["default"].publish(stream, message)

    # Verify identifier is always returned as string
    assert identifier is not None
    assert isinstance(identifier, str)
    assert len(identifier) > 0

    # Verify message is stored as tuple (identifier, message)
    assert len(test_domain.brokers["default"]._messages[stream]) == 1
    stored_tuple = test_domain.brokers["default"]._messages[stream][0]
    assert isinstance(stored_tuple, tuple)
    assert len(stored_tuple) == 2
    assert stored_tuple[0] == identifier
    assert stored_tuple[1] == message


def test_event_message_to_stream(test_domain):
    person = Person.add_newcomer(
        {"id": "1", "first_name": "John", "last_name": "Doe", "age": 21}
    )
    event = person._events[0]

    identifier = test_domain.brokers["default"].publish("test_stream", event.to_dict())

    # Verify identifier is always returned as string
    assert identifier is not None
    assert isinstance(identifier, str)
    assert len(identifier) > 0

    # Verify message is stored as tuple (identifier, message)
    assert len(test_domain.brokers["default"]._messages["test_stream"]) == 1
    stored_tuple = test_domain.brokers["default"]._messages["test_stream"][0]
    assert isinstance(stored_tuple, tuple)
    assert len(stored_tuple) == 2
    assert stored_tuple[0] == identifier
    assert stored_tuple[1] == event.to_dict()


def test_uuid_generation_in_publish(broker):
    """Test that publish generates UUID-format identifiers."""
    stream = "test_stream"
    message = {"foo": "bar"}

    identifier = broker.publish(stream, message)

    # Verify it's a valid UUID
    try:
        uuid_obj = uuid.UUID(identifier)
        assert str(uuid_obj) == identifier
    except ValueError:
        pytest.fail(f"Identifier '{identifier}' is not a valid UUID")


def test_reliable_messaging_broker_publish_generates_uuid_format(broker):
    """Test that reliable messaging broker generates UUID-format identifiers."""
    stream = "test_stream"
    message = {"test": "data"}

    identifier = broker.publish(stream, message)

    # Should be a valid UUID string
    assert identifier is not None
    assert isinstance(identifier, str)
    assert len(identifier) == 36  # Standard UUID string length

    # Verify it's a valid UUID
    try:
        uuid_obj = uuid.UUID(identifier)
        assert str(uuid_obj) == identifier
    except ValueError:
        pytest.fail(f"Identifier '{identifier}' is not a valid UUID")


# ============= Consuming Tests =============


def test_get_next_basic_consumption(broker):
    """Test basic message consumption."""
    stream = "test_stream"
    consumer_group = "test_group"
    message = {"foo": "bar"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Consume the message
    result = broker.get_next(stream, consumer_group)
    assert result is not None
    retrieved_id, retrieved_msg = result
    assert retrieved_id == identifier
    assert retrieved_msg == message

    # No more messages available
    result = broker.get_next(stream, consumer_group)
    assert result is None


def test_reliable_messaging_broker_retrieved_message_has_uuid_identifier(broker):
    """Test that retrieved messages have UUID identifiers."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    message = {"test": "data"}

    # Publish a message
    published_id = broker.publish(stream, message)

    # Get the message
    retrieved_message = broker.get_next(stream, consumer_group)
    assert retrieved_message is not None
    retrieved_id, retrieved_payload = retrieved_message

    # Verify identifier is a UUID
    assert retrieved_id == published_id
    try:
        uuid_obj = uuid.UUID(retrieved_id)
        assert str(uuid_obj) == retrieved_id
    except ValueError:
        pytest.fail(f"Retrieved identifier '{retrieved_id}' is not a valid UUID")


def test_reliable_messaging_broker_get_next_generates_uuid_identifier(broker):
    """Test that get_next returns messages with UUID identifiers."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Publish multiple messages
    messages = [{"data": i} for i in range(3)]
    published_ids = []
    for msg in messages:
        published_ids.append(broker.publish(stream, msg))

    # Get all messages and verify identifiers
    for i, expected_msg in enumerate(messages):
        result = broker.get_next(stream, consumer_group)
        assert result is not None
        retrieved_id, retrieved_msg = result

        # Verify it's a UUID
        try:
            uuid_obj = uuid.UUID(retrieved_id)
            assert str(uuid_obj) == retrieved_id
        except ValueError:
            pytest.fail(f"Retrieved identifier '{retrieved_id}' is not a valid UUID")

        # Verify it matches published ID
        assert retrieved_id == published_ids[i]
        assert retrieved_msg == expected_msg


def test_cross_stream_message_isolation(broker):
    """Test that messages in different streams are isolated."""
    stream1 = "stream1"
    stream2 = "stream2"
    consumer_group = "test_consumer_group"
    message1 = {"stream": "1"}
    message2 = {"stream": "2"}

    # Publish to different streams
    id1 = broker.publish(stream1, message1)
    id2 = broker.publish(stream2, message2)

    # Consume from stream1
    result = broker.get_next(stream1, consumer_group)
    assert result is not None
    retrieved_id, retrieved_msg = result
    assert retrieved_id == id1
    assert retrieved_msg == message1

    # No more messages in stream1
    result = broker.get_next(stream1, consumer_group)
    assert result is None

    # Stream2 still has its message
    result = broker.get_next(stream2, consumer_group)
    assert result is not None
    retrieved_id, retrieved_msg = result
    assert retrieved_id == id2
    assert retrieved_msg == message2


def test_message_deduplication_within_consumer_group(broker):
    """Test that messages are not duplicated within a consumer group."""
    stream = "test_stream"
    consumer_group = "test_consumer_group"

    # Publish messages
    messages = [{"id": i} for i in range(5)]
    for msg in messages:
        broker.publish(stream, msg)

    # Consume all messages
    consumed = []
    while True:
        result = broker.get_next(stream, consumer_group)
        if result is None:
            break
        _, msg = result
        consumed.append(msg)

    # Verify all messages consumed exactly once
    assert len(consumed) == len(messages)
    for msg in messages:
        assert msg in consumed


def test_inline_broker_message_storage_format(broker):
    """Test the internal storage format of messages."""
    stream = "test_stream"
    message = {"test": "data"}

    # Publish a message
    identifier = broker.publish(stream, message)

    # Check internal storage structure
    assert stream in broker._messages
    assert len(broker._messages[stream]) == 1

    # Messages stored as tuples (identifier, message)
    stored_tuple = broker._messages[stream][0]
    assert isinstance(stored_tuple, tuple)
    assert len(stored_tuple) == 2
    assert stored_tuple[0] == identifier
    assert stored_tuple[1] == message
