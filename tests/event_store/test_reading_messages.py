from __future__ import annotations

from uuid import uuid4

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields import String
from protean.fields.basic import Identifier
from protean.utils.mixins import Message


class Registered(BaseEvent):
    id = Identifier()
    email = String()


class Activated(BaseEvent):
    id = Identifier(required=True)


class Renamed(BaseEvent):
    id = Identifier(required=True)
    name = String(required=True, max_length=50)


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()
    name = String(max_length=50)


def test_reading_a_message(test_domain):
    identifier = str(uuid4())
    event = Registered(id=identifier, email="john.doe@example.com")
    user = User(id=identifier, email="john.doe@example.com")
    test_domain.event_store.store.append_aggregate_event(user, event)

    messages = test_domain.event_store.store.read("user")

    assert len(messages) == 1

    message = messages[0]
    assert isinstance(message, Message)
    assert message.stream_name == f"user-{identifier}"
    assert message.metadata.kind == "EVENT"
    assert message.data == event.to_dict()


def test_reading_many_messages(test_domain):
    identifier = str(uuid4())
    event1 = Registered(id=identifier, email="john.doe@example.com")
    user = User(**event1.to_dict())
    test_domain.event_store.store.append_aggregate_event(user, event1)

    event2 = Activated(id=identifier)
    test_domain.event_store.store.append_aggregate_event(user, event2)

    messages = test_domain.event_store.store.read(f"user-{identifier}")

    assert len(messages) == 2

    assert messages[0].stream_name == f"user-{identifier}"
    assert messages[0].metadata.kind == "EVENT"
    assert messages[0].data == event1.to_dict()
    assert messages[1].data == event2.to_dict()


def test_limiting_no_of_messages(test_domain):
    identifier = str(uuid4())
    event1 = Registered(id=identifier, email="john.doe@example.com")
    user = User(**event1.to_dict())
    test_domain.event_store.store.append_aggregate_event(user, event1)

    event2 = Activated(id=identifier)
    test_domain.event_store.store.append_aggregate_event(user, event2)

    for i in range(10):
        event = Renamed(id=identifier, name=f"John Doe {i}")
        test_domain.event_store.store.append_aggregate_event(user, event)

    messages = test_domain.event_store.store.read(f"user-{identifier}")
    assert len(messages) == 12

    messages = test_domain.event_store.store.read(
        f"user-{identifier}", no_of_messages=5
    )
    assert len(messages) == 5


def test_reading_messages_from_position(test_domain):
    identifier = str(uuid4())
    event1 = Registered(id=identifier, email="john.doe@example.com")
    user = User(**event1.to_dict())
    test_domain.event_store.store.append_aggregate_event(user, event1)

    event2 = Activated(id=identifier)
    test_domain.event_store.store.append_aggregate_event(user, event2)

    for i in range(2, 12):  # Account for 2 previous events
        event = Renamed(id=identifier, name=f"John Doe {i}")
        test_domain.event_store.store.append_aggregate_event(user, event)

    messages = test_domain.event_store.store.read(f"user-{identifier}")

    messages = test_domain.event_store.store.read(f"user-{identifier}", position=5)
    assert messages[0].data["name"] == "John Doe 5"


def test_reading_messages_by_category(test_domain):
    identifier = str(uuid4())
    event1 = Registered(id=identifier, email="john.doe@example.com")
    user = User(**event1.to_dict())
    test_domain.event_store.store.append_aggregate_event(user, event1)

    event2 = Activated(id=identifier)
    test_domain.event_store.store.append_aggregate_event(user, event2)

    messages = test_domain.event_store.store.read("user")

    assert len(messages) == 2

    assert messages[0].stream_name == f"user-{identifier}"
    assert messages[0].metadata.kind == "EVENT"
    assert messages[0].data == event1.to_dict()
    assert messages[1].data == event2.to_dict()
