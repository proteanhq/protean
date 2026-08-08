"""The commit-time inline dispatch is gated on ``event_processing == "sync"``.

On commit a UnitOfWork drains raised events to their handlers *inline* only in
sync mode. In async mode the same events are written to the outbox and picked up
later by the engine, so no handler runs inside the committing call. These two
tests pin both sides of that guard: flipping or dropping the ``sync`` check would
either stop firing handlers in sync mode or fire them (a second time, eagerly) in
async mode.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.utils import Processing
from protean.utils.globals import current_domain
from protean.utils.mixins import handle

handled: list[str] = []


class Register(BaseCommand):
    user_id = Identifier()
    email = String()


class Registered(BaseEvent):
    user_id = Identifier()
    email = String()


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    email = String()

    @classmethod
    def register(cls, command: Register) -> "User":
        user = cls(user_id=command.user_id, email=command.email)
        user.raise_(Registered(user_id=command.user_id, email=command.email))
        return user

    @apply
    def registered(self, _: Registered) -> None:
        pass


class UserCommandHandler(BaseCommandHandler):
    @handle(Register)
    def register_user(self, command: Register) -> None:
        current_domain.repository_for(User).add(User.register(command))


class UserEventHandler(BaseEventHandler):
    @handle(Registered)
    def on_registered(self, event: Registered) -> None:
        handled.append(event.user_id)


def _register(test_domain, mode: str) -> None:
    test_domain.config["event_processing"] = mode
    test_domain.register(User, event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserCommandHandler, part_of=User)
    test_domain.register(UserEventHandler, part_of=User)
    test_domain.init(traverse=False)


def _process_one(test_domain) -> str:
    identifier = str(uuid4())
    test_domain.process(Register(user_id=identifier, email="john@example.com"))
    return identifier


@pytest.fixture(autouse=True)
def _reset():
    handled.clear()
    yield
    handled.clear()


@pytest.mark.eventstore
def test_sync_mode_dispatches_handler_inline_on_commit(test_domain):
    _register(test_domain, Processing.SYNC.value)

    identifier = _process_one(test_domain)

    # The handler ran inside the committing call.
    assert handled == [identifier]


@pytest.mark.eventstore
def test_async_mode_does_not_dispatch_handler_inline_on_commit(test_domain):
    _register(test_domain, Processing.ASYNC.value)

    _process_one(test_domain)

    # The event is deferred to the outbox for the engine; no handler ran inline.
    assert handled == []
