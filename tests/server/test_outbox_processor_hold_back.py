"""OutboxProcessor publishes a partition key's rows in commit order and stops
at the first failure (ADR-0028, outbox-side ordering).

When a row of a group fails to publish, the later rows of that group in the
same batch are released back to ``PENDING`` unpublished, so they wait for it.
"""

from datetime import UTC, datetime, timedelta

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Integer, String
from protean.port.broker import BrokerCapabilities
from protean.server.outbox_processor import OutboxProcessor
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox, OutboxStatus

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

    def has_capability(self, capability: BrokerCapabilities) -> bool:
        return False

    def publish(self, stream: str, message: dict) -> str:
        message_id = message["metadata"]["headers"]["id"]
        if message_id in self.fail_ids:
            raise RuntimeError("broker down")
        self.published.append(message_id)
        return "broker-msg-id"


class FakeEmitter:
    def emit(self, **kwargs) -> None:
        pass


class FakeEngine:
    def __init__(self, domain) -> None:
        self.domain = domain
        self.loop = None
        self.emitter = FakeEmitter()


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


async def _processor(test_domain, fail_ids: set[str]) -> OutboxProcessor:
    processor = OutboxProcessor(
        FakeEngine(test_domain), "default", "default", worker_id="worker-1"
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
        self, test_domain, outbox_repo
    ):
        for label, minute in (("a", 0), ("b", 1), ("c", 2)):
            outbox_repo.add(_row(label, minute))
        processor = await _processor(test_domain, fail_ids={"a"})

        batch = await processor.get_next_batch_of_messages()
        assert [row.message_id for row in batch] == ["a", "b", "c"]

        successful = await processor.process_batch(batch)

        assert successful == 0
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
