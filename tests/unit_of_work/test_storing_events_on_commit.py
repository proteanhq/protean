from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.fields import String
from protean.fields.basic import Identifier
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


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


class User(BaseAggregate):
    email = String()
    name = String()
    password_hash = String()

    @classmethod
    def register(cls, command: Register) -> "User":
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
    def on_registered(self, event: Registered) -> None:
        self.id = event.id
        self.email = event.email
        self.name = event.name
        self.password_hash = event.password_hash


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


def test_event_store_append_precedes_relational_commit(test_domain, monkeypatch):
    """ADR-0015: the event-store append is the durable anchor of the
    commit and must run before the relational session commit. A crash between
    the two then leaves the events durable (recoverable) rather than leaving the
    store missing an event whose state/outbox already committed.
    """
    from protean.adapters.repository.memory import MemorySession
    from protean.port.event_store import BaseEventStore

    order: list[str] = []
    orig_append = BaseEventStore.append
    orig_commit = MemorySession.commit

    def traced_append(self, obj):
        order.append("append")
        return orig_append(self, obj)

    def traced_commit(self):
        order.append("commit")
        return orig_commit(self)

    monkeypatch.setattr(BaseEventStore, "append", traced_append)
    monkeypatch.setattr(MemorySession, "commit", traced_commit)

    UserCommandHandler().register_user(
        Register(
            id=str(uuid4()),
            email="john.doe@example.com",
            name="John Doe",
            password_hash="hash",
        )
    )

    assert "append" in order, order
    assert "commit" in order, order
    # The first append must precede the first relational commit.
    assert order.index("append") < order.index("commit"), order


def test_uow_rollback_does_not_pop_a_parent_unit_of_work(test_domain):
    """Guard for the reordered pop: a UnitOfWork only pops itself off the
    context stack. After ``_do_commit`` pops this UoW, a failing relational
    commit triggers ``__exit__`` -> ``rollback()``, which also pops; the identity
    guard ensures that second pop cannot remove a *parent* UoW in a nested
    scenario.
    """
    from protean.core.unit_of_work import UnitOfWork
    from protean.utils.globals import _uow_context_stack

    outer = UnitOfWork()
    inner = UnitOfWork()
    inner._in_progress = True
    _uow_context_stack.push(outer)
    _uow_context_stack.push(inner)
    try:
        # _do_commit already popped `inner` (its guarded pop ran).
        _uow_context_stack.pop()
        assert _uow_context_stack.top is outer

        # A failing commit then calls inner.rollback(); its guarded pop must be
        # a no-op because `inner` is no longer on top, leaving `outer` intact.
        inner.rollback()
        assert _uow_context_stack.top is outer
    finally:
        while _uow_context_stack.top is not None:
            _uow_context_stack.pop()
