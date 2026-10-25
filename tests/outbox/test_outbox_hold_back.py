"""A partition key's later outbox rows wait until its earlier rows publish.

``claim_batch`` groups rows that carry both a ``partition_key`` and a
``stream_category`` by ``(target_broker, stream_category, partition_key,
lane)``. A grouped row is claimed only when every earlier row of its group is
published or claimed in the same call (ADR-0028, outbox-side ordering).

Where a test seeds both rows at once, it inserts the later row first, so a
claim that ignored the group would still return it.

Marked ``transactional`` so the suite runs on the in-memory adapter and on every
SQL database the test matrix covers.
"""

from datetime import UTC, datetime, timedelta

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Integer, String
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox, OutboxStatus

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
CATEGORY = "test::counter"


class Counter(BaseAggregate):
    name: String(max_length=50, required=True)
    count: Integer(default=0)


class Bumped(BaseEvent):
    counter_id: String(required=True)
    count: Integer(required=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.config["enable_outbox"] = True
    test_domain.config["server"]["default_subscription_type"] = "stream"
    test_domain.config["outbox"]["external_brokers"] = ["external"]
    test_domain.register(Counter)
    test_domain.register(Bumped, part_of=Counter)
    test_domain.init(traverse=False)


@pytest.fixture
def outbox_repo(test_domain):
    return test_domain._get_outbox_repo("default")


@pytest.fixture
def now(test_domain):
    return test_domain.clock.now()


def _row(
    label: str,
    minute: int,
    key: str | None = "client-1",
    category: str | None = CATEGORY,
    priority: int = 0,
    broker: str = "default",
) -> Outbox:
    metadata = Metadata(
        headers=MessageHeaders(id=label, type="Test.Bumped.v1", stream=CATEGORY),
        domain=DomainMeta(stream_category=CATEGORY),
    )
    row = Outbox.create_message(
        message_id=label,
        stream_name=f"{CATEGORY}-1",
        message_type="Test.Bumped.v1",
        data={"label": label},
        metadata=metadata,
        priority=priority,
        sequence_number=0,
        target_broker=broker,
        partition_key=key,
        stream_category=category,
    )
    row.created_at = BASE_TIME + timedelta(minutes=minute)
    return row


def _failed(row: Outbox, next_retry_at: datetime) -> Outbox:
    row.status = OutboxStatus.FAILED.value
    row.retry_count = 1
    row.next_retry_at = next_retry_at
    return row


def _abandoned(row: Outbox) -> Outbox:
    row.status = OutboxStatus.ABANDONED.value
    row.retry_count = row.max_retries
    return row


def _insert(outbox_repo, *rows: Outbox) -> None:
    for row in rows:
        outbox_repo.add(row)


def _publish(outbox_repo, label: str) -> None:
    [row] = outbox_repo.find_all_by_message_id(label)
    row.status = OutboxStatus.PUBLISHED.value
    row.locked_by = None
    row.locked_until = None
    outbox_repo.add(row)


def _labels(rows: list[Outbox]) -> list[str]:
    return [row.message_id for row in rows]


@pytest.mark.transactional
class TestEarlierRowHoldsLaterRows:
    def test_a_failed_row_holds_the_next_row_until_it_publishes(self, outbox_repo, now):
        _insert(
            outbox_repo,
            _row("b", minute=1),
            _failed(_row("a", minute=0), next_retry_at=now + timedelta(hours=1)),
        )

        assert outbox_repo.claim_batch("worker-1", limit=10) == []

        _publish(outbox_repo, "a")

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["b"]

    def test_a_failed_row_due_for_retry_is_claimed_with_the_next_row(
        self, outbox_repo, now
    ):
        _insert(
            outbox_repo,
            _row("b", minute=1),
            _failed(_row("a", minute=0), next_retry_at=now - timedelta(minutes=1)),
        )

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["a", "b"]

    def test_an_abandoned_row_halts_its_key(self, outbox_repo):
        _insert(outbox_repo, _row("b", minute=1), _abandoned(_row("a", minute=0)))

        assert outbox_repo.claim_batch("worker-1", limit=10) == []
        assert outbox_repo.claim_batch("worker-2", limit=10) == []

    def test_a_row_another_worker_holds_blocks_the_next_row(self, outbox_repo):
        _insert(outbox_repo, _row("a", minute=0))
        assert _labels(outbox_repo.claim_batch("worker-1", limit=1)) == ["a"]
        _insert(outbox_repo, _row("b", minute=1))

        assert outbox_repo.claim_batch("worker-2", limit=10) == []

    def test_pending_rows_of_one_key_are_claimed_together_in_order(self, outbox_repo):
        _insert(outbox_repo, _row("c", minute=2), _row("b", minute=1))
        _insert(outbox_repo, _row("a", minute=0))

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == [
            "a",
            "b",
            "c",
        ]

    def test_a_published_row_holds_nothing(self, outbox_repo):
        _insert(outbox_repo, _row("b", minute=1), _row("a", minute=0))
        _publish(outbox_repo, "a")

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["b"]


@pytest.mark.transactional
class TestOtherRowsKeepFlowing:
    def test_another_key_is_claimed_while_one_key_is_halted(self, outbox_repo):
        _insert(
            outbox_repo,
            _row("k1-b", minute=1),
            _abandoned(_row("k1-a", minute=0)),
            _row("k2-a", minute=2, key="client-2"),
        )

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["k2-a"]

    def test_a_halted_backlog_larger_than_the_batch_does_not_starve_other_keys(
        self, outbox_repo
    ):
        _insert(outbox_repo, _abandoned(_row("k1-0", minute=0)))
        _insert(outbox_repo, *[_row(f"k1-{n}", minute=n) for n in range(1, 8)])
        _insert(
            outbox_repo,
            *[_row(f"k2-{n}", minute=10 + n, key="client-2") for n in range(3)],
        )

        claimed = outbox_repo.claim_batch("worker-1", limit=3)

        assert _labels(claimed) == ["k2-0", "k2-1", "k2-2"]

    def test_a_later_high_priority_row_waits_for_its_earlier_low_priority_row(
        self, outbox_repo
    ):
        _insert(
            outbox_repo,
            _row("k1-late-high", minute=1, priority=10),
            _row("k1-early-low", minute=0, priority=0),
            _row("k2", minute=2, key="client-2", priority=5),
        )

        first = outbox_repo.claim_batch("worker-1", limit=2)
        assert _labels(first) == ["k2", "k1-early-low"]

        # The earlier row is now in flight, so the later one still waits.
        assert outbox_repo.claim_batch("worker-2", limit=10) == []

        _publish(outbox_repo, "k1-early-low")

        assert _labels(outbox_repo.claim_batch("worker-2", limit=10)) == [
            "k1-late-high"
        ]

    def test_a_row_without_a_partition_key_is_never_held(self, outbox_repo, now):
        _insert(
            outbox_repo,
            _row("b", minute=1, key=None),
            _failed(
                _row("a", minute=0, key=None), next_retry_at=now + timedelta(hours=1)
            ),
        )

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["b"]

    def test_a_row_without_a_stream_category_neither_holds_nor_is_held(
        self, outbox_repo, now
    ):
        _insert(
            outbox_repo,
            _row("legacy-b", minute=2, category=None),
            _row("new-b", minute=1),
            _failed(
                _row("legacy-a", minute=0, category=None),
                next_retry_at=now + timedelta(hours=1),
            ),
        )

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == [
            "new-b",
            "legacy-b",
        ]

    def test_another_stream_category_is_another_group(self, outbox_repo):
        _insert(
            outbox_repo,
            _row("other-b", minute=1, category="test::other"),
            _abandoned(_row("a", minute=0)),
        )

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["other-b"]


@pytest.mark.transactional
class TestGroupsFollowTheDestinationStream:
    def test_each_broker_is_its_own_group(self, outbox_repo, now):
        _insert(
            outbox_repo,
            _row("default-b", minute=1),
            _row("external-b", minute=1, broker="external"),
            _failed(
                _row("default-a", minute=0), next_retry_at=now + timedelta(hours=1)
            ),
        )

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["external-b"]

    def test_lanes_disabled_put_every_priority_in_one_group(self, outbox_repo):
        _insert(
            outbox_repo,
            _row("high-b", minute=1, priority=10),
            _abandoned(_row("low-a", minute=0, priority=0)),
        )

        assert outbox_repo.claim_batch("worker-1", limit=10) == []

    def test_lanes_enabled_split_the_group_by_lane(self, test_domain, outbox_repo, now):
        test_domain.config["server"]["priority_lanes"] = {
            "enabled": True,
            "threshold": 5,
        }
        _insert(
            outbox_repo,
            _row("primary-b", minute=1, priority=10),
            _row("backfill-b", minute=1, priority=0),
            _failed(
                _row("backfill-a", minute=0, priority=0),
                next_retry_at=now + timedelta(hours=1),
            ),
        )

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["primary-b"]

    def test_external_rows_stay_in_the_primary_lane(self, test_domain, outbox_repo):
        test_domain.config["server"]["priority_lanes"] = {
            "enabled": True,
            "threshold": 5,
        }
        # A low-priority external row is primary, so it holds a high-priority
        # external row of its key.
        _insert(
            outbox_repo,
            _row("external-high-b", minute=1, priority=10, broker="external"),
            _abandoned(_row("external-low-a", minute=0, priority=0, broker="external")),
        )

        assert outbox_repo.claim_batch("worker-1", limit=10) == []


@pytest.mark.transactional
class TestCleanupKeepsHaltingRows:
    def test_old_abandoned_rows_with_a_partition_key_are_kept(self, outbox_repo, now):
        old = now - timedelta(hours=1000)
        keyed = _abandoned(_row("keyed", minute=0))
        unkeyed = _abandoned(_row("unkeyed", minute=0, key=None))
        for row in (keyed, unkeyed):
            row.last_processed_at = old
        _insert(outbox_repo, keyed, unkeyed)

        assert outbox_repo.cleanup_old_abandoned(older_than_hours=720) == 1

        remaining = outbox_repo._dao.query.all().items
        assert _labels(remaining) == ["keyed"]
