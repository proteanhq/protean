from uuid import uuid4

import pytest

from protean import BaseCommand, BaseEvent, BaseEventSourcedAggregate
from protean.fields import Identifier, String
from protean.utils.mixins import Message


class User(BaseEventSourcedAggregate):
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
    to = String()
    subject = String()
    content = String()


class SendEmailCommand(BaseCommand):
    to = String()
    subject = String()
    content = String()


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(SendEmail)
    test_domain.register(SendEmailCommand, part_of=SendEmail)


def test_construct_event_from_message():
    identifier = str(uuid4())
    user = User(id=identifier, email="john.doe@gmail.com", name="John Doe")
    user.raise_(Registered(id=identifier, email="john.doe@gmail.com", name="John Doe"))
    message = Message.to_aggregate_event_message(user, user._events[-1])

    reconstructed_event = message.to_object()
    assert isinstance(reconstructed_event, Registered)
    assert reconstructed_event.id == identifier


def test_construct_command_from_message():
    identifier = str(uuid4())
    command = Register(id=identifier, email="john.doe@gmail.com", name="John Doe")
    message = Message.to_message(command)

    reconstructed_command = message.to_object()
    assert isinstance(reconstructed_command, Register)
    assert reconstructed_command.id == identifier
