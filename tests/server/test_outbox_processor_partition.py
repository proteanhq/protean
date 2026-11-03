"""OutboxProcessor partition-per-key routing and the abandon backstop (#830).

Verifies ADR-0028 decisions 3, 4, and 8 on the publishing side:
- a row with a ``partition_key`` routes to ``{category}:{key}`` when the broker
  advertises ``STREAM_PARTITIONING``;
- the partition segment composes with the backfill lane as
  ``{category}:{key}:{backfill_suffix}``;
- under a non-partitioning broker the key is inert (routes to the base category);
- an invalid key that somehow reaches publish is abandoned, not retried.
"""

import logging

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.port.broker import BrokerCapabilities
from protean.server import Engine
from protean.server.outbox_processor import OutboxProcessor
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox, OutboxStatus


class RecordingBroker:
    """A fake broker that records what it was asked to publish (not a mock).

    Only the Redis broker partitions streams, so this stands in for it.
    """

    def __init__(self, name: str, capabilities: BrokerCapabilities) -> None:
        self.name = name
        self._capabilities = capabilities
        self.published: list[tuple[str, dict]] = []
        self.recorded_partitions: list[tuple[str, str]] = []

    def has_capability(self, capability: BrokerCapabilities) -> bool:
        return capability in self._capabilities

    def publish(self, stream: str, message: dict) -> str:
        self.published.append((stream, message))
        return "broker-msg-id"

    def record_partition(self, category: str, key: str) -> None:
        if getattr(self, "raise_on_record", False):
            raise RuntimeError("index write boom")
        self.recorded_partitions.append((category, key))


class Order(BaseAggregate):
    client_id: String(max_length=50)


class OrderPlaced(BaseEvent):
    order_id: Identifier()
    client_id: String(max_length=50)


def _make_domain(name, lanes_enabled=False, threshold=0, backfill_suffix="backfill"):
    config = {
        "enable_outbox": True,
        "server": {
            "default_subscription_type": "stream",
            "priority_lanes": {
                "enabled": lanes_enabled,
                "threshold": threshold,
                "backfill_suffix": backfill_suffix,
            },
        },
    }
    domain = Domain(name=name, config=config)
    domain.register(Order)
    domain.register(OrderPlaced, part_of=Order)
    domain.init(traverse=False)
    return domain


def _outbox_row(msg_id, partition_key=None, priority=0, stream_category="test::order"):
    headers = MessageHeaders(id=msg_id, type="OrderPlaced", stream="test::order-1")
    metadata = Metadata(
        headers=headers, domain=DomainMeta(stream_category=stream_category)
    )
    return Outbox.create_message(
        message_id=msg_id,
        stream_name="test::order-1",
        message_type="OrderPlaced",
        data={"order_id": "o-1", "client_id": "client-1"},
        metadata=metadata,
        priority=priority,
        partition_key=partition_key,
    )


@pytest.mark.database
class TestPartitionRouting:
    @pytest.mark.asyncio
    async def test_partition_key_routes_to_partition_stream(self):
        domain = _make_domain("RoutePart")
        processor = OutboxProcessor(
            Engine(domain, test_mode=True), "default", "default"
        )
        broker = RecordingBroker("default", BrokerCapabilities.STREAM_PARTITIONING)
        processor.broker = broker

        with domain.domain_context():
            success, error = await processor._publish_message(
                _outbox_row("m1", partition_key="client-1")
            )

        assert success is True and error is None
        assert broker.published[0][0] == "test::order:client-1"

    @pytest.mark.asyncio
    async def test_partition_composes_with_backfill_lane(self):
        domain = _make_domain("RouteBackfill", lanes_enabled=True, threshold=0)
        processor = OutboxProcessor(
            Engine(domain, test_mode=True), "default", "default"
        )
        broker = RecordingBroker("default", BrokerCapabilities.STREAM_PARTITIONING)
        processor.broker = broker

        with domain.domain_context():
            # priority below the threshold routes to the backfill lane, after the
            # partition segment: {category}:{key}:{backfill_suffix}.
            await processor._publish_message(
                _outbox_row("m2", partition_key="client-1", priority=-50)
            )

        assert broker.published[0][0] == "test::order:client-1:backfill"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "partition_key, capability, is_external",
        [
            (None, BrokerCapabilities.STREAM_PARTITIONING, False),
            # Broker lacks STREAM_PARTITIONING: key carried but routing is a no-op.
            ("client-1", BrokerCapabilities.RELIABLE_MESSAGING, False),
            # Registration validates sequential_by against the internal outbox
            # broker only, so partition routing is internal-only. An external
            # processor, even on a partitioning broker, must publish to the base
            # category and not partition a stream no one opted into.
            ("client-1", BrokerCapabilities.STREAM_PARTITIONING, True),
        ],
        ids=["no_partition_key", "non_partitioning_broker", "external_processor"],
    )
    async def test_routes_to_base_category_without_an_index_write(
        self, partition_key, capability, is_external
    ):
        domain = _make_domain("RouteBase")
        processor = OutboxProcessor(
            Engine(domain, test_mode=True),
            "default",
            "default",
            is_external=is_external,
        )
        broker = RecordingBroker("default", capability)
        processor.broker = broker

        with domain.domain_context():
            await processor._publish_message(
                _outbox_row("m3", partition_key=partition_key)
            )

        assert broker.published[0][0] == "test::order"
        assert broker.recorded_partitions == []


@pytest.mark.database
class TestAbandonBackstop:
    @pytest.mark.asyncio
    async def test_invalid_key_is_abandoned_not_retried(self):
        domain = _make_domain("Abandon")
        with domain.domain_context():
            outbox_repo = domain._get_outbox_repo("default")

            # A corrupt/legacy row carrying an invalid key (bypasses UoW
            # validation by constructing the row directly).
            row = _outbox_row("bad-1", partition_key="has:colon")
            with UnitOfWork():
                outbox_repo.add(row)
            row_id = row.id

            processor = OutboxProcessor(
                Engine(domain, test_mode=True), "default", "default"
            )
            await processor.initialize()
            # Override with a partitioning broker so the backstop path engages.
            processor.broker = RecordingBroker(
                "default", BrokerCapabilities.STREAM_PARTITIONING
            )

            result = await processor._process_single_message(row)

            assert result is False
            refetched = outbox_repo.get(row_id)
            assert refetched.status == OutboxStatus.ABANDONED.value
            assert "Invalid partition key" in refetched.last_error["message"]
            assert refetched.last_error["reason"] == "Invalid partition key"
            # The backstop abandons instead of publishing.
            assert processor.broker.published == []

    @pytest.mark.asyncio
    async def test_empty_string_key_is_abandoned_not_published(self):
        # An empty-string key is as invalid as one with a colon
        # (``invalid_partition_key_reason`` rejects both), but it is also
        # falsy like the legitimate "no partition key" ``None`` value. The
        # backstop must still catch it rather than let it slip through as if
        # it were an unpartitioned row.
        domain = _make_domain("AbandonEmpty")
        with domain.domain_context():
            outbox_repo = domain._get_outbox_repo("default")

            row = _outbox_row("bad-empty", partition_key="")
            with UnitOfWork():
                outbox_repo.add(row)
            row_id = row.id

            processor = OutboxProcessor(
                Engine(domain, test_mode=True), "default", "default"
            )
            await processor.initialize()
            processor.broker = RecordingBroker(
                "default", BrokerCapabilities.STREAM_PARTITIONING
            )

            result = await processor._process_single_message(row)

            assert result is False
            refetched = outbox_repo.get(row_id)
            assert refetched.status == OutboxStatus.ABANDONED.value
            assert "Invalid partition key" in refetched.last_error["message"]
            assert processor.broker.published == []

    @pytest.mark.asyncio
    async def test_invalid_key_on_non_partitioning_broker_is_not_abandoned(self):
        # The backstop only engages when the broker actually partitions. Under a
        # non-partitioning broker the invalid key is inert, so the row must
        # publish to the base category and succeed, not be abandoned.
        domain = _make_domain("AbandonNoCap")
        with domain.domain_context():
            outbox_repo = domain._get_outbox_repo("default")

            row = _outbox_row("bad-2", partition_key="has:colon")
            with UnitOfWork():
                outbox_repo.add(row)
            row_id = row.id

            processor = OutboxProcessor(
                Engine(domain, test_mode=True), "default", "default"
            )
            await processor.initialize()
            broker = RecordingBroker("default", BrokerCapabilities.RELIABLE_MESSAGING)
            processor.broker = broker

            result = await processor._process_single_message(row)

            assert result is True
            refetched = outbox_repo.get(row_id)
            assert refetched.status == OutboxStatus.PUBLISHED.value
            # Key inert: published to the base category, not abandoned.
            assert broker.published[0][0] == "test::order"

    @pytest.mark.asyncio
    async def test_abandon_failure_returns_false_does_not_propagate(self, caplog):
        # If the abandon transaction blows up (row cleaned up between claim and
        # backstop, or an OCC race on a reclaimed row), the backstop must swallow
        # it and return False so one poisoned row cannot abort the rest of the
        # batch in process_batch. The row is never stored, so the abandon's
        # reload fails as it would for a row deleted after the claim.
        domain = _make_domain("AbandonRaises")

        with domain.domain_context():
            processor = OutboxProcessor(
                Engine(domain, test_mode=True), "default", "default"
            )
            await processor.initialize()
            processor.broker = RecordingBroker(
                "default", BrokerCapabilities.STREAM_PARTITIONING
            )

            row = _outbox_row("bad-3", partition_key="has:colon")
            # Must not raise out of the backstop.
            with caplog.at_level(
                logging.ERROR, logger="protean.server.outbox_processor"
            ):
                result = await processor._process_single_message(row)

            assert result is False
            assert any(
                r.getMessage() == "outbox.invalid_partition_key_abandon_failed"
                for r in caplog.records
            )
            # It never reached the publish path.
            assert processor.broker.published == []

    @pytest.mark.asyncio
    async def test_valid_key_on_partitioning_broker_publishes(self):
        # A valid key on a partitioning broker skips the backstop and publishes
        # to the partition stream through the full single-message path.
        domain = _make_domain("BackstopValid")
        with domain.domain_context():
            outbox_repo = domain._get_outbox_repo("default")

            row = _outbox_row("good-1", partition_key="client-1")
            with UnitOfWork():
                outbox_repo.add(row)
            row_id = row.id

            processor = OutboxProcessor(
                Engine(domain, test_mode=True), "default", "default"
            )
            await processor.initialize()
            broker = RecordingBroker("default", BrokerCapabilities.STREAM_PARTITIONING)
            processor.broker = broker

            result = await processor._process_single_message(row)

            assert result is True
            refetched = outbox_repo.get(row_id)
            assert refetched.status == OutboxStatus.PUBLISHED.value
            assert broker.published[0][0] == "test::order:client-1"


@pytest.mark.database
class TestPartitionIndexWrite:
    """The publisher records each partition key in the index (ADR-0028 #7).

    The partitioned consumer discovers partitions only from this index, so the
    publish path must write it. There is deliberately no per-process cache: the
    consumer reaps cold keys from the index, so a cache could skip re-adding a
    reaped-then-republished key and strand it. Every publish records (SADD is
    idempotent), and a failed record fails the publish so the row retries.
    """

    @pytest.mark.asyncio
    async def test_every_partitioned_publish_records_no_cache(self):
        # No per-process cache: each publish records its key, even a repeat.
        # Relying on SADD idempotency keeps a reaped-then-republished key from
        # being silently skipped (the strand bug a cache would reintroduce).
        domain = _make_domain("IdxNoCache")
        processor = OutboxProcessor(
            Engine(domain, test_mode=True), "default", "default"
        )
        broker = RecordingBroker("default", BrokerCapabilities.STREAM_PARTITIONING)
        processor.broker = broker

        with domain.domain_context():
            await processor._publish_message(_outbox_row("m1", partition_key="c1"))
            await processor._publish_message(_outbox_row("m2", partition_key="c1"))
            await processor._publish_message(_outbox_row("m3", partition_key="c2"))

        assert broker.recorded_partitions == [
            ("test::order", "c1"),
            ("test::order", "c1"),
            ("test::order", "c2"),
        ]

    @pytest.mark.asyncio
    async def test_index_write_failure_fails_publish(self):
        # A failed index write must fail the whole publish so the row stays
        # PENDING and retries — never leave a message on a partition stream that
        # is absent from the index (the consumer would never discover it).
        domain = _make_domain("IdxFail")
        processor = OutboxProcessor(
            Engine(domain, test_mode=True), "default", "default"
        )
        broker = RecordingBroker("default", BrokerCapabilities.STREAM_PARTITIONING)
        broker.raise_on_record = True
        processor.broker = broker

        with domain.domain_context():
            success, error = await processor._publish_message(
                _outbox_row("m1", partition_key="client-1")
            )

        assert success is False
        assert error is not None
        # The message was NOT published to the partition stream.
        assert broker.published == []
