from __future__ import annotations

from protean import BaseEventSourcedAggregate, BaseEvent, BaseCommandHandler, handle
from protean.core.command import BaseCommand
from protean.fields import String


class Register(BaseCommand):
    email = String()
    name = String()
    password_hash = String()


class Registered(BaseEvent):
    email = String()
    name = String()
    password_hash = String()


class User(BaseEventSourcedAggregate):
    email = String()
    name = String()
    password_hash = String()

    @classmethod
    def register(cls, command: Registered) -> User:
        user = cls(
            email=command.email, name=command.name, password_hash=command.password_hash
        )
        user.raise_event(
            Registered(
                email=command.email,
                name=command.name,
                password_hash=command.password_hash,
            )
        )

        return user


class UserCommandHandler(BaseCommandHandler):
    @handle(Registered)
    def register_user(self, command: Register) -> None:
        User.register(command)


def test_that_events_can_be_raised_from_within_aggregates():
    pass
