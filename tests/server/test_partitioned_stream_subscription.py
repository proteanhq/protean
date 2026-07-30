"""Two-instance integration tests for the partitioned stream consumer (ADR-0028).

These exercise the consumer side of ``sequential_by`` against a live Redis. Two
``PartitionedStreamSubscription`` instances with distinct owner ids (but the same
consumer group) stand in for two engine instances: the coordination that matters
lives in Redis (the ownership lease keyed ``{group}:{key}:__lease__``, holding
``{owner_id}:{generation}``), so distinct owner ids on one Redis faithfully model
two processes. The lease is exactly the cross-instance in-progress marker ADR-0028
asks for — recorded in Redis with the instance id, not in process memory — so
"no two instances process the same key at once" is asserted as "the lease is held
by exactly one instance".

Draining is driven step by step (``_auto_workers=False``) so ordering, halt,
fence, reclaim, discovery, and reaping are deterministic rather than timing
races; one end-to-end test runs the real async poll loops as a wiring smoke test.
"""

import asyncio
from collections import defaultdict
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.domain import Domain
from protean.fields import Identifier, Integer, String
from protean.port.broker import LeaseLostError
from protean.server import Engine
from protean.server.subscription.partitioned_stream_subscription import (
    PartitionedStreamSubscription,
)
from protean.utils.eventing import Message
from protean.utils.mixins import handle
from tests.shared import REDIS_URI

pytestmark = [pytest.mark.redis, pytest.mark.no_test_domain]

# Recording sinks for handlers (single test process, so plain dicts suffice for
# order; cross-instance exclusion is proven via the Redis lease, not these).
processed: dict[str, list[int]] = defaultdict(list)
pm_processed: dict[str, list[str]] = defaultdict(list)
poison: dict[str, int] = {}


# --- Domain elements -------------------------------------------------------


class OrderPlaced(BaseEvent):
    order_id = Identifier(identifier=True)
    client_id = String()
    seq = Integer()


class Order(BaseAggregate):
    client_id = String()
    seq = Integer()


class OrderTracker(BaseEventHandler):
    @handle(OrderPlaced)
    def track(self, event: OrderPlaced) -> None:
        # A poisoned (client_id, seq) fails every time, so the partition halts.
        if poison.get(event.client_id) == event.seq:
            raise RuntimeError(f"poison {event.client_id}:{event.seq}")
        processed[event.client_id].append(event.seq)


# Process-manager elements: correlate order + payment by order_id.


class PaymentReceived(BaseEvent):
    payment_id = Identifier(identifier=True)
    order_id = Identifier()
    seq = Integer()


class Payment(BaseAggregate):
    order_id = Identifier()


class OrderSaga(BaseProcessManager):
    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order(self, event: OrderPlaced) -> None:
        pm_processed[event.order_id].append(f"order:{event.seq}")

    @handle(PaymentReceived, correlate="order_id")
    def on_payment(self, event: PaymentReceived) -> None:
        pm_processed[event.order_id].append(f"payment:{event.seq}")


# --- Fixtures --------------------------------------------------------------


def _build_domain(name: str, db: int, *, with_pm: bool = False) -> Domain:
    # The module reuses the same element classes (Order/OrderPlaced/OrderSaga)
    # across every test's domain. Protean caches a handler's ``_handlers`` on the
    # class after the first registration but re-derives each event's ``__type__``
    # from the domain name, so all PM domains must share one name (and all
    # non-PM domains another) or a later domain's message type stops matching the
    # cached handler map. Pin the name by flavour rather than trusting callers.
    name = "PmSeq" if with_pm else "PartSeq"
    domain = Domain(name=name)
    domain.config["brokers"]["default"] = {
        "provider": "redis",
        "URI": f"{REDIS_URI}/{db}",
    }
    domain.config["command_processing"] = "sync"
    domain.config["event_processing"] = "sync"
    # Tight partitioning knobs so reaping/lease tests are fast.
    domain.config["server"] = {
        "partitioning": {
            "lease_ttl_ms": 3000,
            "heartbeat_interval_seconds": 0.3,
            "poll_interval_seconds": 0.02,
            "reap_idle_ms": 0,
        }
    }
    domain._initialize()
    domain.register(Order)
    domain.register(OrderPlaced, part_of=Order)
    if with_pm:
        domain.register(Payment)
        domain.register(PaymentReceived, part_of=Payment)
        domain.register(OrderSaga, sequential_by=True)
    else:
        domain.register(OrderTracker, part_of=Order, sequential_by="client_id")
    domain.init(traverse=False)
    return domain


@pytest.fixture(autouse=True)
def _reset() -> None:
    processed.clear()
    pm_processed.clear()
    poison.clear()


@pytest.fixture
def domain() -> Domain:
    domain = _build_domain("PartTest", 11)
    with domain.domain_context():
        domain.brokers["default"]._data_reset()
        yield domain
        domain.brokers["default"]._data_reset()


@pytest.fixture
def category(domain: Domain) -> str:
    return Order.meta_.stream_category


# --- Helpers ---------------------------------------------------------------


async def _make_sub(
    domain: Domain,
    *,
    correlated: bool = False,
    categories: list[str] | None = None,
    auto_workers: bool = False,
) -> PartitionedStreamSubscription:
    """Build and initialize a partitioned subscription against *domain*."""
    engine = Engine(domain=domain, test_mode=True)
    primary = (categories or [Order.meta_.stream_category])[0]
    handler = OrderSaga if correlated else OrderTracker
    sub = PartitionedStreamSubscription(
        engine=engine,
        stream_category=primary,
        handler=handler,
        stream_categories=categories or [Order.meta_.stream_category],
        correlated=correlated,
        max_retries=2,
        retry_delay_seconds=0,
    )
    sub._auto_workers = auto_workers
    await sub.initialize()
    return sub


def _publish(domain: Domain, category: str, event: BaseEvent, key: str) -> None:
    """Publish an event to its partition stream and index it (mimics the outbox)."""
    broker = domain.brokers["default"]
    message = Message.from_domain_object(event)
    broker.record_partition(category, key)
    broker._publish(f"{category}:{key}", message.to_dict())


def _order_event(client_id: str, seq: int) -> OrderPlaced:
    return OrderPlaced(order_id=str(uuid4()), client_id=client_id, seq=seq)


async def _drain(
    sub: PartitionedStreamSubscription, partition_id: str, times: int = 30
) -> None:
    """Drain a partition until it halts or truly runs dry (bounded).

    A failed head returns 0 processed but leaves a retry pending (tracked in
    ``retry_counts``), so "0 processed" alone does not mean the partition is
    drained — keep going while a retry is outstanding, stop only when it halts or
    there is genuinely nothing left.
    """
    owned = sub._owned[partition_id]
    await sub._reclaim(owned)
    for _ in range(times):
        if owned.halted:
            break
        processed_n = await sub._drain_once(owned)
        if processed_n == 0 and not owned.retry_counts:
            break


# --- Tests: factory selection ---------------------------------------------


def test_factory_selects_partitioned_for_sequential_by(domain: Domain) -> None:
    engine = Engine(domain=domain, test_mode=True)
    subs = [
        s
        for s in engine._subscriptions.values()
        if isinstance(s, PartitionedStreamSubscription)
    ]
    assert len(subs) == 1
    assert subs[0].handler is OrderTracker


def test_pm_with_no_categories_is_not_partitioned(domain: Domain) -> None:
    # Defensive guard: a sequential_by PM that somehow has no stream categories
    # is not treated as partitioned (it would have nothing to lease).
    from types import SimpleNamespace

    engine = Engine(domain=domain, test_mode=True)
    stub = SimpleNamespace(
        meta_=SimpleNamespace(sequential_by=True, stream_categories=[])
    )
    assert engine._is_partitioned_process_manager(stub) is False


def test_factory_plain_stream_when_broker_cannot_partition() -> None:
    # Inline broker does not advertise STREAM_PARTITIONING: sequential_by is a
    # no-op and the handler keeps a regular stream subscription (decision 8).
    domain = Domain(name="InlinePart")
    domain.config["event_processing"] = "sync"
    domain._initialize()
    domain.register(Order)
    domain.register(OrderPlaced, part_of=Order)
    domain.register(OrderTracker, part_of=Order, sequential_by="client_id")
    domain.init(traverse=False)
    with domain.domain_context():
        engine = Engine(domain=domain, test_mode=True)
        trackers = [
            s
            for s in engine._subscriptions.values()
            if getattr(s, "handler", None) is OrderTracker
        ]
        assert len(trackers) == 1
        # The invariant: no partitioned consumer under a non-partitioning broker.
        assert not isinstance(trackers[0], PartitionedStreamSubscription)


# --- Tests: ordering, ownership, parallelism -------------------------------


async def test_strict_per_key_order(domain: Domain, category: str) -> None:
    for seq in range(4):
        _publish(domain, category, _order_event("A", seq), "A")

    sub = await _make_sub(domain)
    await sub._discovery_pass()
    await _drain(sub, "A")

    assert processed["A"] == [0, 1, 2, 3]


async def test_single_owner_across_instances(domain: Domain, category: str) -> None:
    _publish(domain, category, _order_event("A", 0), "A")

    sub_a = await _make_sub(domain)
    sub_b = await _make_sub(domain)

    await sub_a._discovery_pass()
    await sub_b._discovery_pass()

    # Exactly one instance holds the lease (the cross-instance marker).
    owners = [s for s in (sub_a, sub_b) if "A" in s._owned]
    assert len(owners) == 1
    owner, other = owners[0], (sub_b if owners[0] is sub_a else sub_a)

    # The non-owner is fenced: it cannot read or ack the partition.
    stream = f"{category}:A"
    lease_key = owner._lease_key("A")
    with pytest.raises(LeaseLostError):
        domain.brokers["default"].read_partition_fenced(
            stream,
            owner.consumer_group,
            "intruder:99",
            lease_key,
            "intruder:99",
        )
    assert other  # the other instance simply owns nothing here


async def test_cross_key_parallelism(domain: Domain, category: str) -> None:
    # Two instances hold leases on two different keys AT THE SAME TIME, and each
    # drains its own key while the other holds its lease. This is the property
    # that distinguishes "serialize per key" from "serialize everything": a
    # single global lock would stop sub_b from taking B while sub_a holds A.
    _publish(domain, category, _order_event("A", 0), "A")
    _publish(domain, category, _order_event("B", 0), "B")

    sub_a = await _make_sub(domain)
    sub_b = await _make_sub(domain)

    # Force distribution: A to instance a, B to instance b.
    await sub_a._acquire_new({"A": [(category, f"{category}:A")]})
    await sub_b._acquire_new({"B": [(category, f"{category}:B")]})

    # Both leases are held concurrently by different instances.
    assert "A" in sub_a._owned
    assert "B" in sub_b._owned
    assert "A" not in sub_b._owned
    assert "B" not in sub_a._owned

    # Interleave draining: both make progress while the other still holds its
    # lease, so neither key blocks the other.
    await sub_a._drain_once(sub_a._owned["A"])
    await sub_b._drain_once(sub_b._owned["B"])
    assert processed["A"] == [0]
    assert processed["B"] == [0]
    assert "A" in sub_a._owned and "B" in sub_b._owned  # both still owned


# --- Tests: halt on poison -------------------------------------------------


async def test_halt_on_poison_is_partition_scoped(
    domain: Domain, category: str
) -> None:
    poison["A"] = 1  # A's second event always fails
    for seq in range(3):
        _publish(domain, category, _order_event("A", seq), "A")
    for seq in range(3):
        _publish(domain, category, _order_event("B", seq), "B")

    sub = await _make_sub(domain)
    await sub._discovery_pass()
    await _drain(sub, "A")
    await _drain(sub, "B")

    # A processed only up to the poison head and halted; it never advanced to 2.
    assert processed["A"] == [0]
    assert sub._owned["A"].halted is True
    # B is unaffected and drains fully.
    assert processed["B"] == [0, 1, 2]
    assert sub._owned["B"].halted is False

    # No auto-DLQ: the poison is still the pending head, not moved anywhere.
    broker = domain.brokers["default"]
    assert broker.dlq_depth(f"{category}:A:dlq") == 0
    # The poison message stays pending as the head for an operator to resolve —
    # a regression that acked-then-halted (losing the message) is caught here.
    pending = broker._client.xpending(f"{category}:A", sub.consumer_group)
    assert pending["pending"] == 1


# --- Tests: crash and stall failover --------------------------------------


async def test_crash_failover_reclaims_pending(domain: Domain, category: str) -> None:
    for seq in range(3):
        _publish(domain, category, _order_event("A", seq), "A")

    broker = domain.brokers["default"]
    sub_a = await _make_sub(domain)
    await sub_a._discovery_pass()
    owned_a = sub_a._owned["A"]
    stream = f"{category}:A"

    # A reads seq 0, RUNS its handler (records 0), then "crashes" before acking:
    # exactly the applied-but-unacked case the ADR says must re-run, not be lost.
    delivered = broker.read_partition_fenced(
        stream,
        sub_a.consumer_group,
        owned_a.consumer_name,
        owned_a.lease_key,
        owned_a.fence_token,
    )
    assert [m[1]["data"]["seq"] for m in delivered] == [0]
    await sub_a.engine.handle_message(
        sub_a.handler, Message.deserialize(delivered[0][1])
    )
    assert processed["A"] == [0]
    broker._client.delete(owned_a.lease_key)  # lease expires on crash

    # B takes over at a new generation, reclaims the pending entry, drains in order.
    sub_b = await _make_sub(domain)
    await sub_b._discovery_pass()
    assert "A" in sub_b._owned
    await _drain(sub_b, "A")

    # No loss and correct order. Apply is at-least-once across the crash: seq 0
    # ran on A (unacked) and re-ran on B, so assert order + no-loss (deduped
    # committed order is [0,1,2]) and that seq 0 genuinely re-ran, NOT one call
    # per event.
    assert _dedup_in_order(processed["A"]) == [0, 1, 2]
    assert processed["A"].count(0) == 2  # re-run on failover


async def test_stall_failover_fence_holds(domain: Domain, category: str) -> None:
    for seq in range(3):
        _publish(domain, category, _order_event("A", seq), "A")

    broker = domain.brokers["default"]
    sub_a = await _make_sub(domain)
    await sub_a._discovery_pass()
    owned_a = sub_a._owned["A"]

    # A stalls: its lease expires and B takes over at a higher generation.
    broker._client.delete(owned_a.lease_key)
    sub_b = await _make_sub(domain)
    await sub_b._discovery_pass()
    owned_b = sub_b._owned["A"]
    assert owned_b.generation > owned_a.generation

    stream = f"{category}:A"
    # The resumed stale owner (A) is fenced out of both reading and acking.
    with pytest.raises(LeaseLostError):
        broker.read_partition_fenced(
            stream,
            sub_a.consumer_group,
            owned_a.consumer_name,
            owned_a.lease_key,
            owned_a.fence_token,
        )
    with pytest.raises(LeaseLostError):
        broker.ack_partition_fenced(
            stream,
            "0-0",
            sub_a.consumer_group,
            owned_a.lease_key,
            owned_a.fence_token,
        )

    # B, the true owner, drains the partition in committed order.
    await _drain(sub_b, "A")
    assert processed["A"] == [0, 1, 2]


# --- Tests: discovery and reaping ------------------------------------------


async def test_dynamic_discovery(domain: Domain, category: str) -> None:
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    assert set(sub._owned) == {"A"}

    # A brand-new key appears with no restart; discovery picks it up next cycle.
    _publish(domain, category, _order_event("B", 0), "B")
    await sub._discovery_pass()
    assert set(sub._owned) == {"A", "B"}


async def test_cold_partition_reaping(domain: Domain, category: str) -> None:
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    await _drain(sub, "A")
    assert processed["A"] == [0]

    broker = domain.brokers["default"]
    assert "A" in broker.partition_keys(category)

    # reap_idle_ms=0 → a fully drained partition is retired immediately.
    retired = await sub._retire(sub._owned["A"])
    assert retired is True
    assert "A" not in broker.partition_keys(category)
    assert "A" not in sub._owned


async def test_reaped_key_is_rediscovered_when_republished(
    domain: Domain, category: str
) -> None:
    # After a reap, publishing the key again re-adds it to the index and it is
    # rediscovered — the message is never stranded on a stream absent from the
    # index. (The publisher keeps no cache that could skip the re-add; that the
    # outbox always records is covered separately in the outbox tests.)
    broker = domain.brokers["default"]
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    await _drain(sub, "A")
    assert await sub._retire(sub._owned["A"]) is True
    assert "A" not in broker.partition_keys(category)

    # Same key published again → re-indexed and rediscovered with no restart.
    _publish(domain, category, _order_event("A", 1), "A")
    assert "A" in broker.partition_keys(category)
    await sub._discovery_pass()
    assert "A" in sub._owned
    await _drain(sub, "A")
    assert processed["A"] == [0, 1]


# --- Tests: process manager ------------------------------------------------


async def test_process_manager_serializes_per_correlation() -> None:
    domain = _build_domain("PmTest", 11, with_pm=True)
    with domain.domain_context():
        broker = domain.brokers["default"]
        broker._data_reset()
        order_cat = Order.meta_.stream_category
        pay_cat = Payment.meta_.stream_category

        # Two correlation values (order ids), events across both categories.
        oid1, oid2 = "corr-1", "corr-2"
        broker.record_partition(order_cat, oid1)
        broker._publish(
            f"{order_cat}:{oid1}",
            Message.from_domain_object(_pm_order(oid1, 0)).to_dict(),
        )
        broker.record_partition(pay_cat, oid1)
        broker._publish(
            f"{pay_cat}:{oid1}",
            Message.from_domain_object(_pm_payment(oid1, 1)).to_dict(),
        )
        broker.record_partition(order_cat, oid2)
        broker._publish(
            f"{order_cat}:{oid2}",
            Message.from_domain_object(_pm_order(oid2, 0)).to_dict(),
        )

        sub = await _make_sub(domain, correlated=True, categories=[order_cat, pay_cat])
        await sub._discovery_pass()

        # One unit per correlation value, spanning both categories for corr-1.
        assert set(sub._owned) == {oid1, oid2}
        assert {c for c, _ in sub._owned[oid1].streams} == {order_cat, pay_cat}

        await _drain(sub, oid1)
        await _drain(sub, oid2)

        # corr-1 saw both its events; corr-2 only its order event. Cross-category
        # order is not promised, only that one correlation's events never overlap
        # (guaranteed by the single owning worker), so assert the set.
        assert set(pm_processed[oid1]) == {"order:0", "payment:1"}
        assert pm_processed[oid2] == ["order:0"]

        broker._data_reset()


async def test_process_manager_single_owner_across_instances() -> None:
    domain = _build_domain("PmExcl", 11, with_pm=True)
    with domain.domain_context():
        broker = domain.brokers["default"]
        broker._data_reset()
        order_cat = Order.meta_.stream_category
        pay_cat = Payment.meta_.stream_category
        oid = "corr-1"  # present in both categories
        _pm_publish(broker, order_cat, _pm_order(oid, 0), oid)
        _pm_publish(broker, pay_cat, _pm_payment(oid, 1), oid)

        sub_a = await _make_sub(
            domain, correlated=True, categories=[order_cat, pay_cat]
        )
        sub_b = await _make_sub(
            domain, correlated=True, categories=[order_cat, pay_cat]
        )
        await sub_a._discovery_pass()
        await sub_b._discovery_pass()

        # Exactly one instance owns the correlation value, spanning BOTH streams.
        owners = [s for s in (sub_a, sub_b) if oid in s._owned]
        assert len(owners) == 1
        owner = owners[0]
        assert {c for c, _ in owner._owned[oid].streams} == {order_cat, pay_cat}

        # The loser is fenced out of every category stream for the correlation
        # value — no second instance can process the same PM instance's events.
        lease_key = owner._lease_key(oid)
        for cat in (order_cat, pay_cat):
            with pytest.raises(LeaseLostError):
                broker.read_partition_fenced(
                    f"{cat}:{oid}",
                    owner.consumer_group,
                    "intruder:99",
                    lease_key,
                    "intruder:99",
                )
        broker._data_reset()


async def test_process_manager_absorbs_late_category_stream() -> None:
    # A PM unit keyed by a correlation value must pick up a category stream that
    # first appears after the unit is already owned (order arrives, payment for
    # the same order arrives later) — otherwise the later stream is never read.
    domain = _build_domain("PmLate", 11, with_pm=True)
    with domain.domain_context():
        broker = domain.brokers["default"]
        broker._data_reset()
        order_cat = Order.meta_.stream_category
        pay_cat = Payment.meta_.stream_category
        oid = "corr-1"

        _pm_publish(broker, order_cat, _pm_order(oid, 0), oid)
        sub = await _make_sub(domain, correlated=True, categories=[order_cat, pay_cat])
        await sub._discovery_pass()
        assert {c for c, _ in sub._owned[oid].streams} == {order_cat}
        await _drain(sub, oid)
        assert pm_processed[oid] == ["order:0"]

        # Payment for the SAME correlation value appears later.
        _pm_publish(broker, pay_cat, _pm_payment(oid, 1), oid)
        await sub._discovery_pass()  # merges the late stream into the owned unit
        assert {c for c, _ in sub._owned[oid].streams} == {order_cat, pay_cat}
        await _drain(sub, oid)
        assert set(pm_processed[oid]) == {"order:0", "payment:1"}
        broker._data_reset()


def _pm_order(order_id: str, seq: int) -> OrderPlaced:
    return OrderPlaced(order_id=order_id, client_id="c", seq=seq)


def _pm_payment(order_id: str, seq: int) -> PaymentReceived:
    return PaymentReceived(payment_id=str(uuid4()), order_id=order_id, seq=seq)


def _pm_publish(broker, category: str, event: BaseEvent, corr: str) -> None:
    broker.record_partition(category, corr)
    broker._publish(f"{category}:{corr}", Message.from_domain_object(event).to_dict())


# --- Test: end-to-end async smoke -----------------------------------------


async def test_end_to_end_async_poll_loops(domain: Domain, category: str) -> None:
    """Two real poll loops drain two keys end to end (integration wiring check)."""
    for seq in range(3):
        _publish(domain, category, _order_event("A", seq), "A")
        _publish(domain, category, _order_event("B", seq), "B")

    sub_a = await _make_sub(domain, auto_workers=True)
    sub_b = await _make_sub(domain, auto_workers=True)
    task_a = asyncio.get_event_loop().create_task(sub_a.poll())
    task_b = asyncio.get_event_loop().create_task(sub_b.poll())

    async def _done() -> bool:
        return processed["A"] == [0, 1, 2] and processed["B"] == [0, 1, 2]

    for _ in range(100):
        if await _done():
            break
        await asyncio.sleep(0.1)

    sub_a.keep_going = False
    sub_b.keep_going = False
    await sub_a.cleanup()
    await sub_b.cleanup()
    task_a.cancel()
    task_b.cancel()

    assert processed["A"] == [0, 1, 2]
    assert processed["B"] == [0, 1, 2]


# --- Tests: control-flow branches (deterministic, direct-await) ------------
# The discovery loop and per-partition workers run as asyncio tasks in
# production; here they are awaited directly so their control-flow branches
# (backoff, cancel, fence-out, retire-fail, error handling) are exercised
# deterministically instead of via timing races.


async def test_initialize_without_broker_raises(domain: Domain, monkeypatch) -> None:
    sub = await _make_sub(domain)
    # No default broker configured → fail loud. Patch only ``get`` so the
    # fixture teardown (which uses ``brokers["default"]``) still works.
    monkeypatch.setattr(sub.engine.domain.brokers, "get", lambda name: None)
    with pytest.raises(RuntimeError):
        await sub.initialize()


async def test_poll_runs_a_pass_then_stops(domain: Domain, monkeypatch) -> None:
    sub = await _make_sub(domain)
    calls: list[int] = []

    async def _once() -> None:
        calls.append(1)
        sub.keep_going = False

    monkeypatch.setattr(sub, "_discovery_pass", _once)
    await sub.poll()
    assert calls == [1]


async def test_poll_breaks_on_cancel(domain: Domain, monkeypatch) -> None:
    sub = await _make_sub(domain)

    async def _cancel() -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(sub, "_discovery_pass", _cancel)
    await sub.poll()  # CancelledError is caught and breaks the loop


async def test_poll_backs_off_on_error(domain: Domain, monkeypatch) -> None:
    sub = await _make_sub(domain)
    sub.heartbeat_interval = 0
    n = {"i": 0}

    async def _boom() -> None:
        n["i"] += 1
        if n["i"] == 1:
            raise RuntimeError("discovery blew up")
        sub.keep_going = False

    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    monkeypatch.setattr(sub, "_discovery_pass", _boom)
    await sub.poll()
    assert n["i"] == 2


async def test_cleanup_cancels_workers_and_releases(
    domain: Domain, category: str
) -> None:
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    owned = sub._owned["A"]
    owned.task = asyncio.get_running_loop().create_task(asyncio.sleep(30))

    await sub.cleanup()
    assert sub._owned == {}
    assert owned.task.cancelling() or owned.task.cancelled()


async def test_discover_units_swallows_broker_error(
    domain: Domain, monkeypatch
) -> None:
    sub = await _make_sub(domain)
    monkeypatch.setattr(sub.broker, "partition_keys", _raiser(RuntimeError("x")))
    assert sub._discover_units() == {}


async def test_drop_owned_is_idempotent(domain: Domain) -> None:
    sub = await _make_sub(domain)
    await sub._drop_owned("never-owned")  # no-op when the id is not owned
    assert sub._owned == {}


async def test_renew_drops_lost_lease(domain: Domain, category: str) -> None:
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    owned = sub._owned["A"]
    owned.task = asyncio.get_running_loop().create_task(asyncio.sleep(30))

    domain.brokers["default"]._client.delete(owned.lease_key)  # lease lost
    await sub._renew_owned()
    assert "A" not in sub._owned
    assert owned.task.cancelling() or owned.task.cancelled()


async def test_release_lease_swallows_error(
    domain: Domain, category: str, monkeypatch
) -> None:
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    owned = sub._owned["A"]
    monkeypatch.setattr(
        sub.broker, "release_partition_lease", _raiser(RuntimeError("x"))
    )
    await sub._release_lease(owned)  # swallowed, no raise


async def test_run_partition_drains_then_retires(domain: Domain, category: str) -> None:
    for seq in range(2):
        _publish(domain, category, _order_event("A", seq), "A")
    sub = await _make_sub(domain)  # reap_idle_ms=0 from the fixture config
    await sub._discovery_pass()
    await asyncio.wait_for(sub._run_partition(sub._owned["A"]), timeout=5)
    assert processed["A"] == [0, 1]
    assert "A" not in sub._owned  # retired after draining


async def test_run_partition_gives_up_when_fenced(
    domain: Domain, category: str
) -> None:
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    # Pin reaping off so the ONLY way to leave _owned here is the fence-out path
    # (a lost lease), never retirement of a drained partition.
    sub.reap_idle_ms = 10_000_000
    await sub._discovery_pass()
    owned = sub._owned["A"]
    domain.brokers["default"]._client.delete(owned.lease_key)  # fence lost
    await asyncio.wait_for(sub._run_partition(owned), timeout=5)
    assert "A" not in sub._owned  # dropped after LeaseLostError
    # Fenced out before handling: the event was never processed (not drained).
    assert processed["A"] == []


async def test_run_partition_propagates_cancel(
    domain: Domain, category: str, monkeypatch
) -> None:
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    owned = sub._owned["A"]

    async def _cancel(_owned) -> int:
        raise asyncio.CancelledError

    monkeypatch.setattr(sub, "_drain_once", _cancel)
    with pytest.raises(asyncio.CancelledError):
        await sub._run_partition(owned)


async def test_run_partition_logs_unexpected_error(
    domain: Domain, category: str, monkeypatch
) -> None:
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    owned = sub._owned["A"]

    async def _boom(_owned) -> int:
        raise RuntimeError("drain blew up")

    monkeypatch.setattr(sub, "_drain_once", _boom)
    await asyncio.wait_for(sub._run_partition(owned), timeout=5)  # caught + logged
    # A transient worker error gives up ownership so the lease lapses and the
    # partition can be re-acquired, rather than wedging behind a dead worker.
    assert "A" not in sub._owned


async def test_run_partition_resets_idle_when_retire_fails(
    domain: Domain, category: str, monkeypatch
) -> None:
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    owned = sub._owned["A"]
    calls = {"n": 0}

    async def _retire_fail(_owned) -> bool:
        calls["n"] += 1
        sub.keep_going = False  # stop the worker after this pass
        return False

    monkeypatch.setattr(sub, "_retire", _retire_fail)
    await asyncio.wait_for(sub._run_partition(owned), timeout=5)
    assert calls["n"] == 1


async def test_reclaim_propagates_lease_lost(
    domain: Domain, category: str, monkeypatch
) -> None:
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    owned = sub._owned["A"]
    monkeypatch.setattr(
        sub.broker, "reclaim_partition_pending", _raiser(LeaseLostError("gone"))
    )
    with pytest.raises(LeaseLostError):
        await sub._reclaim(owned)


async def test_reclaim_propagates_generic_error(
    domain: Domain, category: str, monkeypatch
) -> None:
    # Reclaim is a correctness precondition: a failure propagates to
    # _run_partition (which drops ownership) rather than being swallowed and
    # letting the worker drain out of order.
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    owned = sub._owned["A"]
    monkeypatch.setattr(
        sub.broker, "reclaim_partition_pending", _raiser(RuntimeError("x"))
    )
    with pytest.raises(RuntimeError):
        await sub._reclaim(owned)


async def test_deserialize_failure_is_a_processing_failure(
    domain: Domain, category: str
) -> None:
    broker = domain.brokers["default"]
    broker.record_partition(category, "A")
    broker._publish(f"{category}:A", {"not": "a valid message envelope"})
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    owned = sub._owned["A"]

    await sub._drain_once(owned)
    # A corrupt head is retried (not DLQ'd, not skipped) — a retry is recorded,
    # the message is not moved to a DLQ, and it stays pending as the head.
    assert owned.retry_counts
    assert broker.dlq_depth(f"{category}:A:dlq") == 0
    pending = broker._client.xpending(f"{category}:A", sub.consumer_group)
    assert pending["pending"] == 1


async def test_drain_once_breaks_when_halted(domain: Domain, category: str) -> None:
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    owned = sub._owned["A"]
    owned.halted = True
    assert await sub._drain_once(owned) == 0  # short-circuits on the halt flag


async def test_retire_returns_false_when_reap_blocked(
    domain: Domain, category: str, monkeypatch
) -> None:
    _publish(domain, category, _order_event("A", 0), "A")
    sub = await _make_sub(domain)
    await sub._discovery_pass()
    owned = sub._owned["A"]
    monkeypatch.setattr(sub.broker, "reap_partition", _raiser(RuntimeError("x")))
    assert await sub._retire(owned) is False
    assert "A" in sub._owned  # not retired


def _raiser(exc: Exception):
    def _fn(*args, **kwargs):
        raise exc

    return _fn


async def _noop_sleep(*args, **kwargs) -> None:
    return None


def _dedup_in_order(seq: list[int]) -> list[int]:
    """First occurrence of each value, in order — the committed order under
    at-least-once (duplicates removed, ordering preserved)."""
    seen: set[int] = set()
    out: list[int] = []
    for value in seq:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
