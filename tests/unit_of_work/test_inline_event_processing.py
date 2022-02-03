from __future__ import annotations

from uuid import uuid4

import pytest

from protean import (
    BaseCommand,
    BaseCommandHandler,
    BaseEvent,
    BaseEventHandler,
    BaseEventSourcedAggregate,
    apply,
    handle,
)
from protean.fields import Boolean, Identifier, String
from protean.globals import current_domain

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


class User(BaseEventSourcedAggregate):
    user_id = Identifier(identifier=True)  # FIXME Auto-attach ID attribute
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

    @apply(Registered)
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

    class Meta:
        aggregate_cls = User


@pytest.mark.eventstore
def test_inline_event_processing_in_sync_mode(test_domain):
    test_domain.register(User)
    test_domain.register(Registered)
    test_domain.register(UserEventHandler, aggregate_cls=User)
    test_domain.register(UserMetrics)

    identifier = str(uuid4())
    UserCommandHandler().register_user(
        Register(
            user_id=identifier,
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )

    global counter
    assert counter == 2
