from __future__ import annotations

from uuid import uuid4

import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.command import _LegacyBaseCommand as BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.fields import String
from protean.fields.basic import Identifier
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


class Register(BaseCommand):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()

    @classmethod
    def register(cls, command: Registered) -> User:
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


class Registered(BaseEvent):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register_user(self, command: Register) -> None:
        User.register(command)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Register, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.init(traverse=False)


@pytest.mark.eventstore
def test_persisting_events_on_commit(test_domain):
    identifier = str(uuid4())
    UserCommandHandler().register_user(
        Register(
            id=identifier,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )

    events = test_domain.event_store.store._read(f"test::user-{identifier}")

    assert len(events) == 1
