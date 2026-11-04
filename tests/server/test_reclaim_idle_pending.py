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
import logging
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
from protean.server.subscription.profiles import CircuitBreakerState
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils.eventing import Message
from protean.utils.mixins import handle
from tests.server.test_trace_correlation import _attach_recording_redis
from tests.shared import REDIS_URI

pytestmark = [pytest.mark.redis, pytest.mark.no_test_domain]

STOPPED_CONSUMER = "stopped-worker"
# Short enough for a test to wait out, long enough to tell a fresh entry apart.
RECLAIM_IDLE_SECONDS = 0.05

handled: list[str] = []
# Labels the handler fails on while they are in this set.
failing_labels: set[str] = set()


class Shipment(BaseAggregate):
    label = String()


class ShipmentBooked(BaseEvent):
    shipment_id = Identifier(identifier=True)
    label = String()
    fail = Boolean(default=False)


class ShipmentTracker(BaseEventHandler):
    @handle(ShipmentBooked)
    def track(self, event: ShipmentBooked) -> None:
        if event.fail or event.label in failing_labels:
            raise RuntimeError("intentional failure")
        handled.append(event.label)


class LabelPrinter(BaseSubscriber):
    def __call__(self, data: dict) -> None:
        if data["label"] in failing_labels:
            raise RuntimeError("intentional failure")
        handled.append(data["label"])


@pytest.fixture(autouse=True)
def _reset_handled():
    yield
    handled.clear()
    failing_labels.clear()


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
    return _pending_on(domain.brokers["default"].redis_instance, stream, group)


def _pending_on(client: redis.Redis, stream: str, group: str) -> dict[str, int]:
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


class TestStoppedWorkerStates:
    """A message a stopped worker still meant to retry is claimed like any other."""

    async def test_claims_a_message_waiting_for_its_retry(self, domain):
        category = Shipment.meta_.stream_category
        first = _stream_subscription(domain, max_retries=3)
        await _start(first)
        _publish(domain, category, "flaky")
        failing_labels.add("flaky")
        await _read_and_process(first)
        assert list(first.retry_counts.values()) == [1]
        assert _pending_by_consumer(domain, category, first.consumer_group) == {
            first.consumer_name: 1
        }
        await asyncio.sleep(RECLAIM_IDLE_SECONDS * 2)
        failing_labels.clear()

        second = _stream_subscription(domain, max_retries=3)
        await _start(second)
        processed = await _read_and_process(second)

        assert processed == 1
        assert handled == ["flaky"]
        assert _pending_by_consumer(domain, category, second.consumer_group) == {}

    async def test_restarts_count_only_the_failed_attempts(self, domain):
        """Three workers each fail the message once and stop. With
        max_retries=4 the third failure is still a retry, not a dead letter."""
        category = Shipment.meta_.stream_category
        _publish(domain, category, "flaky")
        failing_labels.add("flaky")
        for attempt in (1, 2, 3):
            worker = _stream_subscription(domain, max_retries=4)
            await _start(worker)
            await _read_and_process(worker)
            assert list(worker.retry_counts.values()) == [attempt]
            await asyncio.sleep(RECLAIM_IDLE_SECONDS * 2)

        client = domain.brokers["default"].redis_instance
        assert client.xlen(worker.dlq_stream) == 0

    async def test_claims_a_message_held_by_an_open_circuit_breaker(self, domain):
        category = Shipment.meta_.stream_category
        first = _stream_subscription(domain, circuit_breaker_threshold=1)
        await _start(first)
        _publish(domain, category, "held")
        failing_labels.add("held")
        await _read_and_process(first)
        assert first.circuit_state == CircuitBreakerState.OPEN
        assert _pending_by_consumer(domain, category, first.consumer_group) == {
            first.consumer_name: 1
        }
        await asyncio.sleep(RECLAIM_IDLE_SECONDS * 2)
        failing_labels.clear()

        second = _stream_subscription(domain, circuit_breaker_threshold=1)
        await _start(second)
        processed = await _read_and_process(second)

        assert processed == 1
        assert handled == ["held"]
        assert _pending_by_consumer(domain, category, second.consumer_group) == {}


def _pause_handling(subscription: StreamSubscription, pause: dict[str, float]):
    """Make the engine wait *pause[label]* seconds after handling that label.

    A negative pause holds the batch until it is cancelled.
    """
    engine = subscription.engine
    handle_message = engine.handle_message

    async def handle_then_pause(handler, message, **kwargs):
        result = await handle_message(handler, message, **kwargs)
        wait = pause.get(message.data["label"])
        if wait is not None and wait < 0:
            await asyncio.Event().wait()
        elif wait is not None:
            await asyncio.sleep(wait)
        return result

    engine.handle_message = handle_then_pause  # type: ignore[method-assign]


class TestShutdownMidBatch:
    """A shutdown that starts mid-batch on a Redis stream subscription."""

    async def test_batch_that_finishes_in_the_drain_window_is_all_acked(
        self, domain, caplog
    ):
        category = Shipment.meta_.stream_category
        domain.config["server"]["drain_timeout"] = 5
        sub = _stream_subscription(domain, messages_per_tick=10)
        await _start(sub)
        for label in ("a", "b", "c"):
            _publish(domain, category, label)
        _pause_handling(sub, {"a": 0.05})
        # Shutdown closes the broker's connection.
        client = domain.brokers["default"].redis_instance

        messages = await sub.get_next_batch_of_messages()
        assert len(messages) == 3
        batch = asyncio.ensure_future(sub.process_batch(messages))
        await asyncio.sleep(0.01)
        with caplog.at_level(logging.WARNING):
            await sub.engine.shutdown()

        assert batch.result() == 3
        assert handled == ["a", "b", "c"]
        assert _pending_on(client, category, sub.consumer_group) == {}
        assert client.xlen(sub.dlq_stream) == 0
        assert not [r for r in caplog.records if "Failed" in r.getMessage()]

    async def test_drain_timeout_leaves_the_rest_pending_without_failing_it(
        self, domain
    ):
        category = Shipment.meta_.stream_category
        domain.config["server"]["drain_timeout"] = 0.1
        sub = _stream_subscription(
            domain, messages_per_tick=10, circuit_breaker_threshold=1
        )
        sub.retry_delay_seconds = 5
        await _start(sub)
        for label in ("a", "b", "c"):
            _publish(domain, category, label)
        traces = _attach_recording_redis(sub.engine.emitter)
        _pause_handling(sub, {"a": 0.05, "b": -1})
        # Shutdown closes the broker's connection.
        client = domain.brokers["default"].redis_instance

        messages = await sub.get_next_batch_of_messages()
        batch = asyncio.ensure_future(sub.process_batch(messages))
        await asyncio.sleep(0.01)
        started = time.monotonic()
        await sub.engine.shutdown()

        assert batch.cancelled()
        assert time.monotonic() - started < 2
        # "a" was acked; "b" was handled but cancelled before its ack, and
        # "c" was never reached. Both stay pending for a later start to claim.
        assert handled == ["a", "b"]
        assert _pending_on(client, category, sub.consumer_group) == {
            sub.consumer_name: 2
        }
        assert sub.retry_counts == {}
        assert sub.consecutive_handler_failures == 0
        assert sub.circuit_state == CircuitBreakerState.CLOSED
        assert [t for t in traces.traces() if t["event"] == "message.nacked"] == []


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

    async def test_restart_counts_only_the_failed_attempts(self, domain):
        """A lone message fails once, then the worker stops. A read that
        returns fewer entries than asked for must not deliver the same entry
        twice, or the restarted worker counts two failed attempts and the
        second failure dead-letters the message with max_retries=3."""
        broker = domain.brokers["default"]
        engine = Engine(domain, test_mode=True)
        broker.publish("labels", {"label": "flaky"})
        failing_labels.add("flaky")
        first = BrokerSubscription(
            engine, broker, "labels", LabelPrinter, max_retries=3, retry_delay_seconds=0
        )
        await first.process_batch(await first.get_next_batch_of_messages())
        assert list(first.retry_counts.values()) == [1]

        # A restarted process reads under a new consumer name.
        broker._consumer_name = "restarted-worker"
        await asyncio.sleep(RECLAIM_IDLE_SECONDS * 2)
        second = BrokerSubscription(
            engine, broker, "labels", LabelPrinter, max_retries=3, retry_delay_seconds=0
        )
        await _start(second)
        assert list(second.retry_counts.values()) == [1]
        await second.process_batch(await second.get_next_batch_of_messages())

        assert list(second.retry_counts.values()) == [2]
        assert broker.redis_instance.xlen(second.dlq_stream) == 0


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

    def test_a_claim_does_not_count_as_a_delivery(self, domain):
        """A worker that claims and stops before reading adds no delivery."""
        broker = domain.brokers["default"]
        broker._ensure_group("group", "again")
        broker.redis_instance.xadd("again", {"i": "1"})
        _leave_pending(domain, "again", "group", 1)

        assert list(
            broker._reclaim_idle_pending("again", "group", "a", 10).values()
        ) == [1]
        time.sleep(RECLAIM_IDLE_SECONDS * 2)
        assert list(
            broker._reclaim_idle_pending("again", "group", "b", 10).values()
        ) == [1]

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

    def test_error_after_a_claimed_page_returns_that_pages_counts(self, domain, caplog):
        """A broker error on the second page stops the scan. The entries the
        first page claimed keep their delivery counts: each page reads its
        counts in the same call that claims it."""
        broker = domain.brokers["default"]
        broker._ensure_group("group", "partial")
        for i in range(150):
            broker.redis_instance.xadd("partial", {"i": str(i)})
        _leave_pending(domain, "partial", "group", 150)
        # A second delivery of every entry to the stopped worker.
        broker.redis_instance.xreadgroup(
            "group", STOPPED_CONSUMER, {"partial": "0"}, count=150
        )
        time.sleep(RECLAIM_IDLE_SECONDS * 2)

        claim = broker._lua_autoclaim_justid
        calls = 0

        def fail_second_page(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise redis.ConnectionError("connection lost")
            return claim(*args, **kwargs)

        broker._lua_autoclaim_justid = fail_second_page
        with caplog.at_level(logging.WARNING, logger="protean.adapters.broker.redis"):
            counts = broker._reclaim_idle_pending("partial", "group", "new", 10)

        assert len(counts) == 100
        assert set(counts.values()) == {2}
        assert "Stopped claiming idle entries for group on partial after 100" in (
            caplog.text
        )

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
