from uuid import uuid4

import pytest

from protean import BaseAggregate, BaseCommand, BaseEvent
from protean.core.event import Metadata
from protean.fields import String
from protean.fields.basic import Identifier
from protean.globals import g
from protean.utils.mixins import Message


class User(BaseAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class Register(BaseCommand):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()


class Registered(BaseEvent):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture
def user_id():
    return str(uuid4())


@pytest.fixture
def register_command_message(user_id, test_domain):
    enriched_command = test_domain._enrich_command(
        Register(
            user_id=user_id,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )
    return Message.to_message(enriched_command)


@pytest.fixture
def registered_event_message(user_id):
    user = User(id=user_id, email="john.doe@gmail.com", name="John Doe")
    user.raise_(
        Registered(
            user_id=user_id,
            email=user.email,
            name=user.name,
        )
    )
    return Message.to_message(user._events[0])


def test_origin_stream_in_event_from_command_without_origin_stream(
    user_id, register_command_message
):
    g.message_in_context = register_command_message

    user = User(id=user_id, email="john.doe@gmail.com", name="John Doe")
    user.raise_(
        Registered(
            user_id=user_id,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )
    event_message = Message.to_message(user._events[-1])
    assert event_message.metadata.origin_stream is None


def test_origin_stream_in_event_from_command_with_origin_stream(
    user_id, register_command_message
):
    command_message = register_command_message

    command_message.metadata = Metadata(
        command_message.metadata.to_dict(), origin_stream="foo"
    )  # Metadata is a VO and immutable, so creating a copy with updated value
    g.message_in_context = command_message

    user = User(id=user_id, email="john.doe@gmail.com", name="John Doe")
    user.raise_(
        Registered(
            user_id=user_id,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )
    event_message = Message.to_message(user._events[-1])

    assert event_message.metadata.origin_stream == "foo"


def test_origin_stream_in_aggregate_event_from_command_without_origin_stream(
    user_id, register_command_message
):
    g.message_in_context = register_command_message
    user = User(
        id=user_id,
        email="john.doe@gmail.com",
        name="John Doe",
    )
    user.raise_(
        Registered(
            user_id=user_id,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )
    event_message = Message.to_message(user._events[-1])

    assert event_message.metadata.origin_stream is None


def test_origin_stream_in_aggregate_event_from_command_with_origin_stream(
    user_id, register_command_message
):
    command_message = register_command_message

    command_message.metadata = Metadata(
        command_message.metadata.to_dict(), origin_stream="foo"
    )  # Metadata is a VO and immutable, so creating a copy with updated value
    g.message_in_context = command_message

    user = User(
        id=user_id,
        email="john.doe@gmail.com",
        name="John Doe",
    )
    user.raise_(
        Registered(
            user_id=user_id,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )
    event_message = Message.to_message(user._events[-1])

    assert event_message.metadata.origin_stream == "foo"


def test_origin_stream_in_command_from_event(
    user_id, test_domain, registered_event_message
):
    g.message_in_context = registered_event_message
    command = Register(
        user_id=user_id,
        email="john.doe@gmail.com",
        name="John Doe",
    )

    enriched_command = test_domain._enrich_command(command)
    command_message = Message.to_message(enriched_command)

    assert command_message.metadata.origin_stream == f"test::user-{user_id}"
