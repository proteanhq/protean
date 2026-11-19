"""The commit helpers of ``UnitOfWork`` cover the cases a plain commit inside
a domain context never reaches: a commit with no domain context, an event
whose metadata has no domain section, and a session with no flush."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import (
    UnitOfWork,
    _flush_sessions,
    _outbox_rows_for_event,
    _OutboxSettings,
    _record_commit_success,
    _record_events_raised,
)
from protean.domain import context as domain_context
from protean.fields import Identifier, String
from protean.utils.globals import g


class Ticket(BaseAggregate):
    title = String()

    def open(self) -> None:
        self.raise_(TicketOpened(ticket_id=self.id, title=self.title))


class TicketOpened(BaseEvent):
    ticket_id = Identifier()
    title = String()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Ticket)
    test_domain.register(TicketOpened, part_of=Ticket)
    test_domain.init(traverse=False)


@pytest.fixture
def no_domain_context(monkeypatch):
    monkeypatch.setattr(domain_context, "has_domain_context", lambda: False)


def _opened_event() -> TicketOpened:
    ticket = Ticket(title="Printer jam")
    ticket.open()
    return ticket._events[0]


def test_events_raised_are_not_recorded_without_a_domain_context(
    test_domain, no_domain_context
):
    g._access_log_events_raised = ["Earlier"]

    _record_events_raised({"default": [_opened_event()]})

    assert g._access_log_events_raised == ["Earlier"]


def test_events_raised_are_appended_to_the_access_log(test_domain):
    g._access_log_events_raised = ["Earlier"]

    _record_events_raised({"default": [_opened_event()]})

    assert g._access_log_events_raised == ["Earlier", "TicketOpened"]


def test_commit_outcome_is_not_recorded_without_a_domain_context(
    test_domain, no_domain_context
):
    g._access_log_uow_outcome = "unset"

    _record_commit_success(UnitOfWork(), total_events=0)

    assert g._access_log_uow_outcome == "unset"


def test_commit_outcome_is_recorded_in_a_domain_context(test_domain):
    g._access_log_uow_outcome = "unset"

    _record_commit_success(UnitOfWork(), total_events=0)

    assert g._access_log_uow_outcome == "committed"


def test_outbox_row_has_no_trace_fields_when_the_event_has_no_domain_metadata(
    test_domain,
):
    event = _opened_event()
    # An event always builds its domain metadata, so bypass the
    # immutability guard to clear it.
    object.__setattr__(
        event,
        "_metadata",
        event._metadata.__class__(**{**event._metadata.to_dict(), "domain": None}),
    )
    settings = _OutboxSettings(
        priority=0,
        internal_broker="default",
        external_brokers=[],
        partition_keys={},
        backfill_suffix="-backfill",
    )

    (row,) = _outbox_rows_for_event(UnitOfWork(), event, 0, settings)

    assert row.correlation_id is None
    assert row.causation_id is None
    assert row.stream_category is None


def test_flush_skips_a_session_without_a_flush(test_domain):
    flushed: list[str] = []

    class FlushingSession:
        def flush(self) -> None:
            flushed.append("flushing")

    class SessionWithoutFlush:
        pass

    uow = UnitOfWork()
    uow._sessions = {"b": SessionWithoutFlush(), "a": FlushingSession()}

    _flush_sessions(uow)

    assert flushed == ["flushing"]
