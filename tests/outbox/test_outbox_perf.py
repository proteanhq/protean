"""Opt-in microbenchmark for the outbox poll-path query/round-trip counts (#942).

Gated behind ``@pytest.mark.database`` so it runs only against a real SQL
provider (e.g. ``protean test --sqlite`` / ``--postgresql``), where emitted
statements are observable and meaningful. The tests use the query-shape
primitives from :mod:`protean.integrations.pytest` to assert the performance
contract introduced by #942:

- ``find_unprocessed`` issues a single ``SELECT`` and does not over-fetch (the
  3x over-fetch loop is gone — lock/retry-window predicates are evaluated in the
  database).
- ``count_by_status`` issues one flat ``SELECT COUNT(*)`` per status with no
  subquery wrapper (no ``FROM (SELECT ... ) AS anon_1``).
- ``cleanup_old_published`` / ``cleanup_old_abandoned`` issue a single
  ``DELETE`` with no preceding read pass.

These are guards against silent regressions of the optimisation, not timing
benchmarks — they assert statement *counts* and *shapes*, which are
deterministic, rather than wall-clock duration.
"""

from datetime import datetime, timedelta, timezone

import pytest

from protean.integrations.pytest import (
    assert_no_overfetch,
    assert_no_subquery_wrap,
    assert_query_count,
)
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
    """The poll path must not regress to multi-query / over-fetch shapes.

    Expressed with the query-shape primitives, which resolve the engine from the
    active domain. The yielded statement list is reused for the finer-grained
    predicate/shape assertions the primitives don't cover (WHERE-clause contents,
    no-read-before-delete). No-op on the in-memory backend.
    """

    def _selects(self, statements: list[str]) -> list[str]:
        return [s for s in statements if s.lstrip().upper().startswith("SELECT")]

    def test_find_unprocessed_issues_a_single_select_without_overfetch(
        self, test_domain, sample_metadata
    ):
        _seed(test_domain, sample_metadata)
        repo = test_domain.repository_for(Outbox)

        with assert_no_overfetch(expected_returned=5):
            with assert_query_count(1) as statements:
                ready = repo.find_unprocessed(limit=5)

        assert len(ready) == 5
        # Statement-shape checks only run against a real SQL backend (the
        # primitives capture nothing on the in-memory adapter).
        if statements:
            # Lock + retry-window predicates are in the WHERE clause, not Python.
            where = self._selects(statements)[0].upper()
            assert "LOCKED_UNTIL" in where
            assert "NEXT_RETRY_AT" in where

    def test_count_by_status_issues_flat_counts_without_wrapper(
        self, test_domain, sample_metadata
    ):
        _seed(test_domain, sample_metadata)
        repo = test_domain.repository_for(Outbox)

        with assert_no_subquery_wrap():
            with assert_query_count(len(OutboxStatus)) as statements:
                counts = repo.count_by_status()

        assert counts[OutboxStatus.PENDING.value] == 5
        assert counts[OutboxStatus.FAILED.value] == 3
        assert counts[OutboxStatus.PUBLISHED.value] == 4
        assert counts[OutboxStatus.ABANDONED.value] == 2
        # One flat COUNT per status (the query count above pins the round trips).
        if statements:
            for stmt in self._selects(statements):
                assert "COUNT(" in stmt.upper()

    def test_cleanup_old_published_issues_single_delete(
        self, test_domain, sample_metadata
    ):
        _seed(test_domain, sample_metadata)
        repo = test_domain.repository_for(Outbox)

        with assert_query_count(1) as statements:
            deleted = repo.cleanup_old_published(older_than_hours=1)

        assert deleted == 4
        # The single query is the DELETE — no read pass precedes it.
        if statements:
            assert self._selects(statements) == []

    def test_cleanup_old_abandoned_issues_single_delete(
        self, test_domain, sample_metadata
    ):
        _seed(test_domain, sample_metadata)
        repo = test_domain.repository_for(Outbox)

        with assert_query_count(1) as statements:
            deleted = repo.cleanup_old_abandoned(older_than_hours=1)

        assert deleted == 2
        if statements:
            assert self._selects(statements) == []
