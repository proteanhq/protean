from uuid import UUID, uuid4

import pytest

from protean import BaseCommand, BaseEvent, BaseEventSourcedAggregate
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String
from protean.utils.mixins import Message


class User(BaseEventSourcedAggregate):
    email = String()
    name = String()


class Register(BaseCommand):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class Activate(BaseCommand):
    id = Identifier()


class Registered(BaseEvent):
    id = Identifier(identifier=True)
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
    test_domain.init(traverse=False)


def test_construct_message_from_event(test_domain):
    identifier = str(uuid4())
    user = User(id=identifier, email="john.doe@example.com", name="John Doe")
    user.raise_(Registered(id=identifier, email="john.doe@gmail.com", name="John Doe"))

    # This simulates the call by UnitOfWork
    message = Message.to_message(user._events[-1])

    assert message is not None
    assert type(message) is Message

    # Verify Message Content
    assert message.type == Registered.__type__
    assert message.stream_name == f"{User.meta_.stream_name}-{identifier}"
    assert message.metadata.kind == "EVENT"
    assert message.data == user._events[-1].payload
    assert message.time is None
    assert message.expected_version == user._version - 1

    # Verify Message Dict
    message_dict = message.to_dict()

    assert message_dict["type"] == Registered.__type__
    assert message_dict["metadata"]["kind"] == "EVENT"
    assert message_dict["stream_name"] == f"{User.meta_.stream_name}-{identifier}"
    assert message_dict["data"] == user._events[-1].payload
    assert message_dict["time"] is None
    assert (
        message_dict["expected_version"] == user._version - 1
    )  # Expected version is always one less than current


def test_construct_message_from_command(test_domain):
    identifier = str(uuid4())
    command = Register(id=identifier, email="john.doe@gmail.com", name="John Doe")
    command_with_metadata = test_domain._enrich_command(command)
    test_domain.process(command)

    messages = test_domain.event_store.store.read("user:command")
    assert len(messages) == 1

    message = messages[0]
    assert type(message) is Message

    # Verify Message Content
    assert message.type == Register.__type__
    assert message.stream_name == f"{User.meta_.stream_name}:command-{identifier}"
    assert message.metadata.kind == "COMMAND"
    assert message.data == command_with_metadata.payload
    assert message.time is not None

    # Verify Message Dict
    message_dict = message.to_dict()
    assert message_dict["type"] == Register.__type__
    assert message_dict["metadata"]["kind"] == "COMMAND"
    assert (
        message_dict["stream_name"] == f"{User.meta_.stream_name}:command-{identifier}"
    )
    assert message_dict["data"] == command_with_metadata.payload
    assert message_dict["time"] is not None


def test_construct_message_from_command_without_identifier(test_domain):
    """Test that a new UUID is used as identifier when there is no explicit identifier specified"""
    identifier = str(uuid4())
    command = SendEmailCommand(to="john.doe@gmail.com", subject="Foo", content="Bar")
    test_domain.process(command)

    messages = test_domain.event_store.store.read("send_email:command")
    assert len(messages) == 1

    message = messages[0]
    assert type(message) is Message

    message_dict = message.to_dict()
    identifier = message_dict["stream_name"].split(
        f"{SendEmail.meta_.stream_name}:command-", 1
    )[1]

    try:
        UUID(identifier, version=4)
    except ValueError:
        pytest.fail("Command identifier is not a valid UUID")


def test_construct_message_from_either_event_or_command(test_domain):
    identifier = str(uuid4())
    command = Register(id=identifier, email="john.doe@gmail.com", name="John Doe")
    command = test_domain._enrich_command(command)

    message = Message.to_message(command)

    assert message is not None
    assert type(message) is Message

    # Verify Message Content
    assert message.type == Register.__type__
    assert message.stream_name == f"{User.meta_.stream_name}:command-{identifier}"
    assert message.metadata.kind == "COMMAND"
    assert message.data == command.payload

    user = User(id=identifier, email="john.doe@example.com", name="John Doe")
    user.raise_(Registered(id=identifier, email="john.doe@gmail.com", name="John Doe"))
    event = user._events[-1]

    # This simulates the call by UnitOfWork
    message = Message.to_message(event)

    assert message is not None
    assert type(message) is Message

    # Verify Message Content
    assert message.type == Registered.__type__
    assert message.stream_name == f"{User.meta_.stream_name}-{identifier}"
    assert message.metadata.kind == "EVENT"
    assert message.data == event.payload
    assert message.time is None


def test_object_is_registered_with_domain():
    command = Activate(id=str(uuid4()))

    with pytest.raises(ConfigurationError) as exc:
        Message.to_message(command)

    assert exc.value.args[0] == "`Activate` is not associated with an aggregate."
