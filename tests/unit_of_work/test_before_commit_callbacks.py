"""A Unit of Work runs its pre-commit callbacks after the aggregate events are
appended and before the outbox rows are saved, inside its transaction."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import (
    ExpectedVersionError,
    ObjectNotFoundError,
    TransactionError,
)
from protean.fields import String
from protean.infra.dao import DAO
from protean.infra.event_store import EventStore


class Ticket(BaseAggregate):
    title = String()

    def open(self) -> None:
        self.raise_(TicketOpened(title=self.title))


class TicketOpened(BaseEvent):
    title = String()


@pytest.fixture(scope="session")
def db_config():
    return {"provider": "memory"}


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["enable_outbox"] = True
    test_domain.config["server"]["default_subscription_type"] = "stream"
    test_domain.register(Ticket)
    test_domain.register(TicketOpened, part_of=Ticket)
    test_domain.init(traverse=False)


@pytest.fixture
def steps(monkeypatch) -> list[str]:
    """Record the event-store appends and the outbox row saves of a commit."""
    recorded: list[str] = []
    orig_append = EventStore.append
    orig_save_if_absent = DAO.save_if_absent

    def traced_append(self, obj):
        recorded.append("append")
        return orig_append(self, obj)

    def traced_save_if_absent(self, entity, *args, **kwargs):
        recorded.append("save_outbox_row")
        return orig_save_if_absent(self, entity, *args, **kwargs)

    monkeypatch.setattr(EventStore, "append", traced_append)
    monkeypatch.setattr(DAO, "save_if_absent", traced_save_if_absent)
    return recorded


def add_ticket(test_domain, title: str) -> Ticket:
    ticket = Ticket(title=title)
    ticket.open()
    test_domain.repository_for(Ticket).add(ticket)
    return ticket


def test_a_callback_runs_between_the_append_and_the_outbox_save(test_domain, steps):
    with UnitOfWork() as uow:
        add_ticket(test_domain, "Broken login")
        uow._before_commit.append(lambda: steps.append("before_commit"))

    assert steps == ["append", "before_commit", "save_outbox_row"]


def test_a_callback_registered_by_a_callback_runs(test_domain):
    ran: list[str] = []

    with UnitOfWork() as uow:

        def first() -> None:
            ran.append("first")
            uow._before_commit.append(lambda: ran.append("second"))

        uow._before_commit.append(first)

    assert ran == ["first", "second"]


def test_a_raising_callback_rolls_back_every_session(test_domain):
    def fail() -> None:
        raise RuntimeError("the callback fails")

    with pytest.raises(TransactionError, match="the callback fails"):
        with UnitOfWork() as uow:
            ticket = add_ticket(test_domain, "Broken login")
            uow._before_commit.append(fail)

    with pytest.raises(ObjectNotFoundError):
        test_domain.repository_for(Ticket).get(ticket.id)
    assert test_domain._get_outbox_repo("default").find_unprocessed() == []


def test_an_expected_version_error_propagates_unchanged(test_domain):
    def conflict() -> None:
        raise ExpectedVersionError("another writer appended first")

    with pytest.raises(ExpectedVersionError, match="another writer appended first"):
        with UnitOfWork() as uow:
            ticket = add_ticket(test_domain, "Broken login")
            uow._before_commit.append(conflict)

    with pytest.raises(ObjectNotFoundError):
        test_domain.repository_for(Ticket).get(ticket.id)


def test_a_rolled_back_transaction_callback_does_not_run_on_reuse(test_domain):
    ran: list[str] = []
    uow = UnitOfWork()

    uow.start()
    uow._before_commit.append(lambda: ran.append("rolled back"))
    uow.rollback()

    uow.start()
    uow._before_commit.append(lambda: ran.append("committed"))
    uow.commit()

    assert ran == ["committed"]


def test_a_committed_transaction_callback_does_not_run_on_reuse(test_domain):
    ran: list[str] = []
    uow = UnitOfWork()

    uow.start()
    uow._before_commit.append(lambda: ran.append("first"))
    uow.commit()
    uow.start()
    uow.commit()

    assert ran == ["first"]


def test_the_memory_store_writes_at_once_inside_a_unit_of_work(test_domain):
    store = test_domain.event_store._require_adapter()

    with UnitOfWork():
        assert store.write_message("ticket-1", "Opened", {}) == 0
        assert len(store.get_stream_messages("ticket-1")) == 1
