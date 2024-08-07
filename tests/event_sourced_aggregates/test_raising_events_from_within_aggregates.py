from __future__ import annotations

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.fields import Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


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


class User(BaseAggregate):
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
    test_domain.register(User, is_event_sourced=True)
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

    messages = test_domain.event_store.store._read("test::user")

    assert len(messages) == 1
    assert messages[0]["stream_name"] == f"test::user-{identifier}"
    assert messages[0]["type"] == Registered.__type__

    messages = test_domain.event_store.store._read("test::user:command")

    assert len(messages) == 1
    assert messages[0]["stream_name"] == f"test::user:command-{identifier}"
    assert messages[0]["type"] == Register.__type__
