from __future__ import annotations

from uuid import uuid4

import pytest

from protean import BaseCommandHandler, BaseEvent, BaseEventSourcedAggregate, handle
from protean.core.command import BaseCommand
from protean.core.event_sourced_aggregate import apply
from protean.fields import Identifier, String
from protean.globals import current_domain


class Register(BaseCommand):
    id = Identifier(identifier=True)
    email = String()
    name = String()
    password_hash = String()


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class User(BaseEventSourcedAggregate):
    email = String()
    name = String()
    password_hash = String()

    @classmethod
    def register(cls, command: Register) -> User:
        user = cls(
            id=command.id,
            email=command.email,
            name=command.name,
            password_hash=command.password_hash,
        )
        user.raise_(
            Registered(
                id=command.id,
                email=command.email,
                name=command.name,
                password_hash=command.password_hash,
            )
        )

        current_domain.repository_for(User).add(user)

        return user

    @apply
    def registered(self, _: Registered) -> None:
        pass


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register_user(self, command: Register) -> None:
        User.register(command)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.init(traverse=False)


@pytest.mark.eventstore
def test_that_events_can_be_raised_from_within_aggregates(test_domain):
    identifier = str(uuid4())
    test_domain.process(
        Register(
            id=identifier,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )

    messages = test_domain.event_store.store._read("user")

    assert len(messages) == 1
    assert messages[0]["stream_name"] == f"user-{identifier}"
    assert messages[0]["type"] == Registered.__type__

    messages = test_domain.event_store.store._read("user:command")

    assert len(messages) == 1
    assert messages[0]["stream_name"] == f"user:command-{identifier}"
    assert messages[0]["type"] == Register.__type__
