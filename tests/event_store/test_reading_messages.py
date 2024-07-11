from __future__ import annotations

from uuid import uuid4

import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields import String
from protean.fields.basic import Identifier
from protean.utils.mixins import Message


class User(BaseEventSourcedAggregate):
    email = String()
    name = String(max_length=50)


class Registered(BaseEvent):
    id = Identifier()
    email = String()


class Activated(BaseEvent):
    id = Identifier(required=True)


class Renamed(BaseEvent):
    id = Identifier(required=True)
    name = String(required=True, max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.register(Renamed, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture
def registered_user(test_domain):
    identifier = str(uuid4())
    user = User(id=identifier, email="john.doe@example.com")
    user.raise_(Registered(id=identifier, email="john.doe@example.com"))
    test_domain.event_store.store.append(user._events[-1])

    return user


@pytest.fixture
def activated_user(test_domain, registered_user):
    registered_user.raise_(Activated(id=registered_user.id))
    test_domain.event_store.store.append(registered_user._events[-1])

    return registered_user


@pytest.fixture
def renamed_user(test_domain, activated_user):
    for i in range(10):
        activated_user.raise_(Renamed(id=activated_user.id, name=f"John Doe {i}"))
        test_domain.event_store.store.append(activated_user._events[-1])

    return activated_user


@pytest.mark.eventstore
def test_reading_a_message(test_domain, registered_user):
    messages = test_domain.event_store.store.read("user")

    assert len(messages) == 1

    message = messages[0]
    assert isinstance(message, Message)
    assert message.stream_name == f"user-{registered_user.id}"
    assert message.metadata.kind == "EVENT"
    assert message.data == registered_user._events[-1].to_dict()


@pytest.mark.eventstore
def test_reading_many_messages(test_domain, activated_user):
    messages = test_domain.event_store.store.read(f"user-{activated_user.id}")

    assert len(messages) == 2

    assert messages[0].stream_name == f"user-{activated_user.id}"
    assert messages[0].metadata.kind == "EVENT"
    assert messages[0].data == activated_user._events[0].to_dict()
    assert messages[1].data == activated_user._events[1].to_dict()


@pytest.mark.eventstore
def test_limiting_no_of_messages(test_domain, renamed_user):
    messages = test_domain.event_store.store.read(f"user-{renamed_user.id}")
    assert len(messages) == 12

    messages = test_domain.event_store.store.read(
        f"user-{renamed_user.id}", no_of_messages=5
    )
    assert len(messages) == 5


@pytest.mark.eventstore
def test_reading_messages_from_position(test_domain, renamed_user):
    messages = test_domain.event_store.store.read(f"user-{renamed_user.id}", position=5)

    assert len(messages) == 7  # Read until end, 1000 messages by default
    assert messages[0].data["name"] == "John Doe 3"


@pytest.mark.eventstore
def test_reading_messages_from_position_with_limit(test_domain, renamed_user):
    messages = test_domain.event_store.store.read(
        f"user-{renamed_user.id}", position=5, no_of_messages=2
    )

    assert len(messages) == 2
    assert messages[0].data["name"] == "John Doe 3"


@pytest.mark.eventstore
def test_reading_messages_by_category(test_domain, activated_user):
    messages = test_domain.event_store.store.read("user")

    assert len(messages) == 2

    assert messages[0].stream_name == f"user-{activated_user.id}"
    assert messages[0].metadata.kind == "EVENT"
    assert messages[0].data == activated_user._events[0].to_dict()
    assert messages[1].data == activated_user._events[1].to_dict()


@pytest.mark.eventstore
def test_reading_last_message(test_domain, renamed_user):
    # Reading by stream
    message = test_domain.event_store.store.read_last_message(f"user-{renamed_user.id}")
    assert message.type == Renamed.__type__
    assert message.data["name"] == "John Doe 9"
