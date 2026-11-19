"""A Unit of Work commit runs its steps in one fixed order: flush the
sessions, append the events, save the outbox rows, leave the context stack,
commit the sessions, then run the after-commit callbacks."""

import pytest

from protean.adapters.database.memory import MemorySession
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork, run_after_commit
from protean.fields import String
from protean.infra.dao import DAO
from protean.port.event_store import BaseEventStore
from protean.utils.globals import _uow_context_stack


class Ticket(BaseAggregate):
    title = String()

    def open(self) -> None:
        self.raise_(TicketOpened(title=self.title))


class TicketOpened(BaseEvent):
    title = String()


@pytest.fixture(scope="session")
def db_config():
    # The ``steps`` fixture traces the memory adapter's session and DAO.
    return {"provider": "memory"}


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["enable_outbox"] = True
    test_domain.config["server"]["default_subscription_type"] = "stream"
    test_domain.register(Ticket)
    test_domain.register(TicketOpened, part_of=Ticket)
    test_domain.init(traverse=False)


@pytest.fixture
def steps(monkeypatch) -> list[tuple[str, bool]]:
    """Record each commit step with whether a Unit of Work is still on the
    context stack when it runs."""
    recorded: list[tuple[str, bool]] = []

    def on_stack() -> bool:
        return _uow_context_stack.top is not None

    orig_flush = MemorySession.flush
    orig_commit = MemorySession.commit
    orig_append = BaseEventStore.append
    orig_save_if_absent = DAO.save_if_absent

    def traced_flush(self):
        recorded.append(("flush", on_stack()))
        return orig_flush(self)

    def traced_commit(self):
        recorded.append(("commit", on_stack()))
        return orig_commit(self)

    def traced_append(self, obj):
        recorded.append(("append", on_stack()))
        return orig_append(self, obj)

    def traced_save_if_absent(self, entity, *args, **kwargs):
        recorded.append(("save_outbox_row", on_stack()))
        return orig_save_if_absent(self, entity, *args, **kwargs)

    monkeypatch.setattr(MemorySession, "flush", traced_flush)
    monkeypatch.setattr(MemorySession, "commit", traced_commit)
    monkeypatch.setattr(BaseEventStore, "append", traced_append)
    monkeypatch.setattr(DAO, "save_if_absent", traced_save_if_absent)
    return recorded


def test_commit_steps_run_in_order(test_domain, steps):
    with UnitOfWork():
        ticket = Ticket(title="Broken login")
        ticket.open()
        test_domain.repository_for(Ticket).add(ticket)
        run_after_commit(lambda: steps.append(("after_commit", False)))

    assert steps == [
        ("flush", True),
        ("append", True),
        ("save_outbox_row", True),
        ("commit", False),
        ("after_commit", False),
    ]
