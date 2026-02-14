from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent

from protean.utils.globals import g
from protean.utils.eventing import DomainMeta, Message, Metadata
from pydantic import Field


class User(BaseAggregate):
    id: str | None = Field(default=None, json_schema_extra={"identifier": True})
    email: str | None = None
    name: str | None = None


class Register(BaseCommand):
    user_id: str | None = Field(default=None, json_schema_extra={"identifier": True})
    email: str | None = None
    name: str | None = None


class Registered(BaseEvent):
    user_id: str | None = Field(default=None, json_schema_extra={"identifier": True})
    email: str | None = None
    name: str | None = None


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
        ),
        True,
    )
    return Message.from_domain_object(enriched_command)


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
    return Message.from_domain_object(user._events[0])


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
    event_message = Message.from_domain_object(user._events[-1])
    assert event_message.metadata.domain.origin_stream is None


def test_origin_stream_in_event_from_command_with_origin_stream(
    user_id, register_command_message
):
    command_message = register_command_message

    # Create a new Metadata with updated origin_stream in domain metadata

    command_message.metadata = Metadata(
        headers=command_message.metadata.headers,
        envelope=command_message.metadata.envelope,
        domain=DomainMeta(
            fqn=command_message.metadata.domain.fqn,
            kind=command_message.metadata.domain.kind,
            origin_stream="foo",
            version=command_message.metadata.domain.version,
            sequence_id=command_message.metadata.domain.sequence_id,
            asynchronous=command_message.metadata.domain.asynchronous,
        ),
    )
    g.message_in_context = command_message

    user = User(id=user_id, email="john.doe@gmail.com", name="John Doe")
    user.raise_(
        Registered(
            user_id=user_id,
            email="john.doe@gmail.com",
            name="John Doe",
        )
    )
    event_message = Message.from_domain_object(user._events[-1])

    assert event_message.metadata.domain.origin_stream == "foo"


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
    event_message = Message.from_domain_object(user._events[-1])

    assert event_message.metadata.domain.origin_stream is None


def test_origin_stream_in_aggregate_event_from_command_with_origin_stream(
    user_id, register_command_message
):
    command_message = register_command_message

    # Create a new Metadata with updated origin_stream in domain metadata

    command_message.metadata = Metadata(
        headers=command_message.metadata.headers,
        envelope=command_message.metadata.envelope,
        domain=DomainMeta(
            fqn=command_message.metadata.domain.fqn,
            kind=command_message.metadata.domain.kind,
            origin_stream="foo",
            version=command_message.metadata.domain.version,
            sequence_id=command_message.metadata.domain.sequence_id,
            asynchronous=command_message.metadata.domain.asynchronous,
        ),
    )
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
    event_message = Message.from_domain_object(user._events[-1])

    assert event_message.metadata.domain.origin_stream == "foo"


def test_origin_stream_in_command_from_event(
    user_id, test_domain, registered_event_message
):
    g.message_in_context = registered_event_message
    command = Register(
        user_id=user_id,
        email="john.doe@gmail.com",
        name="John Doe",
    )

    enriched_command = test_domain._enrich_command(command, True)
    command_message = Message.from_domain_object(enriched_command)

    assert command_message.metadata.domain.origin_stream == f"test::user-{user_id}"
