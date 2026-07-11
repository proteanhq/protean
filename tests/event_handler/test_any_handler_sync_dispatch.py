"""End-to-end regression test.

A ``@handle("$any")`` event handler scoped to an aggregate fired under async
(Engine) dispatch but was silently skipped under ``event_processing="sync"``
(the default in tests / the in-memory env), because the synchronous path routes
through ``EventStore.handlers_for``, which matched only the concrete event
``__type__`` and dropped ``$any``-keyed handlers.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle

audit_log: list[str] = []


class Register(BaseCommand):
    user_id = Identifier()
    name = String()


class Registered(BaseEvent):
    user_id = Identifier()
    name = String()


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    name = String()

    @classmethod
    def register(cls, command: Register) -> "User":
        user = cls(user_id=command.user_id, name=command.name)
        user.raise_(Registered(user_id=command.user_id, name=command.name))
        return user

    @apply
    def registered(self, _: Registered) -> None:
        pass


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register_user(self, command: Register) -> None:
        current_domain.repository_for(User).add(User.register(command))


class AuditHandler(BaseEventHandler):
    @handle("$any")
    def on_any(self, event: BaseEvent) -> None:
        audit_log.append(event.__class__.__name__)


@pytest.mark.eventstore
def test_any_handler_fires_under_sync_dispatch(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.register(AuditHandler, part_of=User)
    test_domain.init(traverse=False)

    audit_log.clear()
    test_domain.process(Register(user_id=str(uuid4()), name="John Doe"))

    assert audit_log == ["Registered"]
