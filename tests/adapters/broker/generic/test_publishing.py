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
def test_publish_generic_message_to_stream(test_domain):
    stream = "test_stream"
    message = {"foo": "bar"}

    identifier = test_domain.brokers["default"].publish(stream, message)

    # Verify message identifier is always returned as string
    assert identifier is not None
    assert isinstance(identifier, str)
    assert len(identifier) > 0


@pytest.mark.broker
def test_event_message_to_stream(test_domain):
    person = Person.add_newcomer(
        {"id": "1", "first_name": "John", "last_name": "Doe", "age": 21}
    )
    event = person._events[0]

    identifier = test_domain.brokers["default"].publish("test_stream", event.to_dict())

    # Verify message identifier is always returned as string
    assert identifier is not None
    assert isinstance(identifier, str)
    assert len(identifier) > 0


@pytest.mark.broker
def test_multiple_messages_unique_identifiers(test_domain):
    """Test that multiple messages get unique identifiers"""
    stream = "test_stream"
    message1 = {"foo": "bar1"}
    message2 = {"foo": "bar2"}

    identifier1 = test_domain.brokers["default"].publish(stream, message1)
    identifier2 = test_domain.brokers["default"].publish(stream, message2)

    # Verify both identifiers are strings and unique
    assert identifier1 is not None
    assert identifier2 is not None
    assert isinstance(identifier1, str)
    assert isinstance(identifier2, str)
    assert identifier1 != identifier2


@pytest.mark.broker
def test_message_content_unchanged_after_publishing(test_domain):
    """Test that the original message content is not modified during publishing"""
    stream = "test_stream"
    original_message = {"foo": "bar", "nested": {"key": "value"}}

    # Store original content for comparison
    message_copy = original_message.copy()

    identifier = test_domain.brokers["default"].publish(stream, original_message)

    # Verify identifier is returned
    assert identifier is not None
    assert isinstance(identifier, str)

    # Verify original message is unchanged
    assert original_message == message_copy
    assert "_identifier" not in original_message  # Ensure no _identifier was added


@pytest.mark.broker
def test_retrieved_message_unchanged(test_domain):
    """Test that retrieved messages don't contain identifier modifications"""
    stream = "test_stream"
    original_message = {"foo": "bar", "data": {"count": 42}}

    test_domain.brokers["default"].publish(stream, original_message)
    identifier, retrieved_message = test_domain.brokers["default"].get_next(stream)

    # Verify retrieved message matches original
    assert retrieved_message == original_message

    # Verify identifier is a UUID4 using uuid package
    assert uuid.UUID(identifier) is not None


def test_message_push_after_uow_exit(test_domain):
    with UnitOfWork():
        person = Person.add_newcomer(
            {"id": "1", "first_name": "John", "last_name": "Doe", "age": 25}
        )

        test_domain.repository_for(Person).add(person)
        test_domain.publish("person_added", person._events[0].to_dict())

        assert test_domain.brokers["default"].get_next("person_added") is None

    _, message = test_domain.brokers["default"].get_next("person_added")
    assert message is not None
    assert message["id"] == "1"
    assert message["first_name"] == "John"
    assert message["last_name"] == "Doe"
    assert message["age"] == 25
    assert "_metadata" in message
