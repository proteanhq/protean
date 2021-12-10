from uuid import UUID, uuid4

import pytest

from protean import BaseCommand, BaseEvent, BaseEventSourcedAggregate
from protean.fields import Identifier, String
from protean.utils import fully_qualified_name
from protean.utils.mixins import Message


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()
    name = String()


class Register(BaseCommand):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()


class SendEmail(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    to = String()
    subject = String()
    content = String()


class SendEmailCommand(BaseCommand):
    to = String()
    subject = String()
    content = String()


def test_construct_message_from_event(test_domain):
    identifier = str(uuid4())
    event = Registered(id=identifier, email="john.doe@gmail.com", name="John Doe")
    user = User(**event.to_dict())

    # This simulates the call by UnitOfWork
    message = Message.to_event_message(user, event)

    assert message is not None
    assert type(message) is Message

    message_dict = message.to_dict()

    assert message_dict["type"] == fully_qualified_name(Registered)
    assert message_dict["kind"] == "EVENT"
    assert message_dict["owner"] == test_domain.domain_name
    assert message_dict["stream_name"] == f"{User.meta_.stream_name}-{identifier}"
    assert message_dict["data"] == event.to_dict()
    assert message_dict["time"] is None


def test_construct_message_from_command(test_domain):
    identifier = str(uuid4())
    command = Register(id=identifier, email="john.doe@gmail.com", name="John Doe")

    message = Message.to_command_message(User, command)

    assert message is not None
    assert type(message) is Message

    message_dict = message.to_dict()

    assert message_dict["type"] == fully_qualified_name(Register)
    assert message_dict["kind"] == "COMMAND"
    assert message_dict["owner"] == test_domain.domain_name
    assert (
        message_dict["stream_name"] == f"{User.meta_.stream_name}:command-{identifier}"
    )
    assert message_dict["data"] == command.to_dict()
    assert message_dict["time"] is None


def test_construct_message_from_command_without_identifier(test_domain):
    """Test that a new UUID is used as identifier when there is no explicit identifier specified"""
    identifier = str(uuid4())
    command = SendEmailCommand(to="john.doe@gmail.com", subject="Foo", content="Bar")

    message = Message.to_command_message(SendEmail, command)

    assert message is not None
    assert type(message) is Message

    message_dict = message.to_dict()
    identifier = message_dict["stream_name"].split(
        f"{SendEmail.meta_.stream_name}:command-", 1
    )[1]

    try:
        UUID(identifier, version=4)
    except ValueError:
        pytest.fail("Command identifier is not a valid UUID")
