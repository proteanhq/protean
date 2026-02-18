from uuid import UUID, uuid4

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String
from protean.utils.eventing import Message


class Register(BaseCommand):
    id: Identifier(identifier=True)
    email: String()
    name: String()


class Activate(BaseCommand):
    id: Identifier()


class Registered(BaseEvent):
    id: Identifier(identifier=True)
    email: String()
    name: String()


class User(BaseAggregate):
    email: String()
    name: String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.email = event.email
        self.name = event.name


class SendEmail(BaseAggregate):
    to: String()
    subject: String()
    content: String()


class SendEmailCommand(BaseCommand):
    to: String()
    subject: String()
    content: String()


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(SendEmail, is_event_sourced=True)
    test_domain.register(SendEmailCommand, part_of=SendEmail)
    test_domain.init(traverse=False)


def test_construct_message_from_event():
    identifier = str(uuid4())
    user = User(id=identifier, email="john.doe@example.com", name="John Doe")
    user.raise_(Registered(id=identifier, email="john.doe@gmail.com", name="John Doe"))

    # This simulates the call by UnitOfWork
    message = Message.from_domain_object(user._events[-1])

    assert message is not None
    assert type(message) is Message

    # Verify Message Content
    assert message.metadata.headers.type == Registered.__type__
    assert (
        message.metadata.headers.stream == f"{User.meta_.stream_category}-{identifier}"
    )
    assert message.metadata.domain.kind == "EVENT"
    assert message.data == user._events[-1].payload
    assert (
        message.metadata.headers.time is not None
    )  # Events now have time set automatically
    assert message.metadata.domain.expected_version == user._version - 1

    # Verify Message Dict
    message_dict = message.to_dict()

    assert message_dict["metadata"]["headers"]["type"] == Registered.__type__
    assert message_dict["metadata"]["domain"]["kind"] == "EVENT"
    assert (
        message_dict["metadata"]["headers"]["stream"]
        == f"{User.meta_.stream_category}-{identifier}"
    )
    assert message_dict["data"] == user._events[-1].payload
    assert (
        message_dict["metadata"]["headers"]["time"] is not None
    )  # Events now have time set automatically
    assert (
        message_dict["metadata"]["domain"]["expected_version"] == user._version - 1
    )  # Expected version is always one less than current


def test_construct_message_from_command(test_domain):
    identifier = str(uuid4())
    command = Register(id=identifier, email="john.doe@gmail.com", name="John Doe")
    command_with_metadata = test_domain._enrich_command(command, True)
    test_domain.process(command)

    messages = test_domain.event_store.store.read("user:command")
    assert len(messages) == 1

    message = messages[0]
    assert type(message) is Message

    # Verify Message Content
    assert message.metadata.headers.type == Register.__type__
    assert (
        message.metadata.headers.stream
        == f"{User.meta_.stream_category}:command-{identifier}"
    )
    assert message.metadata.domain.kind == "COMMAND"
    assert message.data == command_with_metadata.payload
    assert message.metadata.headers.time is not None

    # Verify Message Dict
    message_dict = message.to_dict()
    assert message_dict["metadata"]["headers"]["type"] == Register.__type__
    assert message_dict["metadata"]["domain"]["kind"] == "COMMAND"
    assert (
        message_dict["metadata"]["headers"]["stream"]
        == f"{User.meta_.stream_category}:command-{identifier}"
    )
    assert message_dict["data"] == command_with_metadata.payload
    assert message_dict["metadata"]["headers"]["time"] is not None


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
    identifier = message_dict["metadata"]["headers"]["stream"].split(
        f"{SendEmail.meta_.stream_category}:command-", 1
    )[1]

    try:
        UUID(identifier, version=4)
    except ValueError:
        pytest.fail("Command identifier is not a valid UUID")


def test_construct_message_from_either_event_or_command(test_domain):
    identifier = str(uuid4())
    command = Register(id=identifier, email="john.doe@gmail.com", name="John Doe")
    command = test_domain._enrich_command(command, True)

    message = Message.from_domain_object(command)

    assert message is not None
    assert type(message) is Message

    # Verify Message Content
    assert message.metadata.headers.type == Register.__type__
    assert (
        message.metadata.headers.stream
        == f"{User.meta_.stream_category}:command-{identifier}"
    )
    assert message.metadata.domain.kind == "COMMAND"
    assert message.data == command.payload

    user = User(id=identifier, email="john.doe@example.com", name="John Doe")
    user.raise_(Registered(id=identifier, email="john.doe@gmail.com", name="John Doe"))
    event = user._events[-1]

    # This simulates the call by UnitOfWork
    message = Message.from_domain_object(event)

    assert message is not None
    assert type(message) is Message

    # Verify Message Content
    assert message.metadata.headers.type == Registered.__type__
    assert (
        message.metadata.headers.stream == f"{User.meta_.stream_category}-{identifier}"
    )
    assert message.metadata.domain.kind == "EVENT"
    assert message.data == event.payload
    assert (
        message.metadata.headers.time is not None
    )  # Events now have time set automatically


def test_object_is_registered_with_domain():
    with pytest.raises(ConfigurationError) as exc:
        Message.from_domain_object(Activate(id=str(uuid4())))

    assert exc.value.args[0] == "`Activate` should be registered with a domain"
