from __future__ import annotations

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import String
from protean.fields.basic import Identifier
from protean.utils.eventing import Message


class User(BaseAggregate):
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
    test_domain.register(User, is_event_sourced=True)
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
    messages = test_domain.event_store.store.read("test::user")

    assert len(messages) == 1

    message = messages[0]
    assert isinstance(message, Message)
    assert message.metadata.headers.stream == f"test::user-{registered_user.id}"
    assert message.metadata.domain.kind == "EVENT"
    assert message.data == registered_user._events[-1].payload
    # Compare metadata fields (except envelope which now has checksum in message)
    assert (
        message.metadata.domain.fqn == registered_user._events[-1]._metadata.domain.fqn
    )
    assert (
        message.metadata.domain.kind
        == registered_user._events[-1]._metadata.domain.kind
    )
    assert (
        message.metadata.headers.stream
        == registered_user._events[-1]._metadata.headers.stream
    )
    assert message.metadata.headers == registered_user._events[-1]._metadata.headers


@pytest.mark.eventstore
def test_reading_many_messages(test_domain, activated_user):
    messages = test_domain.event_store.store.read(f"test::user-{activated_user.id}")

    assert len(messages) == 2

    assert messages[0].metadata.headers.stream == f"test::user-{activated_user.id}"
    assert messages[0].metadata.domain.kind == "EVENT"
    assert messages[0].data == activated_user._events[0].payload
    # Compare metadata fields (except envelope which now has checksum in message)
    assert (
        messages[0].metadata.domain.fqn
        == activated_user._events[0]._metadata.domain.fqn
    )
    assert (
        messages[0].metadata.domain.kind
        == activated_user._events[0]._metadata.domain.kind
    )
    assert (
        messages[0].metadata.headers.stream
        == activated_user._events[0]._metadata.headers.stream
    )
    assert messages[0].metadata.headers == activated_user._events[0]._metadata.headers
    assert messages[1].data == activated_user._events[1].payload
    assert (
        messages[1].metadata.domain.fqn
        == activated_user._events[1]._metadata.domain.fqn
    )
    assert (
        messages[1].metadata.domain.kind
        == activated_user._events[1]._metadata.domain.kind
    )
    assert (
        messages[1].metadata.headers.stream
        == activated_user._events[1]._metadata.headers.stream
    )
    assert messages[1].metadata.headers == activated_user._events[1]._metadata.headers


@pytest.mark.eventstore
def test_limiting_no_of_messages(test_domain, renamed_user):
    messages = test_domain.event_store.store.read(f"test::user-{renamed_user.id}")
    assert len(messages) == 12

    messages = test_domain.event_store.store.read(
        f"test::user-{renamed_user.id}", no_of_messages=5
    )
    assert len(messages) == 5


@pytest.mark.eventstore
def test_reading_messages_from_position(test_domain, renamed_user):
    messages = test_domain.event_store.store.read(
        f"test::user-{renamed_user.id}", position=5
    )

    assert len(messages) == 7  # Read until end, 1000 messages by default
    assert messages[0].data["name"] == "John Doe 3"


@pytest.mark.eventstore
def test_reading_messages_from_position_with_limit(test_domain, renamed_user):
    messages = test_domain.event_store.store.read(
        f"test::user-{renamed_user.id}", position=5, no_of_messages=2
    )

    assert len(messages) == 2
    assert messages[0].data["name"] == "John Doe 3"


@pytest.mark.eventstore
def test_reading_messages_by_category(test_domain, activated_user):
    messages = test_domain.event_store.store.read("test::user")

    assert len(messages) == 2

    assert messages[0].metadata.headers.stream == f"test::user-{activated_user.id}"
    assert messages[0].metadata.domain.kind == "EVENT"
    assert messages[0].data == activated_user._events[0].payload
    # Compare metadata fields (except envelope which now has checksum in message)
    assert (
        messages[0].metadata.domain.fqn
        == activated_user._events[0]._metadata.domain.fqn
    )
    assert (
        messages[0].metadata.domain.kind
        == activated_user._events[0]._metadata.domain.kind
    )
    assert (
        messages[0].metadata.headers.stream
        == activated_user._events[0]._metadata.headers.stream
    )
    assert messages[0].metadata.headers == activated_user._events[0]._metadata.headers
    assert messages[1].data == activated_user._events[1].payload
    assert (
        messages[1].metadata.domain.fqn
        == activated_user._events[1]._metadata.domain.fqn
    )
    assert (
        messages[1].metadata.domain.kind
        == activated_user._events[1]._metadata.domain.kind
    )
    assert (
        messages[1].metadata.headers.stream
        == activated_user._events[1]._metadata.headers.stream
    )
    assert messages[1].metadata.headers == activated_user._events[1]._metadata.headers


@pytest.mark.eventstore
def test_reading_last_message(test_domain, renamed_user):
    # Reading by stream
    message = test_domain.event_store.store.read_last_message(
        f"test::user-{renamed_user.id}"
    )
    assert message.metadata.headers.type == Renamed.__type__
    assert message.data["name"] == "John Doe 9"
