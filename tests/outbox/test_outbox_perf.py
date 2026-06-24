"""Opt-in microbenchmark for the outbox poll-path query/round-trip counts (#942).

Gated behind ``@pytest.mark.database`` so it runs only against a real SQL
provider (e.g. ``protean test --sqlite`` / ``--postgresql``), where emitted
statements are observable and meaningful. The test attaches a SQLAlchemy
``before_cursor_execute`` listener to count statements issued on the poll path
and asserts the performance contract introduced by #942:

- ``find_unprocessed`` issues a single ``SELECT`` (the 3x over-fetch loop is
  gone — lock/retry-window predicates are evaluated in the database).
- ``count_by_status`` issues one flat ``SELECT COUNT(*)`` per status with no
  subquery wrapper (no ``FROM (SELECT ... ) AS anon_1``).
- ``cleanup_old_published`` / ``cleanup_old_abandoned`` issue a single
  ``DELETE`` with no preceding read pass.

These are guards against silent regressions of the optimisation, not timing
benchmarks — they assert statement *counts* and *shapes*, which are
deterministic, rather than wall-clock duration.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from protean.utils.eventing import DomainMeta, Metadata, MessageHeaders
from protean.utils.outbox import Outbox, OutboxRepository, OutboxStatus


@pytest.fixture(autouse=True)
def setup_outbox_domain(test_domain):
    test_domain.register(Outbox)
    test_domain.register(OutboxRepository, part_of=Outbox)
    test_domain.init(traverse=False)
    return test_domain


@pytest.fixture
def sample_metadata():
    return Metadata(
        headers=MessageHeaders(
            id="perf-id",
            type="TestEvent",
            time=datetime.now(timezone.utc),
            stream="perf-stream",
        ),
        domain=DomainMeta(
            fqn="test.TestEvent",
            kind="event",
            origin_stream="perf-aggregate-123",
            version="1.0",
            sequence_id="1",
        ),
    )


@pytest.fixture
def sa_engine(test_domain):
    """The SQLAlchemy engine backing the default provider.

    Skips the test when the active provider is not SQLAlchemy-based (statement
    counting is only meaningful against a real SQL backend).
    """
    provider = test_domain.providers["default"]
    engine = getattr(provider, "_engine", None)
    if engine is None:
        pytest.skip("Outbox perf microbenchmark requires a SQLAlchemy provider")
    return engine


@contextmanager
def capture_statements(engine):
    """Collect SQL statements emitted on ``engine`` within the block."""
    statements: list[str] = []

    def _before_cursor_execute(conn, cursor, statement, parameters, context, many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


def _seed(test_domain, sample_metadata):
    """Seed a mix of pending, failed-ready, published, and abandoned messages."""
    repo = test_domain.repository_for(Outbox)

    for i in range(5):
        msg = Outbox.create_message(
            message_id=f"pending-{i}",
            stream_name=f"stream-{i}",
            message_type="TestEvent",
            data={"index": i},
            metadata=sample_metadata,
            priority=i,
        )
        repo.add(msg)

    for i in range(3):
        msg = Outbox.create_message(
            message_id=f"failed-{i}",
            stream_name=f"failed-stream-{i}",
            message_type="FailedEvent",
            data={"index": i},
            metadata=sample_metadata,
            priority=i + 10,
        )
        msg.status = OutboxStatus.FAILED.value
        msg.retry_count = 1
        msg.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        repo.add(msg)

    for i in range(4):
        msg = Outbox.create_message(
            message_id=f"published-{i}",
            stream_name=f"published-stream-{i}",
            message_type="PublishedEvent",
            data={"index": i},
            metadata=sample_metadata,
            priority=i + 20,
        )
        msg.status = OutboxStatus.PUBLISHED.value
        msg.published_at = datetime.now(timezone.utc) - timedelta(days=30)
        repo.add(msg)

    for i in range(2):
        msg = Outbox.create_message(
            message_id=f"abandoned-{i}",
            stream_name=f"abandoned-stream-{i}",
            message_type="AbandonedEvent",
            data={"index": i},
            metadata=sample_metadata,
            priority=i + 30,
        )
        msg.status = OutboxStatus.ABANDONED.value
        msg.retry_count = 5
        msg.last_processed_at = datetime.now(timezone.utc) - timedelta(days=60)
        repo.add(msg)


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestOutboxPollPathQueryCounts:
    """The poll path must not regress to multi-query / over-fetch shapes."""

    def _selects(self, statements: list[str]) -> list[str]:
        return [s for s in statements if s.lstrip().upper().startswith("SELECT")]

    def _deletes(self, statements: list[str]) -> list[str]:
        return [s for s in statements if s.lstrip().upper().startswith("DELETE")]

    def test_find_unprocessed_issues_single_select(
        self, test_domain, sample_metadata, sa_engine
    ):
        _seed(test_domain, sample_metadata)
        repo = test_domain.repository_for(Outbox)

        with capture_statements(sa_engine) as statements:
            ready = repo.find_unprocessed(limit=5)

        selects = self._selects(statements)
        assert len(selects) == 1, f"expected a single SELECT, got: {selects}"
        # Lock + retry-window predicates are in the WHERE clause, not Python.
        where = selects[0].upper()
        assert "LOCKED_UNTIL" in where
        assert "NEXT_RETRY_AT" in where
        assert len(ready) == 5

    def test_count_by_status_issues_flat_counts_without_wrapper(
        self, test_domain, sample_metadata, sa_engine
    ):
        _seed(test_domain, sample_metadata)
        repo = test_domain.repository_for(Outbox)

        with capture_statements(sa_engine) as statements:
            counts = repo.count_by_status()

        selects = self._selects(statements)
        # One flat COUNT per status, no subquery-wrapped projection.
        assert len(selects) == len(OutboxStatus)
        for stmt in selects:
            upper = stmt.upper()
            assert "COUNT(" in upper
            assert "ANON_1" not in upper, f"unexpected subquery wrapper: {stmt}"
        assert counts[OutboxStatus.PENDING.value] == 5
        assert counts[OutboxStatus.FAILED.value] == 3
        assert counts[OutboxStatus.PUBLISHED.value] == 4
        assert counts[OutboxStatus.ABANDONED.value] == 2

    def test_cleanup_old_published_issues_single_delete(
        self, test_domain, sample_metadata, sa_engine
    ):
        _seed(test_domain, sample_metadata)
        repo = test_domain.repository_for(Outbox)

        with capture_statements(sa_engine) as statements:
            deleted = repo.cleanup_old_published(older_than_hours=1)

        assert deleted == 4
        assert len(self._deletes(statements)) == 1
        # No read pass before the delete.
        assert self._selects(statements) == []

    def test_cleanup_old_abandoned_issues_single_delete(
        self, test_domain, sample_metadata, sa_engine
    ):
        _seed(test_domain, sample_metadata)
        repo = test_domain.repository_for(Outbox)

        with capture_statements(sa_engine) as statements:
            deleted = repo.cleanup_old_abandoned(older_than_hours=1)

        assert deleted == 2
        assert len(self._deletes(statements)) == 1
        assert self._selects(statements) == []
