from datetime import datetime, timezone
from uuid import uuid4

import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.command import _LegacyBaseCommand as BaseCommand
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.exceptions import InvalidDataError, DeserializationError
from protean.fields import Identifier, String
from protean.utils.eventing import Message, Metadata, DomainMeta, MessageHeaders


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
    message = Message.from_domain_object(user._events[-1])

    reconstructed_event = message.to_domain_object()
    assert isinstance(reconstructed_event, Registered)
    assert reconstructed_event.id == identifier


def test_construct_command_from_message(test_domain):
    identifier = str(uuid4())
    command = test_domain._enrich_command(
        Register(id=identifier, email="john.doe@gmail.com", name="John Doe"), True
    )
    message = Message.from_domain_object(command)

    reconstructed_command = message.to_domain_object()
    assert isinstance(reconstructed_command, Register)
    assert reconstructed_command.id == identifier


def test_invalid_message_throws_exception():
    message = Message(
        data={},
        metadata=Metadata(
            headers=MessageHeaders(
                id=str(uuid4()),
                type="test.Invalid",
                time=datetime.now(timezone.utc),
            ),
            domain=DomainMeta(kind="INVALID"),
        ),
    )

    with pytest.raises(DeserializationError) as exc:
        message.to_domain_object()

    # Check that it's the right exception with enhanced context
    error = exc.value
    assert "Message type is not supported for deserialization" in error.error

    # Check that the original InvalidDataError is preserved in the exception chain
    assert isinstance(error.__cause__, InvalidDataError)
    assert error.__cause__.messages == {
        "kind": ["Message type is not supported for deserialization"]
    }
