"""OutboxProcessor partition-per-key routing and the abandon backstop (#830).

Verifies ADR-0028 decisions 3, 4, and 8 on the publishing side:
- a row with a ``partition_key`` routes to ``{category}:{key}`` when the broker
  advertises ``STREAM_PARTITIONING``;
- the partition segment composes with the backfill lane as
  ``{category}:{key}:{backfill_suffix}``;
- under a non-partitioning broker the key is inert (routes to the base category);
- an invalid key that somehow reaches publish is abandoned, not retried.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.port.broker import BrokerCapabilities
from protean.server.outbox_processor import OutboxProcessor
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import Outbox, OutboxStatus


class RecordingBroker:
    """A fake broker that records what it was asked to publish (not a mock)."""

    def __init__(self, name: str, capabilities: BrokerCapabilities) -> None:
        self.name = name
        self._capabilities = capabilities
        self.published: list[tuple[str, dict]] = []

    def has_capability(self, capability: BrokerCapabilities) -> bool:
        return capability in self._capabilities

    def publish(self, stream: str, message: dict) -> str:
        self.published.append((stream, message))
        return "broker-msg-id"


class FakeEmitter:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, **kwargs) -> None:
        self.events.append(kwargs)


class FakeEngine:
    def __init__(self, domain: Domain) -> None:
        self.domain = domain
        self.loop = None
        self.emitter = FakeEmitter()


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
        processor = OutboxProcessor(FakeEngine(domain), "default", "default")
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
        processor = OutboxProcessor(FakeEngine(domain), "default", "default")
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
    async def test_no_partition_key_routes_to_base_category(self):
        domain = _make_domain("RouteBase")
        processor = OutboxProcessor(FakeEngine(domain), "default", "default")
        broker = RecordingBroker("default", BrokerCapabilities.STREAM_PARTITIONING)
        processor.broker = broker

        with domain.domain_context():
            await processor._publish_message(_outbox_row("m3", partition_key=None))

        assert broker.published[0][0] == "test::order"

    @pytest.mark.asyncio
    async def test_non_partitioning_broker_ignores_key(self):
        domain = _make_domain("RouteNoCap")
        processor = OutboxProcessor(FakeEngine(domain), "default", "default")
        # Broker lacks STREAM_PARTITIONING → key carried but routing is a no-op.
        broker = RecordingBroker("default", BrokerCapabilities.RELIABLE_MESSAGING)
        processor.broker = broker

        with domain.domain_context():
            await processor._publish_message(
                _outbox_row("m4", partition_key="client-1")
            )

        assert broker.published[0][0] == "test::order"


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

            processor = OutboxProcessor(FakeEngine(domain), "default", "default")
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
            # The backstop abandons instead of publishing.
            assert processor.broker.published == []
