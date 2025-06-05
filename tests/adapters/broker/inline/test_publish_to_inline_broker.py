import pytest

from ..elements import Person, PersonAdded


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonAdded, part_of=Person)
    test_domain.init(traverse=False)


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
