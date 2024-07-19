from uuid import uuid4

import pytest

from protean import BaseAggregate, BaseCommand, BaseEvent
from protean.core.event import Metadata
from protean.exceptions import InvalidDataError
from protean.fields import Identifier, String
from protean.utils.mixins import Message


class User(BaseAggregate):
    email = String()
    name = String()


class Register(BaseCommand):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class Activate(BaseCommand):
    id = Identifier()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()


class SendEmail(BaseAggregate):
    to = String()
    subject = String()
    content = String()


class SendEmailCommand(BaseCommand):
    to = String()
    subject = String()
    content = String()


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(SendEmail, is_event_sourced=True)
    test_domain.register(SendEmailCommand, part_of=SendEmail)
    test_domain.init(traverse=False)


def test_construct_event_from_message():
    identifier = str(uuid4())
    user = User(id=identifier, email="john.doe@gmail.com", name="John Doe")
    user.raise_(Registered(id=identifier, email="john.doe@gmail.com", name="John Doe"))
    message = Message.to_message(user._events[-1])

    reconstructed_event = message.to_object()
    assert isinstance(reconstructed_event, Registered)
    assert reconstructed_event.id == identifier


def test_construct_command_from_message(test_domain):
    identifier = str(uuid4())
    command = test_domain._enrich_command(
        Register(id=identifier, email="john.doe@gmail.com", name="John Doe")
    )
    message = Message.to_message(command)

    reconstructed_command = message.to_object()
    assert isinstance(reconstructed_command, Register)
    assert reconstructed_command.id == identifier


def test_invalid_message_throws_exception():
    message = Message(metadata=Metadata(kind="INVALID"))

    with pytest.raises(InvalidDataError) as exc:
        message.to_object()

    assert exc.value.messages == {
        "_message": ["Message type is not supported for deserialization"]
    }
