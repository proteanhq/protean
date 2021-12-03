from __future__ import annotations

from uuid import uuid4

import mock

from protean import BaseCommandHandler, BaseEvent, BaseEventSourcedAggregate, handle
from protean.core.command import BaseCommand
from protean.fields import Identifier, String
from protean.globals import current_domain


class Register(BaseCommand):
    id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class Registered(BaseEvent):
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


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register_user(self, command: Register) -> None:
        User.register(command)


@mock.patch("protean.core.unit_of_work.UnitOfWork._store_events")
def test_that_events_can_be_raised_from_within_aggregates(mock_uow_store_events):
    identifier = str(uuid4())
    UserCommandHandler().register_user(
        Register(
            id=identifier,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )

    mock_uow_store_events.assert_called_with(
        User(
            id=identifier,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )
