from __future__ import annotations

import random
import string
from uuid import uuid4

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate, apply
from protean.core.command import _LegacyBaseCommand as BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.fields import Identifier, String, Boolean
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


class Register(BaseCommand):
    user_id = Identifier()
    email = String()


class RenameAndActivate(BaseCommand):
    user_id = Identifier()


class Registered(BaseEvent):
    id = Identifier()
    email = String()


class Renamed(BaseEvent):
    id = Identifier()
    name = String()


class Activated(BaseEvent):
    id = Identifier()


class User(BaseAggregate):
    name = String()
    email = String()
    active = Boolean(default=False)

    @apply
    def registered(self, event: Registered) -> None:
        self.email = event.email

    @apply
    def renamed(self, event: Renamed) -> None:
        self.name = event.name

    @apply
    def activated(self, event: Activated) -> None:
        self.active = True


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register_user(self, command: Register) -> None:
        user = User(id=command.user_id, email=command.email)
        user.raise_(Registered(id=command.user_id, email=command.email))
        current_domain.repository_for(User).add(user)

    @handle(RenameAndActivate)
    def rename_and_activate_user(self, command: RenameAndActivate) -> None:
        user_repo = current_domain.repository_for(User)
        user = user_repo.get(command.user_id)

        user.raise_(
            Renamed(
                id=user.id,
                name="".join(random.choice(string.ascii_uppercase) for i in range(10)),
            )
        )
        user.raise_(Activated(id=user.id))

        user_repo.add(user)


def test_that_multiple_events_are_raised_per_aggregate_in_the_same_uow(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(RenameAndActivate, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(Renamed, part_of=User)
    test_domain.register(Activated, part_of=User)
    test_domain.init(traverse=False)

    identifier = str(uuid4())
    UserCommandHandler().register_user(
        Register(
            user_id=identifier,
            email="john.doe@example.com",
        )
    )

    UserCommandHandler().rename_and_activate_user(
        RenameAndActivate(
            user_id=identifier,
        )
    )

    messages = test_domain.event_store.store._read("user")

    assert len(messages) == 3
    assert messages[0]["type"] == Registered.__type__
    assert messages[1]["type"] == Renamed.__type__
    assert messages[2]["type"] == Activated.__type__
