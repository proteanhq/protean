"""OutboxProcessor publishes a partition key's rows in commit order and stops
at the first failure (ADR-0028, outbox-side ordering).

When a row of a group fails to publish, the later rows of that group in the
same batch are released back to ``PENDING`` unpublished, so they wait for it.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Integer, String
from protean.port.broker import BrokerCapabilities
from protean.server import Engine
from protean.server.outbox_processor import (
    OutboxProcessor,
    _abandon_invalid_partition_key,
    _in_group_commit_order,
    _save_processing_error,
)
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils import outbox_trace
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox, OutboxLanes, OutboxStatus
from protean.utils.query import Q
from tests.shared import FrozenClock

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)
CATEGORY = "test::counter"


class Counter(BaseAggregate):
    name: String(max_length=50, required=True)


class Bumped(BaseEvent):
    counter_id: String(required=True)
    count: Integer(required=True)


class FailingBroker:
    """A fake broker that records published message ids and fails the ones
    it is told to (not a mock)."""

    name = "default"

    def __init__(self, fail_ids: set[str]) -> None:
        self.fail_ids = fail_ids
        self.published: list[str] = []
        self.streams: list[str] = []

    capabilities = BrokerCapabilities.BASIC_PUBSUB

    def publish(self, stream: str, message: dict) -> str:
        message_id = message["metadata"]["headers"]["id"]
        if message_id in self.fail_ids:
            raise RuntimeError("broker down")
        self.published.append(message_id)
        self.streams.append(stream)
        return "broker-msg-id"


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


async def _processor(
    test_domain, fail_ids: set[str], engine: Engine | None = None
) -> OutboxProcessor:
    processor = OutboxProcessor(
        engine or Engine(test_domain, test_mode=True),
        "default",
        "default",
        worker_id="worker-1",
    )
    await processor.initialize()
    processor.broker = FailingBroker(fail_ids)
    return processor


def _row(label: str, minute: int, key: str = "client-1", priority: int = 0) -> Outbox:
    metadata = Metadata(
        headers=MessageHeaders(id=label, type="Test.Bumped.v1", stream=CATEGORY),
        domain=DomainMeta(stream_category=CATEGORY),
    )
    row = Outbox.create_message(
        message_id=label,
        stream_name=f"{CATEGORY}-1",
        message_type="Test.Bumped.v1",
        data={"counter_id": "1", "count": minute},
        metadata=metadata,
        priority=priority,
        sequence_number=minute,
        partition_key=key,
        stream_category=CATEGORY,
    )
    row.created_at = BASE_TIME + timedelta(minutes=minute)
    return row


def _stored(outbox_repo, label: str) -> Outbox:
    [row] = outbox_repo.find_all_by_message_id(label)
    return row


@pytest.mark.database
class TestProcessBatchHoldsBackAfterAFailure:
    @pytest.mark.asyncio
    async def test_later_rows_of_the_key_are_released_unpublished(
        self, test_domain, outbox_repo, caplog
    ):
        for label, minute in (("a", 0), ("b", 1), ("c", 2)):
            outbox_repo.add(_row(label, minute))
        processor = await _processor(test_domain, fail_ids={"a"})

        batch = await processor.get_next_batch_of_messages()
        assert [row.message_id for row in batch] == ["a", "b", "c"]

        with caplog.at_level(logging.INFO, logger="protean.server.outbox_processor"):
            successful = await processor.process_batch(batch)

        assert successful == 0
        [record] = [
            r for r in caplog.records if r.getMessage() == "outbox.batch_completed"
        ]
        assert (record.total, record.successful, record.failed, record.released) == (
            3,
            0,
            1,
            2,
        )
        assert processor.broker.published == []
        assert _stored(outbox_repo, "a").status == OutboxStatus.FAILED.value
        for label in ("b", "c"):
            row = _stored(outbox_repo, label)
            assert row.status == OutboxStatus.PENDING.value
            assert row.locked_by is None
            assert row.locked_until is None
            assert row.retry_count == 0
            assert row.next_retry_at is None

    @pytest.mark.asyncio
    async def test_another_key_in_the_batch_still_publishes(
        self, test_domain, outbox_repo
    ):
        outbox_repo.add(_row("k1-a", 0))
        outbox_repo.add(_row("k1-b", 1))
        outbox_repo.add(_row("k2-a", 2, key="client-2"))
        processor = await _processor(test_domain, fail_ids={"k1-a"})

        batch = await processor.get_next_batch_of_messages()
        successful = await processor.process_batch(batch)

        assert successful == 1
        assert processor.broker.published == ["k2-a"]
        assert _stored(outbox_repo, "k1-b").status == OutboxStatus.PENDING.value
        assert _stored(outbox_repo, "k2-a").status == OutboxStatus.PUBLISHED.value

    @pytest.mark.asyncio
    async def test_rows_of_one_key_publish_in_commit_order_whatever_their_priority(
        self, test_domain, outbox_repo
    ):
        # The claim never returns this order, so the batch is built by hand.
        batch = []
        for label, minute, priority in (("late-high", 1, 10), ("early-low", 0, 0)):
            row = _row(label, minute, priority=priority)
            row.start_processing("worker-1")
            outbox_repo.add(row)
            batch.append(row)
        processor = await _processor(test_domain, fail_ids=set())

        successful = await processor.process_batch(batch)

        assert successful == 2
        assert processor.broker.published == ["early-low", "late-high"]

    @pytest.mark.asyncio
    async def test_a_row_this_worker_no_longer_holds_is_not_released(
        self, test_domain, outbox_repo
    ):
        outbox_repo.add(_row("a", 0))
        outbox_repo.add(_row("b", 1))
        processor = await _processor(test_domain, fail_ids={"a"})
        batch = await processor.get_next_batch_of_messages()

        # Another worker took "b" over after this worker's lock expired.
        taken = _stored(outbox_repo, "b")
        taken.locked_by = "worker-2"
        outbox_repo.add(taken)

        successful = await processor.process_batch(batch)

        assert successful == 0
        row = _stored(outbox_repo, "b")
        assert row.status == OutboxStatus.PROCESSING.value
        assert row.locked_by == "worker-2"

    @pytest.mark.asyncio
    async def test_a_failed_release_is_logged_and_the_batch_goes_on(
        self, test_domain, outbox_repo, caplog
    ):
        for label, minute in (("a", 0), ("b", 1), ("c", 2)):
            outbox_repo.add(_row(label, minute))
        processor = await _processor(test_domain, fail_ids={"a"})
        batch = await processor.get_next_batch_of_messages()
        assert [row.message_id for row in batch] == ["a", "b", "c"]

        # "b" is gone when the worker tries to release it, so the release fails.
        outbox_repo._dao.delete(_stored(outbox_repo, "b"))

        with caplog.at_level(logging.INFO, logger="protean.server.outbox_processor"):
            successful = await processor.process_batch(batch)

        assert successful == 0
        [failure] = [
            r for r in caplog.records if r.getMessage() == "outbox.release_failed"
        ]
        assert failure.message_id == "b"
        [record] = [
            r for r in caplog.records if r.getMessage() == "outbox.batch_completed"
        ]
        assert record.released == 1
        assert _stored(outbox_repo, "c").status == OutboxStatus.PENDING.value


class TestGroupCommitOrder:
    def test_rows_that_tie_on_commit_order_keep_the_claim_order(self, test_domain):
        # Integer identities: the store sorts 2 before 10, a string sort would
        # put "10" first.
        batch = []
        for identifier in ("2", "10"):
            row = _row(f"row-{identifier}", 0)
            batch.append(Outbox(**{**row.to_dict(), "id": identifier}))

        ordered = _in_group_commit_order(
            batch, OutboxLanes.from_config(test_domain.config)
        )

        assert [row.id for row in ordered] == ["2", "10"]


@pytest.mark.database
class TestProcessBatchWithPriorityLanes:
    @pytest.fixture(autouse=True)
    def enable_lanes(self, test_domain):
        test_domain.config["server"]["priority_lanes"] = {
            "enabled": True,
            "threshold": 5,
        }

    @pytest.mark.asyncio
    async def test_a_failed_backfill_row_does_not_hold_a_primary_row_of_its_key(
        self, test_domain, outbox_repo
    ):
        outbox_repo.add(_row("backfill", 0, priority=0))
        outbox_repo.add(_row("primary", 1, priority=10))
        processor = await _processor(test_domain, fail_ids={"backfill"})

        batch = await processor.get_next_batch_of_messages()
        assert sorted(row.message_id for row in batch) == ["backfill", "primary"]
        successful = await processor.process_batch(batch)

        assert successful == 1
        assert processor.broker.published == ["primary"]
        assert _stored(outbox_repo, "backfill").status == OutboxStatus.FAILED.value

    @pytest.mark.asyncio
    async def test_routing_uses_the_lanes_the_consumers_started_with(
        self, test_domain, outbox_repo
    ):
        test_domain.config["server"]["priority_lanes"] = {"enabled": False}
        engine = Engine(test_domain, test_mode=True)
        consumer = StreamSubscription(engine, CATEGORY, Counter)
        processor = await _processor(test_domain, fail_ids=set(), engine=engine)
        # Lanes turn on after startup. The running consumer still reads only
        # the primary stream, so the row must go there.
        test_domain.config["server"]["priority_lanes"] = {
            "enabled": True,
            "threshold": 5,
        }
        outbox_repo.add(_row("low", 0, priority=0))

        batch = await processor.get_next_batch_of_messages()
        assert [row.message_id for row in batch] == ["low"]
        await processor.process_batch(batch)

        assert consumer._lanes_enabled is False
        assert processor.broker.streams == [consumer.stream_category]

    @pytest.mark.asyncio
    async def test_routing_keeps_the_backfill_lane_the_consumers_started_with(
        self, test_domain, outbox_repo
    ):
        engine = Engine(test_domain, test_mode=True)
        consumer = StreamSubscription(engine, CATEGORY, Counter)
        processor = await _processor(test_domain, fail_ids=set(), engine=engine)
        test_domain.config["server"]["priority_lanes"] = {"enabled": False}
        outbox_repo.add(_row("low", 0, priority=0))

        batch = await processor.get_next_batch_of_messages()
        await processor.process_batch(batch)

        assert consumer._lanes_enabled is True
        assert processor.broker.streams == [consumer.backfill_stream]

    @pytest.mark.asyncio
    async def test_the_claim_groups_by_the_lanes_the_processor_started_with(
        self, test_domain, outbox_repo
    ):
        test_domain.config["server"]["priority_lanes"] = {"enabled": False}
        processor = await _processor(test_domain, fail_ids={"low"})
        # Under the new config "low" and "high" would sit in different lanes.
        # The processor still routes both to one stream, so "high" waits.
        test_domain.config["server"]["priority_lanes"] = {
            "enabled": True,
            "threshold": 5,
        }
        outbox_repo.add(_row("low", 0, priority=0))
        outbox_repo.add(_row("high", 1, priority=10))

        batch = await processor.get_next_batch_of_messages()
        await processor.process_batch(batch)

        assert processor.broker.published == []
        assert _stored(outbox_repo, "high").status == OutboxStatus.PENDING.value
        assert (await processor.get_next_batch_of_messages()) == []


@pytest.mark.database
@pytest.mark.asyncio
async def test_initialize_logs_the_adapter_class_of_the_selected_broker(
    test_domain, caplog
):
    processor = OutboxProcessor(
        Engine(test_domain, test_mode=True), "default", "default", worker_id="w-1"
    )

    with caplog.at_level(logging.DEBUG, logger="protean.server.outbox_processor"):
        await processor.initialize()

    [record] = [r for r in caplog.records if r.getMessage() == "outbox.broker_selected"]
    assert record.broker == "InlineBroker"


# A worker whose lock expired mid-batch must not release, fail or abandon a
# row another worker claimed since. Each claim advances the row's version, so
# the stale worker's guarded write sees the newer claim and is refused.

LOCK_EXPIRED = timedelta(minutes=10)
TAKEN_OVER = "outbox.message_already_claimed"


async def _engine_processor(
    test_domain, fail_ids: set[str], worker_id: str | None = None
) -> OutboxProcessor:
    """A processor built as the engine builds one: with no ``worker_id``
    unless one is given."""
    processor = OutboxProcessor(
        Engine(test_domain, test_mode=True),
        "default",
        "default",
        worker_id=worker_id,
    )
    await processor.initialize()
    processor.broker = FailingBroker(fail_ids)
    return processor


@pytest.fixture
def clock(test_domain):
    test_domain.clock = FrozenClock(BASE_TIME + timedelta(hours=1))
    return test_domain.clock


def _claim_state(outbox_repo, label: str) -> tuple:
    row = _stored(outbox_repo, label)
    return (row.status, row.locked_by, row.locked_until, row._version)


def _taken_over_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == TAKEN_OVER]


def _assert_refused_once_per_row(caplog, labels: list[str]) -> None:
    refusals = _taken_over_records(caplog)
    assert sorted(r.message_id for r in refusals) == sorted(labels)
    assert all(r.levelno == logging.WARNING for r in refusals)
    # The failed publish logs its own traceback before any write is tried.
    tracebacks = [
        r
        for r in caplog.records
        if r.name == "protean.server.outbox_processor"
        and r.exc_info
        and r.getMessage() != "outbox.broker_publish_failed"
    ]
    assert tracebacks == []


def _marks(events: list[dict]) -> list[dict]:
    return [event for event in events if event["action"] == "mark"]


async def _fail_the_publish(processor: OutboxProcessor, message: Outbox) -> None:
    processor.broker.fail_ids.add(message.message_id)
    await processor.process_batch([message])


async def _fail_unexpectedly(processor: OutboxProcessor, message: Outbox) -> None:
    _save_processing_error(
        processor, processor.outbox_repo, message, RuntimeError("unexpected")
    )


async def _abandon_for_its_key(processor: OutboxProcessor, message: Outbox) -> None:
    processor.broker.capabilities = BrokerCapabilities.STREAM_PARTITIONING
    message.partition_key = "dlq"
    rejected = _abandon_invalid_partition_key(processor, processor.outbox_repo, message)
    assert rejected is True
    assert processor.broker.published == []


WRITES = [
    pytest.param(_fail_the_publish, OutboxStatus.FAILED, id="publish-failed"),
    pytest.param(_fail_unexpectedly, OutboxStatus.FAILED, id="processing-error"),
    pytest.param(_abandon_for_its_key, OutboxStatus.ABANDONED, id="abandon"),
]


@pytest.mark.database
class TestAStaleWorkerLeavesARowAnotherWorkerClaimed:
    @pytest.mark.asyncio
    async def test_the_failure_and_the_release_are_both_refused(
        self, test_domain, outbox_repo, clock, caplog
    ):
        outbox_repo.add(_row("a", 0))
        outbox_repo.add(_row("b", 1))
        stale = await _engine_processor(test_domain, fail_ids={"a"})
        current = await _engine_processor(test_domain, fail_ids=set())
        assert stale.worker_id == current.worker_id

        batch = await stale.get_next_batch_of_messages()
        assert [row.message_id for row in batch] == ["a", "b"]
        clock.advance(LOCK_EXPIRED)
        taken = await current.get_next_batch_of_messages()
        assert [row.message_id for row in taken] == ["a", "b"]
        claimed = {label: _claim_state(outbox_repo, label) for label in ("a", "b")}

        with (
            outbox_trace.capture() as events,
            caplog.at_level(logging.INFO, logger="protean.server.outbox_processor"),
        ):
            successful = await stale.process_batch(batch)

        assert successful == 0
        for label in ("a", "b"):
            assert _claim_state(outbox_repo, label) == claimed[label]
            assert claimed[label][0] == OutboxStatus.PROCESSING.value
        [record] = [
            r for r in caplog.records if r.getMessage() == "outbox.batch_completed"
        ]
        assert (record.successful, record.released, record.failed) == (0, 0, 2)
        _assert_refused_once_per_row(caplog, ["a", "b"])
        assert _marks(events) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("write, status", WRITES)
    async def test_a_write_on_a_row_another_worker_claimed_changes_nothing(
        self, test_domain, outbox_repo, clock, caplog, write, status
    ):
        outbox_repo.add(_row("b", 0))
        stale = await _engine_processor(test_domain, fail_ids=set())
        current = await _engine_processor(test_domain, fail_ids=set())
        [message] = await stale.get_next_batch_of_messages()
        clock.advance(LOCK_EXPIRED)
        assert len(await current.get_next_batch_of_messages()) == 1
        claimed = _claim_state(outbox_repo, "b")

        with (
            outbox_trace.capture() as events,
            caplog.at_level(logging.INFO, logger="protean.server.outbox_processor"),
        ):
            await write(stale, message)

        assert _claim_state(outbox_repo, "b") == claimed
        _assert_refused_once_per_row(caplog, ["b"])
        assert _marks(events) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("write, status", WRITES)
    async def test_a_row_this_worker_still_holds_gets_the_write(
        self, test_domain, outbox_repo, clock, caplog, write, status
    ):
        outbox_repo.add(_row("b", 0))
        processor = await _engine_processor(test_domain, fail_ids=set())
        [message] = await processor.get_next_batch_of_messages()

        with caplog.at_level(logging.INFO, logger="protean.server.outbox_processor"):
            await write(processor, message)

        row = _stored(outbox_repo, "b")
        assert row.status == status.value
        assert row.locked_by is None
        assert _taken_over_records(caplog) == []

    @pytest.mark.asyncio
    async def test_a_row_this_worker_still_holds_is_released(
        self, test_domain, outbox_repo, clock, caplog
    ):
        outbox_repo.add(_row("a", 0))
        outbox_repo.add(_row("b", 1))
        processor = await _engine_processor(test_domain, fail_ids={"a"})
        batch = await processor.get_next_batch_of_messages()

        with caplog.at_level(logging.INFO, logger="protean.server.outbox_processor"):
            await processor.process_batch(batch)

        assert _stored(outbox_repo, "b").status == OutboxStatus.PENDING.value
        assert _taken_over_records(caplog) == []

    @pytest.mark.asyncio
    async def test_a_row_a_stale_worker_published_stays_published(
        self, test_domain, outbox_repo, clock, caplog
    ):
        outbox_repo.add(_row("b", 0))
        stale = await _engine_processor(test_domain, fail_ids=set())
        current = await _engine_processor(test_domain, fail_ids={"b"})
        stale_batch = await stale.get_next_batch_of_messages()
        clock.advance(LOCK_EXPIRED)
        current_batch = await current.get_next_batch_of_messages()
        assert len(current_batch) == 1

        assert await stale.process_batch(stale_batch) == 1
        assert _stored(outbox_repo, "b").status == OutboxStatus.PUBLISHED.value

        with caplog.at_level(logging.INFO, logger="protean.server.outbox_processor"):
            assert await current.process_batch(current_batch) == 0

        assert _stored(outbox_repo, "b").status == OutboxStatus.PUBLISHED.value
        _assert_refused_once_per_row(caplog, ["b"])


def _claim_while_reading(
    test_domain, processor: OutboxProcessor, label: str, claim: Callable[[], None]
) -> None:
    """Make ``processor``'s next read of row ``label`` run ``claim`` on another
    thread after the read and before the row is returned."""
    repo = processor.outbox_repo
    get = repo.get
    row_id = _stored(repo, label).id

    def get_then_claim(identifier):
        row = get(identifier)
        if identifier == row_id:

            def in_context() -> None:
                with test_domain.domain_context():
                    claim()

            thread = threading.Thread(target=in_context)
            thread.start()
            thread.join(timeout=10)
            assert not thread.is_alive()
        return row

    repo.get = get_then_claim


def _claim_by(test_domain, label: str, worker_id: str) -> Callable[[], None]:
    """A claim of row ``label`` by ``worker_id`` that ignores hold-back."""

    def claim() -> None:
        repo = test_domain._get_outbox_repo("default")
        now = test_domain.clock.now()
        claimed = repo._dao.claim(
            repo._eligibility_criteria(now, None) & Q(message_id=label),
            {
                "status": OutboxStatus.PROCESSING.value,
                "locked_by": worker_id,
                "locked_until": now + timedelta(minutes=5),
            },
            limit=1,
            hold_back=None,
        )
        assert len(claimed) == 1

    return claim


class TestAClaimBetweenTheReadAndTheSave:
    """The memory provider runs the other worker's claim between the stale
    worker's read of the row and its save."""

    @pytest.mark.asyncio
    async def test_the_release_is_refused(
        self, test_domain, outbox_repo, clock, caplog
    ):
        outbox_repo.add(_row("a", 0))
        outbox_repo.add(_row("b", 1))
        stale = await _engine_processor(test_domain, {"a"}, worker_id="worker-a")
        batch = await stale.get_next_batch_of_messages()
        assert [row.message_id for row in batch] == ["a", "b"]
        clock.advance(LOCK_EXPIRED)
        _claim_while_reading(
            test_domain, stale, "b", _claim_by(test_domain, "b", "worker-b")
        )

        with (
            outbox_trace.capture() as events,
            caplog.at_level(logging.INFO, logger="protean.server.outbox_processor"),
        ):
            await stale.process_batch(batch)

        assert _stored(outbox_repo, "a").status == OutboxStatus.FAILED.value
        row = _stored(outbox_repo, "b")
        assert (row.status, row.locked_by) == (
            OutboxStatus.PROCESSING.value,
            "worker-b",
        )
        assert row._version == batch[1]._version + 1
        _assert_refused_once_per_row(caplog, ["b"])
        assert [e["message"] for e in _marks(events)] == [str(batch[0].id)]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("publishes", [False, True], ids=["failed", "published"])
    async def test_the_outcome_is_refused(
        self, test_domain, outbox_repo, clock, caplog, publishes
    ):
        outbox_repo.add(_row("b", 0))
        fail_ids = set() if publishes else {"b"}
        stale = await _engine_processor(test_domain, fail_ids, worker_id="worker-a")
        [message] = await stale.get_next_batch_of_messages()
        clock.advance(LOCK_EXPIRED)
        _claim_while_reading(
            test_domain, stale, "b", _claim_by(test_domain, "b", "worker-b")
        )

        with (
            outbox_trace.capture() as events,
            caplog.at_level(logging.INFO, logger="protean.server.outbox_processor"),
        ):
            assert await stale.process_batch([message]) == 0

        row = _stored(outbox_repo, "b")
        assert (row.status, row.locked_by) == (
            OutboxStatus.PROCESSING.value,
            "worker-b",
        )
        assert row._version == message._version + 1
        _assert_refused_once_per_row(caplog, ["b"])
        assert not any(
            r.getMessage() == "outbox.processing_error" for r in caplog.records
        )
        assert _marks(events) == []
