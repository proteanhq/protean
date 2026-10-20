"""Outbox rows of equal priority are claimed in commit order.

The claim order is ``-priority``, ``created_at``, ``sequence_number``, ``id``,
where the Unit of Work writes each event's position within its commit to
``sequence_number``. Each ordering test inserts rows in an order that differs
from commit order, so a claim that only sorted by priority would return them in
insertion (physical) order and fail.

Marked ``transactional`` so the suite runs on the in-memory adapter and on every
SQL database the test matrix covers.
"""

from datetime import UTC, datetime, timedelta

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Integer, String
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox, OutboxStatus

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


class Counter(BaseAggregate):
    name: String(max_length=50, required=True)
    count: Integer(default=0)

    def bump(self, times: int = 1) -> None:
        for _ in range(times):
            self.count += 1
            self.raise_(Bumped(counter_id=self.id, count=self.count))


class Bumped(BaseEvent):
    counter_id: String(required=True)
    count: Integer(required=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["enable_outbox"] = True
    test_domain.config["server"]["default_subscription_type"] = "stream"
    test_domain.register(Counter)
    test_domain.register(Bumped, part_of=Counter)
    test_domain.init(traverse=False)


@pytest.fixture
def outbox_repo(test_domain):
    return test_domain._get_outbox_repo("default")


def _row(
    label: str,
    created_at: datetime,
    sequence_number: int | None,
    priority: int = 0,
) -> Outbox:
    metadata = Metadata(
        headers=MessageHeaders(id=label, type="Test.Bumped.v1", stream="test-stream"),
        domain=DomainMeta(stream_category="test-stream"),
    )
    row = Outbox.create_message(
        message_id=label,
        stream_name="test-stream",
        message_type="Test.Bumped.v1",
        data={"label": label},
        metadata=metadata,
        priority=priority,
        sequence_number=sequence_number,
    )
    row.created_at = created_at
    return row


def _insert(outbox_repo, rows: list[Outbox]) -> None:
    for row in rows:
        outbox_repo.add(row)


def _labels(rows: list[Outbox]) -> list[str]:
    return [row.message_id for row in rows]


@pytest.mark.transactional
class TestClaimInCommitOrder:
    def test_separate_commits_are_claimed_in_commit_order(
        self, test_domain, outbox_repo
    ):
        counter = Counter(name="c")
        repo = test_domain.repository_for(Counter)
        for _ in range(10):
            with UnitOfWork():
                counter.bump()
                repo.add(counter)

        rows = outbox_repo._dao.query.all().items
        assert len(rows) == 10

        # Re-insert the same rows newest first, so insertion order is the
        # reverse of commit order. Each row gets a ``created_at`` a second
        # apart in commit order: SQL Server's ``DATETIME`` rounds to about
        # 3 ms, so two fast commits could otherwise share a timestamp and
        # leave the tie to the random ids.
        outbox_repo._dao._delete_all()
        for row in sorted(rows, key=lambda r: r.data["count"], reverse=True):
            row.created_at = BASE_TIME + timedelta(seconds=row.data["count"])
            row.state_.mark_new()
            outbox_repo.add(row)

        claimed = outbox_repo.claim_batch("worker-1", limit=10)

        assert [row.data["count"] for row in claimed] == list(range(1, 11))

    def test_equal_created_at_is_ordered_by_sequence_number(self, outbox_repo):
        _insert(
            outbox_repo,
            [_row(f"seq-{n}", BASE_TIME, n) for n in (3, 1, 4, 0, 2)],
        )

        claimed = outbox_repo.claim_batch("worker-1", limit=10)

        assert _labels(claimed) == ["seq-0", "seq-1", "seq-2", "seq-3", "seq-4"]

    def test_commit_time_comes_before_sequence_number(self, outbox_repo):
        # Commit A raised two events, commit B one. Numbering restarts at 0 in
        # each commit, so sorting by ``sequence_number`` before ``created_at``
        # would put B's first event between A's two.
        _insert(
            outbox_repo,
            [
                _row("b-0", BASE_TIME + timedelta(seconds=2), 0),
                _row("a-1", BASE_TIME + timedelta(seconds=1), 1),
                _row("a-0", BASE_TIME, 0),
            ],
        )

        claimed = outbox_repo.claim_batch("worker-1", limit=10)

        assert _labels(claimed) == ["a-0", "a-1", "b-0"]

    def test_priority_comes_before_commit_order(self, outbox_repo):
        # The low-priority rows were committed first, yet the high-priority
        # rows are claimed ahead of them.
        _insert(
            outbox_repo,
            [
                _row("high-b", BASE_TIME + timedelta(seconds=4), 0, priority=5),
                _row("low-b", BASE_TIME + timedelta(seconds=1), 0, priority=0),
                _row("high-a", BASE_TIME + timedelta(seconds=3), 0, priority=5),
                _row("low-a", BASE_TIME, 0, priority=0),
            ],
        )

        claimed = outbox_repo.claim_batch("worker-1", limit=10)

        assert _labels(claimed) == ["high-a", "high-b", "low-a", "low-b"]

    def test_limit_claims_the_earliest_rows(self, outbox_repo):
        order = [7, 2, 9, 0, 5, 3, 8, 1, 6, 4]
        _insert(
            outbox_repo,
            [_row(f"row-{n}", BASE_TIME + timedelta(seconds=n), 0) for n in order],
        )

        claimed = outbox_repo.claim_batch("worker-1", limit=3)

        assert _labels(claimed) == ["row-0", "row-1", "row-2"]
        pending = outbox_repo._dao.query.filter(status=OutboxStatus.PENDING.value).all()
        assert sorted(_labels(pending.items)) == [f"row-{n}" for n in range(3, 10)]

    def test_find_unprocessed_matches_claim_batch(self, outbox_repo):
        _insert(
            outbox_repo,
            [
                _row("b", BASE_TIME + timedelta(seconds=1), 1),
                _row("c", BASE_TIME + timedelta(seconds=1), 0, priority=2),
                _row("a", BASE_TIME + timedelta(seconds=1), 0),
                _row("d", BASE_TIME, 0),
            ],
        )

        listed = _labels(outbox_repo.find_unprocessed())
        claimed = _labels(outbox_repo.claim_batch("worker-1", limit=10))

        assert listed == ["c", "d", "a", "b"]
        assert claimed == listed

    def test_null_sequence_number_rows_are_claimed_last(self, outbox_repo):
        # Rows written before the Unit of Work set ``sequence_number`` carry
        # NULL. They sort after the numbered rows of the same ``created_at``.
        _insert(
            outbox_repo,
            [
                _row("late", BASE_TIME + timedelta(seconds=1), None),
                _row("legacy", BASE_TIME, None),
                _row("numbered-1", BASE_TIME, 1),
                _row("numbered-0", BASE_TIME, 0),
            ],
        )

        listed = _labels(outbox_repo.find_unprocessed())
        claimed = _labels(outbox_repo.claim_batch("worker-1", limit=10))

        assert listed == ["numbered-0", "numbered-1", "legacy", "late"]
        assert claimed == listed

    def test_id_breaks_a_tie_on_every_other_key(self, outbox_repo):
        ids = [f"00000000-0000-0000-0000-00000000000{n}" for n in range(1, 5)]
        rows = []
        for n in (3, 1, 4, 2):
            values = _row(f"tie-{n}", BASE_TIME, 0).to_dict()
            values["id"] = ids[n - 1]
            rows.append(Outbox(**values))
        _insert(outbox_repo, rows)

        listed = _labels(outbox_repo.find_unprocessed())
        claimed = _labels(outbox_repo.claim_batch("worker-1", limit=10))

        assert listed == ["tie-1", "tie-2", "tie-3", "tie-4"]
        assert claimed == listed


@pytest.mark.transactional
class TestSequenceNumberPerCommit:
    def test_events_of_one_commit_are_numbered_in_event_order(
        self, test_domain, outbox_repo
    ):
        counter = Counter(name="c")
        with UnitOfWork():
            counter.bump(times=5)
            test_domain.repository_for(Counter).add(counter)

        rows = outbox_repo._dao.query.all().items
        assert len(rows) == 5
        by_count = {row.data["count"]: row.sequence_number for row in rows}
        assert by_count == {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}

    def test_numbering_restarts_for_each_commit(self, test_domain, outbox_repo):
        counter = Counter(name="c")
        repo = test_domain.repository_for(Counter)
        with UnitOfWork():
            counter.bump(times=2)
            repo.add(counter)
        with UnitOfWork():
            counter.bump(times=3)
            repo.add(counter)

        rows = outbox_repo._dao.query.all().items
        assert len(rows) == 5
        by_count = {row.data["count"]: row.sequence_number for row in rows}
        assert by_count == {1: 0, 2: 1, 3: 0, 4: 1, 5: 2}

    def test_one_counter_spans_every_aggregate_of_a_provider(
        self, test_domain, outbox_repo
    ):
        first = Counter(name="first")
        second = Counter(name="second")
        repo = test_domain.repository_for(Counter)
        with UnitOfWork():
            first.bump(times=2)
            second.bump(times=3)
            repo.add(first)
            repo.add(second)

        rows = outbox_repo._dao.query.all().items
        assert len(rows) == 5
        assert sorted(row.sequence_number for row in rows) == [0, 1, 2, 3, 4]
        for counter in (first, second):
            numbers = [
                row.sequence_number
                for row in sorted(rows, key=lambda r: r.data["count"])
                if row.data["counter_id"] == counter.id
            ]
            assert numbers
            assert numbers == sorted(numbers)


class Tally(BaseAggregate):
    name: String(max_length=50, required=True)
    count: Integer(default=0)

    def bump(self, times: int = 1) -> None:
        for _ in range(times):
            self.count += 1
            self.raise_(Tallied(tally_id=self.id, count=self.count))


class Tallied(BaseEvent):
    tally_id: String(required=True)
    count: Integer(required=True)


@pytest.mark.transactional
def test_numbering_restarts_for_each_provider(test_domain):
    test_domain.config["databases"]["secondary"] = {"provider": "memory"}
    test_domain.register(Tally, provider="secondary")
    test_domain.register(Tallied, part_of=Tally)
    test_domain.init(traverse=False)

    counter = Counter(name="c")
    tally = Tally(name="t")
    with UnitOfWork():
        counter.bump(times=2)
        tally.bump(times=3)
        test_domain.repository_for(Counter).add(counter)
        test_domain.repository_for(Tally).add(tally)

    for provider, expected in (("default", [0, 1]), ("secondary", [0, 1, 2])):
        rows = test_domain._get_outbox_repo(provider)._dao.query.all().items
        numbers = [
            r.sequence_number for r in sorted(rows, key=lambda r: r.data["count"])
        ]
        assert numbers == expected
