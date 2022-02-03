from __future__ import annotations

from uuid import uuid4

import pytest

from protean import BaseCommandHandler, BaseEvent, BaseEventSourcedAggregate, handle
from protean.core.command import BaseCommand
from protean.fields import String
from protean.fields.basic import Identifier
from protean.globals import current_domain


class Register(BaseCommand):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
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

    class Meta:
        aggregate_cls = User


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register_user(self, command: Register) -> None:
        User.register(command)


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

    events = test_domain.event_store.store._read(f"user-{identifier}")

    assert len(events) == 1
