from uuid import uuid4

import pytest

from protean import BaseCommand, BaseEvent, BaseEventSourcedAggregate
from protean.fields import Identifier, String
from protean.utils.mixins import Message


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    email = String()
    name = String()


class Register(BaseCommand):
    id = Identifier(identifier=True)
    email = String()
    name = String()

    class Meta:
        aggregate_cls = User


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()

    class Meta:
        aggregate_cls = User


class SendEmail(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
    to = String()
    subject = String()
    content = String()


class SendEmailCommand(BaseCommand):
    to = String()
    subject = String()
    content = String()

    class Meta:
        aggregate_cls = SendEmail


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User)
    test_domain.register(Register)
    test_domain.register(Registered)
    test_domain.register(SendEmail)
    test_domain.register(SendEmailCommand)


def test_construct_event_from_message(test_domain):
    identifier = str(uuid4())
    event = Registered(id=identifier, email="john.doe@gmail.com", name="John Doe")
    user = User(**event.to_dict())
    message = Message.to_aggregate_event_message(user, event)

    reconstructed_event = message.to_object()
    assert isinstance(reconstructed_event, Registered)
    assert reconstructed_event.id == identifier


def test_construct_command_from_message(test_domain):
    identifier = str(uuid4())
    command = Register(id=identifier, email="john.doe@gmail.com", name="John Doe")
    message = Message.to_command_message(command)

    reconstructed_command = message.to_object()
    assert isinstance(reconstructed_command, Register)
    assert reconstructed_command.id == identifier
