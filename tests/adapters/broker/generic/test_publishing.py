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

    # Verify message is stored
    assert identifier is None


@pytest.mark.broker
def test_event_message_to_stream(test_domain):
    person = Person.add_newcomer(
        {"id": "1", "first_name": "John", "last_name": "Doe", "age": 21}
    )
    event = person._events[0]

    identifier = test_domain.brokers["default"].publish("test_stream", event.to_dict())

    # Verify message is stored
    assert identifier is not None
    assert identifier == event._metadata.id


def test_message_push_after_uow_exit(test_domain):
    with UnitOfWork():
        person = Person.add_newcomer(
            {"id": "1", "first_name": "John", "last_name": "Doe", "age": 25}
        )

        test_domain.repository_for(Person).add(person)
        test_domain.publish("person_added", person._events[0].to_dict())

        assert test_domain.brokers["default"].get_next("person_added") is None

    message = test_domain.brokers["default"].get_next("person_added")
    assert message is not None
    assert message["id"] == "1"
    assert message["first_name"] == "John"
    assert message["last_name"] == "Doe"
    assert message["age"] == 25
    assert "_metadata" in message
