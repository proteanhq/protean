import uuid

import pytest

from protean.core.unit_of_work import UnitOfWork

from ..elements import Person, PersonAdded


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonAdded, part_of=Person)
    test_domain.init(traverse=False)


@pytest.mark.broker
def test_publish_generic_message_to_stream(broker):
    stream = "test_stream"
    message = {"foo": "bar"}

    identifier = broker.publish(stream, message)

    # Verify message identifier is always returned as string
    assert identifier is not None
    assert isinstance(identifier, str)
    assert len(identifier) > 0


@pytest.mark.broker
def test_event_message_to_stream(broker):
    person = Person.add_newcomer(
        {"id": "1", "first_name": "John", "last_name": "Doe", "age": 21}
    )
    event = person._events[0]

    identifier = broker.publish("test_stream", event.to_dict())

    # Verify message identifier is always returned as string
    assert identifier is not None
    assert isinstance(identifier, str)
    assert len(identifier) > 0


@pytest.mark.broker
def test_multiple_messages_unique_identifiers(broker):
    """Test that multiple messages get unique identifiers"""
    stream = "test_stream"
    message1 = {"foo": "bar1"}
    message2 = {"foo": "bar2"}

    identifier1 = broker.publish(stream, message1)
    identifier2 = broker.publish(stream, message2)

    # Verify both identifiers are strings and unique
    assert identifier1 is not None
    assert identifier2 is not None
    assert isinstance(identifier1, str)
    assert isinstance(identifier2, str)
    assert identifier1 != identifier2


@pytest.mark.broker
def test_message_content_unchanged_after_publishing(broker):
    """Test that the original message content is not modified during publishing"""
    stream = "test_stream"
    original_message = {"foo": "bar", "nested": {"key": "value"}}

    # Store original content for comparison
    message_copy = original_message.copy()

    identifier = broker.publish(stream, original_message)

    # Verify identifier is returned
    assert identifier is not None
    assert isinstance(identifier, str)

    # Verify original message is unchanged
    assert original_message == message_copy
    assert "_identifier" not in original_message  # Ensure no _identifier was added


@pytest.mark.broker
def test_retrieved_message_unchanged(broker):
    """Test that retrieved messages don't contain identifier modifications"""
    stream = "test_stream"
    original_message = {"foo": "bar", "data": {"count": 42}}

    broker.publish(stream, original_message)
    identifier, retrieved_message = broker.get_next(stream, "test_consumer_group")

    # Verify retrieved message matches original
    assert retrieved_message == original_message

    # Verify identifier is a UUID4 using uuid package
    assert uuid.UUID(identifier) is not None


def test_message_push_after_uow_exit(test_domain, broker):
    with UnitOfWork():
        person = Person.add_newcomer(
            {"id": "1", "first_name": "John", "last_name": "Doe", "age": 25}
        )

        test_domain.repository_for(Person).add(person)
        test_domain.publish("person_added", person._events[0].to_dict())

        assert broker.get_next("person_added", "test_consumer_group") is None

    _, message = broker.get_next("person_added", "test_consumer_group")
    assert message is not None
    assert message["id"] == "1"
    assert message["first_name"] == "John"
    assert message["last_name"] == "Doe"
    assert message["age"] == 25
    assert "_metadata" in message


@pytest.mark.broker
def test_get_next_from_empty_stream(broker):
    assert broker.get_next("person_added", "test_consumer_group") is None


@pytest.mark.broker
def test_default_publish_generates_uuid(broker):
    """Test default publish method generates UUID"""
    stream = "test_stream"
    message = {"data": "test"}

    # The publish method should generate a UUID
    identifier = broker.publish(stream, message)

    # Should be a string UUID format
    assert isinstance(identifier, str)
    assert len(identifier) == 36  # Standard UUID length with hyphens
    assert identifier.count("-") == 4  # UUID has 4 hyphens

    # Verify it's a valid UUID
    uuid.UUID(identifier)  # This will raise ValueError if invalid


@pytest.mark.broker
def test_publish_to_multiple_streams(broker):
    """Test publishing to different streams maintains separation"""
    stream1 = "stream1"
    stream2 = "stream2"
    consumer_group = "test_consumer_group"
    message1 = {"stream": 1, "data": "message1"}
    message2 = {"stream": 2, "data": "message2"}

    # Publish to different streams
    id1 = broker.publish(stream1, message1)
    id2 = broker.publish(stream2, message2)

    # Verify unique identifiers
    assert id1 != id2

    # Retrieve from stream1
    msg1 = broker.get_next(stream1, consumer_group)
    assert msg1 is not None
    assert msg1[0] == id1
    assert msg1[1] == message1

    # Retrieve from stream2
    msg2 = broker.get_next(stream2, consumer_group)
    assert msg2 is not None
    assert msg2[0] == id2
    assert msg2[1] == message2

    # Verify streams are isolated - no more messages in each stream
    assert broker.get_next(stream1, consumer_group) is None
    assert broker.get_next(stream2, consumer_group) is None


@pytest.mark.broker
def test_publish_empty_message(broker):
    """Test publishing empty message dict"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    empty_message = {}

    # Publish empty message
    identifier = broker.publish(stream, empty_message)
    assert isinstance(identifier, str)

    # Retrieve and verify
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None
    assert retrieved[0] == identifier
    assert retrieved[1] == empty_message


@pytest.mark.broker
def test_publish_complex_nested_message(broker):
    """Test publishing complex nested message structure"""
    stream = "test_stream"
    consumer_group = "test_consumer_group"
    complex_message = {
        "level1": {
            "level2": {"level3": ["item1", "item2", {"nested": True}]},
            "array": [1, 2, 3, {"key": "value"}],
        },
        "boolean": True,
        "null_value": None,
        "number": 42.5,
    }

    # Publish complex message
    identifier = broker.publish(stream, complex_message)

    # Retrieve and verify structure is preserved
    retrieved = broker.get_next(stream, consumer_group)
    assert retrieved is not None
    assert retrieved[0] == identifier
    assert retrieved[1] == complex_message
