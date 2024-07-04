from uuid import uuid4

import pytest

from protean import BaseCommand, BaseEvent, BaseEventSourcedAggregate
from protean.core.event import Metadata
from protean.fields import String
from protean.fields.basic import Identifier
from protean.globals import g
from protean.utils.mixins import Message


class User(BaseEventSourcedAggregate):
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
    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)


@pytest.fixture
def user_id():
    return str(uuid4())


def register_command_message(user_id):
    return Message.to_message(
        Register(
            user_id=user_id,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )


def registered_event_message(user_id):
    return Message.to_message(
        Registered(
            user_id=user_id,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )


def test_origin_stream_name_in_event_from_command_without_origin_stream_name(user_id):
    g.message_in_context = register_command_message(user_id)

    event_message = Message.to_message(
        Registered(
            user_id=user_id,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )
    assert event_message.metadata.origin_stream_name is None


def test_origin_stream_name_in_event_from_command_with_origin_stream_name(user_id):
    command_message = register_command_message(user_id)

    command_message.metadata = Metadata(
        command_message.metadata.to_dict(), origin_stream_name="foo"
    )  # Metadata is a VO and immutable, so creating a copy with updated value
    g.message_in_context = command_message

    event_message = Message.to_message(
        Registered(
            user_id=user_id,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )

    assert event_message.metadata.origin_stream_name == "foo"


def test_origin_stream_name_in_aggregate_event_from_command_without_origin_stream_name(
    user_id,
):
    g.message_in_context = register_command_message(user_id)
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
    event_message = Message.to_aggregate_event_message(user, user._events[-1])

    assert event_message.metadata.origin_stream_name is None


def test_origin_stream_name_in_aggregate_event_from_command_with_origin_stream_name(
    user_id,
):
    command_message = register_command_message(user_id)

    command_message.metadata = Metadata(
        command_message.metadata.to_dict(), origin_stream_name="foo"
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
    event_message = Message.to_aggregate_event_message(user, user._events[-1])

    assert event_message.metadata.origin_stream_name == "foo"


def test_origin_stream_name_in_command_from_event(user_id):
    g.message_in_context = registered_event_message(user_id)
    command_message = Message.to_message(
        Register(
            user_id=user_id,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )

    assert command_message.metadata.origin_stream_name == f"user-{user_id}"
