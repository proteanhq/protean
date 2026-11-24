"""A partition key's later outbox rows wait until its earlier rows publish.

``claim_batch`` groups rows that carry both a ``partition_key`` and a
``stream_category`` by ``(target_broker, stream_category, partition_key,
lane)``. A grouped row is claimed only when every earlier row of its group is
published or claimed in the same call (ADR-0028, outbox-side ordering).

Where a test seeds both rows at once, it inserts the later row first, so a
claim that ignored the group would still return it.

Most classes are marked ``transactional`` so they run on the in-memory adapter
and on every SQL database the test matrix covers.
"""

import threading
from contextlib import suppress
from datetime import UTC, datetime, timedelta

import pytest

from protean.adapters.database.memory import MemorySession
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Integer, String
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import PAGE_SIZE, Outbox, OutboxStatus

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

    def test_find_unprocessed_lists_a_held_row_without_claiming_it(
        self, outbox_repo, now
    ):
        _insert(
            outbox_repo,
            _row("b", minute=1),
            _failed(_row("a", minute=0), next_retry_at=now + timedelta(hours=1)),
        )

        assert _labels(outbox_repo.find_unprocessed()) == ["b"]
        [row] = outbox_repo.find_all_by_message_id("b")
        assert row.status == OutboxStatus.PENDING.value
        assert row.locked_by is None
        assert outbox_repo.claim_batch("worker-1", limit=10) == []

    def test_a_failed_row_due_for_retry_is_claimed_with_the_next_row(
        self, outbox_repo, now
    ):
        _insert(
            outbox_repo,
            _row("b", minute=1),
            _failed(_row("a", minute=0), next_retry_at=now - timedelta(minutes=1)),
        )

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["a", "b"]

    def test_a_row_failed_under_a_higher_max_attempts_is_retried(
        self, outbox_repo, now
    ):
        # The processor passes ``outbox.retry.max_attempts`` to
        # ``mark_failed``. Above the row's ``max_retries`` of 3, the row must
        # stay claimable, or it would halt its key while still FAILED.
        _insert(outbox_repo, _row("b", minute=1), _row("a", minute=0))
        for _ in range(3):
            [row] = outbox_repo.find_all_by_message_id("a")
            row.status = OutboxStatus.PROCESSING.value
            row.mark_failed(RuntimeError("broker down"), max_retries=5, now=now)
            row.next_retry_at = now - timedelta(minutes=1)
            outbox_repo.add(row)

        [row] = outbox_repo.find_all_by_message_id("a")
        assert (row.status, row.retry_count) == (OutboxStatus.FAILED.value, 3)
        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["a", "b"]

    def test_a_row_with_no_sequence_number_sorts_after_one_with_a_number(
        self, outbox_repo, now
    ):
        # Same ``created_at``: the row without a sequence number is the later
        # one, as in the claim order.
        later = _row("later", minute=0)
        later.sequence_number = None
        earlier = _failed(_row("earlier", minute=0), now + timedelta(hours=1))
        earlier.sequence_number = 5
        _insert(outbox_repo, later, earlier)

        assert outbox_repo.claim_batch("worker-1", limit=10) == []

    def test_a_row_with_a_sequence_number_is_not_held_by_one_without(
        self, outbox_repo, now
    ):
        later = _failed(_row("later", minute=0), now + timedelta(hours=1))
        later.sequence_number = None
        earlier = _row("earlier", minute=0)
        earlier.sequence_number = 5
        _insert(outbox_repo, later, earlier)

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["earlier"]

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

    def test_old_discarded_rows_with_a_partition_key_are_deleted(
        self, outbox_repo, now
    ):
        old_row = _abandoned(_row("old", minute=0))
        assert old_row.discard("skip", now=now - timedelta(hours=1000)) is True
        recent_row = _abandoned(_row("recent", minute=1, key="client-2"))
        assert recent_row.discard("skip", now=now) is True
        _insert(outbox_repo, old_row, recent_row)

        assert outbox_repo.cleanup_old_discarded(older_than_hours=720) == 1

        remaining = outbox_repo._dao.query.all().items
        assert _labels(remaining) == ["recent"]


def _reload(outbox_repo, label: str) -> Outbox:
    [row] = outbox_repo.find_all_by_message_id(label)
    return row


@pytest.mark.transactional
class TestAnOperatorReleasesAHaltedKey:
    def test_a_discarded_head_lets_the_next_row_through(self, outbox_repo):
        _insert(outbox_repo, _row("b", minute=1), _abandoned(_row("a", minute=0)))
        head = _reload(outbox_repo, "a")
        assert head.discard("poison") is True
        assert outbox_repo.save_operator_change(
            head, OutboxStatus.ABANDONED.value, head.max_retries
        )

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["b"]
        stored = _reload(outbox_repo, "a")
        assert stored.status == OutboxStatus.DISCARDED.value
        assert stored.last_error["discard_reason"] == "poison"

    def test_a_discarded_row_without_a_key_is_never_claimed(self, outbox_repo):
        row = _abandoned(_row("a", minute=0, key=None))
        assert row.discard("poison") is True
        _insert(outbox_repo, row)

        assert outbox_repo.claim_batch("worker-1", limit=10) == []

    def test_a_retried_head_is_claimed_with_the_rest_of_its_key(self, outbox_repo):
        _insert(outbox_repo, _row("b", minute=1), _abandoned(_row("a", minute=0)))
        head = _reload(outbox_repo, "a")
        assert head.reset_for_retry() is True
        assert outbox_repo.save_operator_change(
            head, OutboxStatus.ABANDONED.value, head.max_retries
        )

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["a", "b"]

    def test_a_retried_row_with_no_retries_is_claimed(self, outbox_repo):
        row = _abandoned(_row("a", minute=0))
        row.max_retries = 0
        row.retry_count = 0
        _insert(outbox_repo, row)
        head = _reload(outbox_repo, "a")
        assert head.reset_for_retry() is True
        assert outbox_repo.save_operator_change(head, OutboxStatus.ABANDONED.value, 0)

        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["a"]

    @pytest.mark.parametrize("action", ["retry", "discard"])
    def test_a_row_a_worker_claimed_after_the_read_is_not_written(
        self, outbox_repo, now, action
    ):
        _insert(
            outbox_repo,
            _failed(_row("a", minute=0), next_retry_at=now - timedelta(minutes=1)),
        )
        stale = _reload(outbox_repo, "a")
        assert _labels(outbox_repo.claim_batch("worker-1", limit=10)) == ["a"]
        changed = stale.reset_for_retry() if action == "retry" else stale.discard("x")
        assert changed is True

        assert (
            outbox_repo.save_operator_change(stale, OutboxStatus.FAILED.value, 1)
            is False
        )

        stored = _reload(outbox_repo, "a")
        assert stored.status == OutboxStatus.PROCESSING.value
        assert stored.locked_by == "worker-1"
        assert stored.last_error is None

    def test_a_row_that_failed_again_after_the_read_is_not_written(
        self, outbox_repo, now
    ):
        _insert(
            outbox_repo,
            _failed(_row("a", minute=0), next_retry_at=now + timedelta(hours=1)),
        )
        stale = _reload(outbox_repo, "a")
        again = _reload(outbox_repo, "a")
        again.retry_count = 2
        outbox_repo.add(again)
        assert stale.discard("x") is True

        assert (
            outbox_repo.save_operator_change(stale, OutboxStatus.FAILED.value, 1)
            is False
        )
        assert _reload(outbox_repo, "a").status == OutboxStatus.FAILED.value

    @pytest.mark.parametrize("action", ["retry", "discard"])
    def test_an_operator_change_advances_the_row_version(self, outbox_repo, action):
        _insert(outbox_repo, _abandoned(_row("a", minute=0)))
        head = _reload(outbox_repo, "a")
        read_version = head._version
        changed = head.reset_for_retry() if action == "retry" else head.discard("x")
        assert changed is True

        assert outbox_repo.save_operator_change(
            head, OutboxStatus.ABANDONED.value, head.max_retries
        )
        assert _reload(outbox_repo, "a")._version == read_version + 1

    def test_a_row_saved_again_after_the_read_is_not_written(self, outbox_repo, now):
        _insert(
            outbox_repo,
            _failed(_row("a", minute=0), next_retry_at=now + timedelta(hours=1)),
        )
        stale = _reload(outbox_repo, "a")
        moved = _reload(outbox_repo, "a")
        moved.next_retry_at = now + timedelta(hours=2)
        outbox_repo.add(moved)
        assert _reload(outbox_repo, "a")._version == stale._version + 1
        assert stale.discard("x") is True

        assert (
            outbox_repo.save_operator_change(stale, OutboxStatus.FAILED.value, 1)
            is False
        )
        stored = _reload(outbox_repo, "a")
        assert stored.status == OutboxStatus.FAILED.value
        assert stored.last_error is None

    @pytest.mark.parametrize("action", ["retry", "discard"])
    def test_a_stale_change_does_not_overwrite_a_newer_failure(
        self, outbox_repo, now, action
    ):
        _insert(
            outbox_repo,
            _failed(_row("a", minute=0), next_retry_at=now - timedelta(minutes=1)),
        )
        stale = _reload(outbox_repo, "a")
        other = _reload(outbox_repo, "a")
        assert other.reset_for_retry() is True
        assert outbox_repo.save_operator_change(other, OutboxStatus.FAILED.value, 1)
        [claimed] = outbox_repo.claim_batch("worker-1", limit=10)
        claimed.mark_failed(RuntimeError("broker down again"))
        outbox_repo.add(claimed)
        changed = stale.reset_for_retry() if action == "retry" else stale.discard("x")
        assert changed is True

        assert (
            outbox_repo.save_operator_change(stale, OutboxStatus.FAILED.value, 1)
            is False
        )

        stored = _reload(outbox_repo, "a")
        assert stored.status == OutboxStatus.FAILED.value
        assert stored.retry_count == 1
        assert stored.last_error["message"] == "broker down again"
        assert "discard_reason" not in stored.last_error

    @pytest.mark.parametrize("action", ["retry", "discard"])
    def test_a_stale_change_does_not_overwrite_a_newer_abandonment(
        self, outbox_repo, now, action
    ):
        _insert(outbox_repo, _abandoned(_row("a", minute=0)))
        stale = _reload(outbox_repo, "a")
        max_retries = stale.max_retries
        other = _reload(outbox_repo, "a")
        assert other.reset_for_retry() is True
        assert outbox_repo.save_operator_change(
            other, OutboxStatus.ABANDONED.value, max_retries
        )
        for attempt in range(1, max_retries + 1):
            [claimed] = outbox_repo.claim_batch("worker-1", limit=10)
            # A failure stamped a day back leaves its retry due at once.
            claimed.mark_failed(
                RuntimeError(f"attempt {attempt}"), now=now - timedelta(days=1)
            )
            outbox_repo.add(claimed)
        changed = stale.reset_for_retry() if action == "retry" else stale.discard("x")
        assert changed is True

        assert (
            outbox_repo.save_operator_change(
                stale, OutboxStatus.ABANDONED.value, max_retries
            )
            is False
        )

        stored = _reload(outbox_repo, "a")
        assert stored.status == OutboxStatus.ABANDONED.value
        assert stored.retry_count == max_retries
        assert stored.last_error["message"] == f"attempt {max_retries}"
        assert "discard_reason" not in stored.last_error


class TestAnOperatorChangeDoesNotOverlapAClaim:
    """Runs on the memory provider only: the patched ``MemorySession.write``
    never fires on a SQL provider."""

    @pytest.mark.parametrize("action", ["retry", "discard"])
    def test_a_claim_waits_for_the_operator_write(
        self, test_domain, outbox_repo, now, monkeypatch, action
    ):
        _insert(
            outbox_repo,
            _failed(_row("a", minute=0), next_retry_at=now - timedelta(minutes=1)),
        )
        meet = threading.Barrier(2, timeout=0.5)
        operator_writing = threading.Event()
        write = MemorySession.write

        def write_after_meeting(self, *args, **kwargs):
            if threading.current_thread().name == "operator":
                operator_writing.set()
            with suppress(threading.BrokenBarrierError):
                meet.wait()
            return write(self, *args, **kwargs)

        monkeypatch.setattr(MemorySession, "write", write_after_meeting)
        results: dict[str, object] = {}

        def operator() -> None:
            with test_domain.domain_context():
                repo = test_domain._get_outbox_repo("default")
                row = _reload(repo, "a")
                changed = (
                    row.reset_for_retry()
                    if action == "retry"
                    else row.discard("poison")
                )
                assert changed is True
                results["saved"] = repo.save_operator_change(
                    row, OutboxStatus.FAILED.value, 1
                )

        def worker() -> None:
            assert operator_writing.wait(timeout=5)
            with test_domain.domain_context():
                repo = test_domain._get_outbox_repo("default")
                results["claimed"] = _labels(repo.claim_batch("worker-1", limit=10))

        threads = [
            threading.Thread(target=operator, name="operator", daemon=True),
            threading.Thread(target=worker, name="worker", daemon=True),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert not any(thread.is_alive() for thread in threads)

        assert results["saved"] is True
        stored = _reload(outbox_repo, "a")
        if action == "discard":
            assert results["claimed"] == []
            assert stored.status == OutboxStatus.DISCARDED.value
            assert stored.last_error["discard_reason"] == "poison"
        else:
            assert results["claimed"] == ["a"]
            assert stored.status == OutboxStatus.PROCESSING.value
            assert stored.locked_by == "worker-1"


def _halted(outbox_repo) -> list[tuple[str, str, str, str, int]]:
    return [
        (
            key.target_broker,
            key.partition_key,
            key.lane,
            key.head.message_id,
            key.waiting,
        )
        for key in outbox_repo.find_halted()
    ]


@pytest.mark.transactional
class TestFindHalted:
    def test_an_abandoned_head_is_listed_with_the_rows_behind_it(self, outbox_repo):
        _insert(
            outbox_repo,
            _row("c", minute=2),
            _row("b", minute=1),
            _abandoned(_row("a", minute=0)),
            _row("other", minute=0, key="client-2"),
        )

        [key] = outbox_repo.find_halted()

        assert key.stream_category == CATEGORY
        assert key.head.status == OutboxStatus.ABANDONED.value
        assert _halted(outbox_repo) == [("default", "client-1", "primary", "a", 2)]

    def test_no_halted_key_lists_nothing(self, outbox_repo, now):
        _insert(
            outbox_repo,
            _row("b", minute=1),
            _failed(_row("a", minute=0), next_retry_at=now + timedelta(hours=1)),
        )

        assert outbox_repo.find_halted() == []

    def test_an_abandoned_row_behind_an_earlier_failed_row_is_not_the_head(
        self, outbox_repo, now
    ):
        _insert(
            outbox_repo,
            _abandoned(_row("b", minute=1)),
            _failed(_row("a", minute=0), next_retry_at=now + timedelta(hours=1)),
        )

        assert outbox_repo.find_halted() == []

    def test_an_abandoned_row_behind_an_earlier_pending_row_is_not_the_head(
        self, outbox_repo
    ):
        _insert(outbox_repo, _abandoned(_row("b", minute=1)), _row("a", minute=0))

        assert outbox_repo.find_halted() == []

    def test_two_abandoned_rows_of_one_key_list_the_key_once(self, outbox_repo):
        _insert(
            outbox_repo,
            _abandoned(_row("b", minute=1)),
            _abandoned(_row("a", minute=0)),
        )

        assert _halted(outbox_repo) == [("default", "client-1", "primary", "a", 1)]

    def test_published_and_discarded_rows_are_not_waiting(self, outbox_repo, now):
        discarded = _abandoned(_row("d", minute=3))
        assert discarded.discard("skip", now=now) is True
        _insert(outbox_repo, _row("b", minute=1), discarded)
        _insert(outbox_repo, _abandoned(_row("a", minute=0)))
        _publish(outbox_repo, "b")
        _insert(outbox_repo, _row("c", minute=2))

        assert _halted(outbox_repo) == [("default", "client-1", "primary", "a", 1)]

    def test_an_abandoned_row_without_a_partition_key_is_not_listed(self, outbox_repo):
        _insert(
            outbox_repo,
            _abandoned(_row("no-key", minute=0, key=None)),
            _abandoned(_row("no-category", minute=0, category=None)),
        )

        assert outbox_repo.find_halted() == []

    def test_each_broker_is_its_own_group(self, outbox_repo):
        _insert(
            outbox_repo,
            _row("external-b", minute=2, broker="external"),
            _abandoned(_row("internal-a", minute=1)),
            _abandoned(_row("external-a", minute=0, broker="external")),
        )

        assert _halted(outbox_repo) == [
            ("external", "client-1", "primary", "external-a", 1),
            ("default", "client-1", "primary", "internal-a", 0),
        ]

    def test_lanes_enabled_list_each_lane_separately(self, test_domain, outbox_repo):
        test_domain.config["server"]["priority_lanes"] = {
            "enabled": True,
            "threshold": 5,
        }
        _insert(
            outbox_repo,
            _row("backfill-b", minute=2, priority=0),
            _abandoned(_row("primary-a", minute=1, priority=10)),
            _abandoned(_row("backfill-a", minute=0, priority=0)),
        )

        assert _halted(outbox_repo) == [
            ("default", "client-1", "backfill", "backfill-a", 1),
            ("default", "client-1", "primary", "primary-a", 0),
        ]

    def test_every_halted_key_is_listed_past_one_page(self, outbox_repo):
        keys = [f"client-{index:03}" for index in range(PAGE_SIZE + 5)]
        _insert(
            outbox_repo,
            *(_abandoned(_row(key, minute=0, key=key)) for key in keys),
        )

        assert sorted(key.partition_key for key in outbox_repo.find_halted()) == keys
