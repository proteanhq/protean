import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import DateTime, Identifier, String
from protean.utils.eventing import Message

from tests.event.elements import Person, PersonAdded


class PersonWithDates(BaseAggregate):
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    registered_at: DateTime()


class PersonRegisteredWithDate(BaseEvent):
    id: Identifier(required=True)
    first_name: String(max_length=50, required=True)
    last_name: String(max_length=50, required=True)
    registered_at: DateTime()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonAdded, part_of=Person)
    test_domain.register(PersonWithDates)
    test_domain.register(PersonRegisteredWithDate, part_of=PersonWithDates)
    test_domain.init(traverse=False)


def test_that_message_has_unique_identifier():
    event = PersonAdded(id=str(uuid4()), first_name="John", last_name="Doe")

    assert hasattr(event, "id")
    try:
        UUID(str(event.id))
    except ValueError:
        pytest.fail("Event ID is not valid UUID")


def test_that_event_messages_have_the_right_type():
    event = PersonAdded(id=str(uuid4()), first_name="John", last_name="Doe")

    assert hasattr(PersonAdded, "__type__")
    assert PersonAdded.__type__ == "Test.PersonAdded.v1"

    # The type should also be reflected in the event's metadata after enrichment
    assert event._metadata.headers.type == "Test.PersonAdded.v1"


def test_event_payload_construction():
    person_id = str(uuid4())
    event = PersonAdded(id=person_id, first_name="John", last_name="Doe", age=35)

    payload = event.payload
    assert payload == {
        "id": person_id,
        "first_name": "John",
        "last_name": "Doe",
        "age": 35,
    }

    # Payload should not contain metadata
    assert "_metadata" not in payload


def test_stringified_message():
    person_id = str(uuid4())
    event = PersonAdded(id=person_id, first_name="John", last_name="Doe", age=42)

    event_dict = event.to_dict()

    # to_dict() should include both payload and metadata
    assert "first_name" in event_dict
    assert "last_name" in event_dict
    assert "age" in event_dict
    assert "_metadata" in event_dict

    # The dict should be JSON-serializable
    json_str = json.dumps(event_dict, default=str)
    parsed = json.loads(json_str)

    assert parsed["first_name"] == "John"
    assert parsed["last_name"] == "Doe"
    assert parsed["age"] == 42
    assert parsed["_metadata"]["headers"]["type"] == "Test.PersonAdded.v1"


def test_reconstruction_of_event_from_message():
    person_id = str(uuid4())
    original = PersonAdded(id=person_id, first_name="John", last_name="Doe", age=30)

    # Serialize to Message and back
    message = Message.from_domain_object(original)
    reconstructed = message.to_domain_object()

    assert isinstance(reconstructed, PersonAdded)
    assert reconstructed.id == person_id
    assert reconstructed.first_name == "John"
    assert reconstructed.last_name == "Doe"
    assert reconstructed.age == 30


def test_that_dates_in_message_are_serialized_and_deserialized():
    person_id = str(uuid4())
    now = datetime.now(timezone.utc)

    event = PersonRegisteredWithDate(
        id=person_id,
        first_name="John",
        last_name="Doe",
        registered_at=now,
    )

    # DateTime should serialize to string in payload
    payload = event.payload
    assert payload["registered_at"] == str(now)

    # Full dict should be JSON-serializable
    event_dict = event.to_dict()
    json_str = json.dumps(event_dict, default=str)
    parsed = json.loads(json_str)
    assert parsed["registered_at"] == str(now)

    # Round-trip through Message should preserve the datetime
    message = Message.from_domain_object(event)
    reconstructed = message.to_domain_object()

    assert isinstance(reconstructed, PersonRegisteredWithDate)
    assert reconstructed.registered_at == now
