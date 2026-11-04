"""A starting subscription claims the messages a stopped worker left unhandled.

A worker cut off mid-batch leaves its unacknowledged entries pending under its
own consumer name in the Redis consumer group. Every start uses a new consumer
name, so no later read returns those entries. On startup a subscription claims
the group's entries that have sat unacknowledged for ``reclaim_idle_seconds``,
handles them, and keeps each entry's earlier deliveries toward ``max_retries``.

Each test stands in for the stopped worker by reading entries under a consumer
name of its own and leaving them unacknowledged.
"""

import asyncio
import time
from uuid import uuid4

import pytest
import redis

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.domain import Domain
from protean.fields import Boolean, Identifier, String
from protean.server import Engine
from protean.server.subscription.broker_subscription import BrokerSubscription
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils.eventing import Message
from protean.utils.mixins import handle
from tests.shared import REDIS_URI

pytestmark = [pytest.mark.redis, pytest.mark.no_test_domain]

STOPPED_CONSUMER = "stopped-worker"
# Short enough for a test to wait out, long enough to tell a fresh entry apart.
RECLAIM_IDLE_SECONDS = 0.05

handled: list[str] = []


class Shipment(BaseAggregate):
    label = String()


class ShipmentBooked(BaseEvent):
    shipment_id = Identifier(identifier=True)
    label = String()
    fail = Boolean(default=False)


class ShipmentTracker(BaseEventHandler):
    @handle(ShipmentBooked)
    def track(self, event: ShipmentBooked) -> None:
        if event.fail:
            raise RuntimeError("intentional failure")
        handled.append(event.label)


class LabelPrinter(BaseSubscriber):
    def __call__(self, data: dict) -> None:
        handled.append(data["label"])


@pytest.fixture(autouse=True)
def _reset_handled():
    yield
    handled.clear()


def _domain(**server: object) -> Domain:
    domain = Domain(name="ReclaimTest")
    domain.config["brokers"]["default"] = {
        "provider": "redis",
        "URI": f"{REDIS_URI}/10",
    }
    domain.config["command_processing"] = "sync"
    domain.config["event_processing"] = "sync"
    domain.config["server"]["reclaim_idle_seconds"] = RECLAIM_IDLE_SECONDS
    domain.config["server"].update(server)
    domain.register(Shipment)
    domain.register(ShipmentBooked, part_of=Shipment)
    domain.register(ShipmentTracker, part_of=Shipment)
    domain.register(LabelPrinter, stream="labels")
    domain.init(traverse=False)
    return domain


@pytest.fixture
def domain():
    domain = _domain()
    with domain.domain_context():
        domain.brokers["default"]._data_reset()
        yield domain
        domain.brokers["default"]._data_reset()


@pytest.fixture
def lanes_domain():
    domain = _domain(priority_lanes={"enabled": True, "backfill_suffix": "backfill"})
    with domain.domain_context():
        domain.brokers["default"]._data_reset()
        yield domain
        domain.brokers["default"]._data_reset()


def _stream_subscription(domain: Domain, **kwargs: object) -> StreamSubscription:
    return StreamSubscription(
        engine=Engine(domain, test_mode=True),
        stream_category=Shipment.meta_.stream_category,
        handler=ShipmentTracker,
        retry_delay_seconds=0,
        **kwargs,
    )


def _publish(domain: Domain, stream: str, label: str, fail: bool = False) -> None:
    event = ShipmentBooked(shipment_id=str(uuid4()), label=label, fail=fail)
    domain.brokers["default"]._publish(
        stream, Message.from_domain_object(event).to_dict()
    )


def _leave_pending(domain: Domain, stream: str, group: str, count: int) -> None:
    """Read *count* entries as the stopped worker and never acknowledge them."""
    client = domain.brokers["default"].redis_instance
    client.xreadgroup(group, STOPPED_CONSUMER, {stream: ">"}, count=count)
    time.sleep(RECLAIM_IDLE_SECONDS * 2)


def _pending_by_consumer(domain: Domain, stream: str, group: str) -> dict[str, int]:
    client = domain.brokers["default"].redis_instance
    summary = client.xpending(stream, group)
    return {
        (c["name"].decode() if isinstance(c["name"], bytes) else c["name"]): int(
            c["pending"]
        )
        for c in summary["consumers"]
    }


async def _start(subscription: StreamSubscription | BrokerSubscription) -> None:
    await subscription.initialize()


async def _read_and_process(subscription: StreamSubscription) -> int:
    messages = await subscription.get_next_batch_of_messages()
    return await subscription.process_batch(messages)


class TestStreamSubscription:
    async def test_handles_what_a_stopped_worker_left_pending(self, domain):
        category = Shipment.meta_.stream_category
        first = _stream_subscription(domain)
        await _start(first)
        for label in ("a", "b", "c"):
            _publish(domain, category, label)
        _leave_pending(domain, category, first.consumer_group, 3)

        second = _stream_subscription(domain, messages_per_tick=10)
        await _start(second)
        processed = await _read_and_process(second)

        assert processed == 3
        assert handled == ["a", "b", "c"]
        assert _pending_by_consumer(domain, category, second.consumer_group) == {}

    async def test_leaves_entries_younger_than_the_threshold(self, domain):
        """Negative: a live consumer's fresh entries stay with it."""
        category = Shipment.meta_.stream_category
        domain.config["server"]["reclaim_idle_seconds"] = 60
        first = _stream_subscription(domain)
        await _start(first)
        _publish(domain, category, "a")
        _leave_pending(domain, category, first.consumer_group, 1)

        second = _stream_subscription(domain)
        await _start(second)

        assert second.retry_counts == {}
        assert _pending_by_consumer(domain, category, second.consumer_group) == {
            STOPPED_CONSUMER: 1
        }

    async def test_a_claimed_message_keeps_its_earlier_deliveries(self, domain):
        """One earlier delivery plus one failure here reaches max_retries=2,
        so the message goes to the dead-letter stream instead of a retry."""
        category = Shipment.meta_.stream_category
        first = _stream_subscription(domain, max_retries=2)
        await _start(first)
        _publish(domain, category, "poison", fail=True)
        _leave_pending(domain, category, first.consumer_group, 1)

        second = _stream_subscription(domain, max_retries=2)
        await _start(second)
        assert list(second.retry_counts.values()) == [1]

        await _read_and_process(second)

        client = domain.brokers["default"].redis_instance
        assert client.xlen(second.dlq_stream) == 1
        assert _pending_by_consumer(domain, category, second.consumer_group) == {}

    async def test_claims_on_the_backfill_stream_too(self, lanes_domain):
        first = _stream_subscription(lanes_domain)
        await _start(first)
        _publish(lanes_domain, first.backfill_stream, "late")
        _leave_pending(lanes_domain, first.backfill_stream, first.consumer_group, 1)

        second = _stream_subscription(lanes_domain)
        await _start(second)

        assert _pending_by_consumer(
            lanes_domain, second.backfill_stream, second.consumer_group
        ) == {second.consumer_name: 1}
        primary, backfill = await second._read_lanes_blocking()
        assert primary == []
        await second.process_batch(backfill, stream=second.backfill_stream)
        assert handled == ["late"]


class TestBrokerSubscription:
    async def test_handles_what_a_stopped_worker_left_pending(self, domain):
        broker = domain.brokers["default"]
        engine = Engine(domain, test_mode=True)
        first = BrokerSubscription(engine, broker, "labels", LabelPrinter)
        broker.publish("labels", {"label": "x"})
        broker.publish("labels", {"label": "y"})
        _leave_pending(domain, "labels", first.subscriber_name, 2)

        second = BrokerSubscription(engine, broker, "labels", LabelPrinter)
        await _start(second)
        messages = await second.get_next_batch_of_messages()
        await second.process_batch(messages)

        assert sorted(handled) == ["x", "y"]
        assert _pending_by_consumer(domain, "labels", second.subscriber_name) == {}


class TestBrokerReclaim:
    def test_pages_through_more_entries_than_one_claim_returns(self, domain):
        """The claim loop follows the cursor past the first page of entries."""
        broker = domain.brokers["default"]
        broker._ensure_group("group", "bulk")
        for i in range(250):
            broker.redis_instance.xadd("bulk", {"i": str(i)})
        _leave_pending(domain, "bulk", "group", 250)

        counts = broker._reclaim_idle_pending("bulk", "group", "new", 10)

        assert len(counts) == 250
        assert set(counts.values()) == {1}
        assert _pending_by_consumer(domain, "bulk", "group") == {"new": 250}

    def test_missing_group_claims_nothing(self, domain):
        broker = domain.brokers["default"]
        broker.redis_instance.xadd("orphan", {"i": "1"})

        assert broker._reclaim_idle_pending("orphan", "group", "new", 10) == {}

    def test_group_deleted_after_caching_claims_nothing_and_recreates_it(self, domain):
        """A group removed behind the broker's group cache makes the claim fail
        with NOGROUP. The claim returns nothing and creates the group again."""
        broker = domain.brokers["default"]
        broker._ensure_group("group", "dropped")
        broker.redis_instance.xadd("dropped", {"i": "1"})
        broker.redis_instance.xgroup_destroy("dropped", "group")

        assert broker._reclaim_idle_pending("dropped", "group", "new", 10) == {}
        groups = broker.redis_instance.xinfo_groups("dropped")
        assert [
            g["name"].decode() if isinstance(g["name"], bytes) else g["name"]
            for g in groups
        ] == ["group"]

    def test_other_claim_errors_are_raised(self, domain):
        """Negative: a claim error other than NOGROUP reaches the caller."""
        broker = domain.brokers["default"]
        broker.redis_instance.set("not-a-stream", "x")

        with pytest.raises(redis.ResponseError, match="WRONGTYPE"):
            broker._reclaim_idle_pending("not-a-stream", "group", "new", 10)

    def test_none_claims_into_the_brokers_own_consumer(self, domain):
        broker = domain.brokers["default"]
        broker._ensure_group("group", "own")
        broker.redis_instance.xadd("own", {"i": "1"})
        _leave_pending(domain, "own", "group", 1)

        assert len(broker._reclaim_idle_pending("own", "group", None, 10)) == 1
        assert _pending_by_consumer(domain, "own", "group") == {
            broker._consumer_name: 1
        }


async def test_claiming_first_lets_cleanup_remove_the_stopped_consumer(domain):
    """The stale-consumer cleanup skips a consumer with pending entries. The
    claim empties the stopped consumer first, so the same start removes it."""
    category = Shipment.meta_.stream_category
    first = _stream_subscription(domain)
    await _start(first)
    _publish(domain, category, "a")
    client = domain.brokers["default"].redis_instance
    client.xreadgroup(first.consumer_group, first.consumer_name, {category: ">"})
    await asyncio.sleep(RECLAIM_IDLE_SECONDS * 2)

    second = _stream_subscription(domain)
    await _start(second)

    consumers = client.xinfo_consumers(category, second.consumer_group)
    names = {
        c["name"].decode() if isinstance(c["name"], bytes) else c["name"]
        for c in consumers
    }
    assert first.consumer_name not in names
    assert _pending_by_consumer(domain, category, second.consumer_group) == {
        second.consumer_name: 1
    }
