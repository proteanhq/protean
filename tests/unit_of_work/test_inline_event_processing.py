from __future__ import annotations

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Boolean, Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle

counter = 0


def count_up():
    global counter
    counter += 1


class Register(BaseCommand):
    user_id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()
    name = String()
    password_hash = String()


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    email = String()
    name = String()
    password_hash = String()
    address = String()

    is_registered = Boolean()

    @classmethod
    def register(cls, command: Register) -> User:
        user = cls(
            user_id=command.user_id,
            email=command.email,
            name=command.name,
            password_hash=command.password_hash,
        )
        user.raise_(
            Registered(
                user_id=command.user_id,
                email=command.email,
                name=command.name,
                password_hash=command.password_hash,
            )
        )

        return user

    @apply
    def registered(self, _: Registered) -> None:
        self.is_registered = True


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register_user(self, command: Register) -> None:
        user = User.register(command)
        current_domain.repository_for(User).add(user)


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def registered(self, _: Registered) -> None:
        count_up()


class UserMetrics(BaseEventHandler):
    @handle(Registered)
    def count_registrations(self, _: BaseEventHandler) -> None:
        count_up()


@pytest.mark.eventstore
def test_inline_event_processing_in_sync_mode(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.register(UserMetrics, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    test_domain.process(
        Register(
            user_id=identifier,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )

    global counter
    assert counter == 2
