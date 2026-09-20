"""DLQ integration tests across subscription types.

Verifies end-to-end error handling flows:
- BrokerSubscription: handler fail → retry → DLQ publish
- EventStoreSubscription: handler fail → failed position → recovery
- DLQ discovery: all subscription types surfaced by discovery utility
- InlineBroker internal DLQ: nack → max retries → list/inspect/replay/purge
"""

import logging
import time

import pytest

from protean import Domain, handle
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.fields import String
from protean.server.engine import Engine
from protean.utils.dlq import collect_dlq_streams, discover_subscriptions

# ── Shared domain elements ──────────────────────────────────────────────


class DLQTestAggregate(BaseAggregate):
    name: String(required=True)


class DLQTestEvent(BaseEvent):
    name: String(required=True)


class DLQTestCommand(BaseCommand):
    name: String(required=True)


fail_counter = 0
success_counter = 0


class FailThenSucceedHandler(BaseEventHandler):
    """Fails the first N calls, then succeeds."""

    @handle(DLQTestEvent)
    def handle_event(self, event):
        global fail_counter
        fail_counter += 1
        if fail_counter <= 2:
            raise RuntimeError(f"Transient failure #{fail_counter}")


class AlwaysFailHandler(BaseEventHandler):
    @handle(DLQTestEvent)
    def handle_event(self, event):
        raise RuntimeError("Permanent failure")


class SuccessHandler(BaseEventHandler):
    @handle(DLQTestEvent)
    def handle_event(self, event):
        global success_counter
        success_counter += 1


class FailingSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        raise RuntimeError("Subscriber failure")


class SucceedingSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        global success_counter
        success_counter += 1


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_counters():
    global fail_counter, success_counter
    fail_counter = 0
    success_counter = 0


# ── Tests: BrokerSubscription retry → DLQ end-to-end ────────────────────


class TestBrokerSubscriptionDLQIntegration:
    """BrokerSubscription handler failure → retry → DLQ publish."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(FailingSubscriber, stream="integration_stream")
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_handler_failure_produces_dlq_message(self, test_domain):
        """When a subscriber fails max_retries times, message ends up in DLQ stream."""
        engine = Engine(test_domain, test_mode=True)
        broker = test_domain.brokers["default"]

        from protean.server.subscription.broker_subscription import (
            BrokerSubscription,
        )

        sub = BrokerSubscription(
            engine=engine,
            broker=broker,
            stream_name="integration_stream",
            handler=FailingSubscriber,
            max_retries=1,
            retry_delay_seconds=0,
        )

        # Simulate processing a message that will fail
        identifier = "int-msg-1"
        payload = {"data": "test_payload"}

        # First call — exhausts retries (max_retries=1)
        is_successful = await engine.handle_broker_message(
            FailingSubscriber,
            payload,
            message_id=identifier,
            stream="integration_stream",
        )
        assert is_successful is False

        # Trigger the retry/DLQ logic
        await sub._handle_failed_message(identifier, payload)

        # The DLQ message should be published to integration_stream:dlq
        dlq_messages = broker._messages.get("integration_stream:dlq", [])
        assert len(dlq_messages) == 1

        _, dlq_payload = dlq_messages[0]
        assert "_dlq_metadata" in dlq_payload
        assert dlq_payload["_dlq_metadata"]["original_stream"] == "integration_stream"
        assert dlq_payload["_dlq_metadata"]["original_id"] == identifier

    @pytest.mark.asyncio
    async def test_successful_processing_no_dlq(self, test_domain):
        """Successful subscriber processing does not produce DLQ messages."""
        test_domain.register(SucceedingSubscriber, stream="success_stream")
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)
        broker = test_domain.brokers["default"]

        is_successful = await engine.handle_broker_message(
            SucceedingSubscriber,
            {"data": "good"},
            message_id="ok-msg",
            stream="success_stream",
        )
        assert is_successful is True
        assert success_counter == 1

        # No DLQ messages
        dlq_messages = broker._messages.get("success_stream:dlq", [])
        assert len(dlq_messages) == 0

    @pytest.mark.asyncio
    async def test_persistent_dlq_outage_holds_and_lands_in_published_dlq(
        self, test_domain, monkeypatch
    ):
        """The subscription owns retry/DLQ: the InlineBroker holds, never dead-letters.

        Under a persistent ``{stream}:dlq`` outage the subscription holds the
        message by NACKing it. Because the subscription owns retry and
        dead-lettering for this stream, the InlineBroker holds-and-redelivers
        with no independent ceiling: it never moves the message to its own native
        DLQ, no matter how many rounds the outage lasts. When the DLQ recovers,
        the message lands in the single documented ``{stream}:dlq`` and the retry
        count is cleared, so nothing leaks.
        """
        engine = Engine(test_domain, test_mode=True)
        broker = test_domain.brokers["default"]
        # A low ceiling that the OLD, unreconciled broker would have tripped, plus
        # no retry delay so the unbounded rounds run fast.
        monkeypatch.setattr(broker, "_max_retries", 1)
        monkeypatch.setattr(broker, "_retry_delay", 0)

        from protean.server.subscription.broker_subscription import (
            BrokerSubscription,
        )

        sub = BrokerSubscription(
            engine=engine,
            broker=broker,
            stream_name="integration_stream",
            handler=FailingSubscriber,
            max_retries=1,
            retry_delay_seconds=0,
        )

        # A persistent DLQ outage: every publish to the DLQ stream raises.
        real_publish = broker.publish

        def faulty_publish(stream, message):
            if stream == sub.dlq_stream:
                raise RuntimeError("DLQ down")
            return real_publish(stream, message)

        monkeypatch.setattr(broker, "publish", faulty_publish)

        identifier = "int-persistent-1"
        payload = {"data": "x"}
        group = sub.subscriber_name

        def reseed_in_flight():
            # Stand in for the poll loop re-reading the held message: re-seed the
            # delivery state (ownership + cleared op-state + in-flight) exactly as
            # ``get_next`` would. We set it directly rather than publish + read
            # because publishing to the source stream would synchronously invoke
            # the subscriber, and we bypass ``get_next``.
            broker._message_ownership[identifier][group] = True
            broker._clear_operation_state(group, identifier)
            broker._store_in_flight_message(
                "integration_stream", group, identifier, payload
            )

        # Drive the exhaust path for far more rounds than the broker's own ceiling.
        # The OLD broker would have dead-lettered on round 2; the reconciled broker
        # holds every round.
        for _ in range(broker._max_retries + 5):
            reseed_in_flight()
            await sub._handle_failed_message(identifier, payload)

        # Never reached the published DLQ stream (publish failed every round).
        assert len(broker._messages.get(sub.dlq_stream, [])) == 0
        # And never routed to the broker's native DLQ: it is held, not lost.
        native_dlq = broker.get_dlq_messages(group, "integration_stream")
        dlq_ids = [entry[0] for entries in native_dlq.values() for entry in entries]
        assert identifier not in dlq_ids
        group_key = f"integration_stream:{group}"
        held_ids = [entry[0] for entry in broker._failed_messages[group_key]]
        assert identifier in held_ids
        # The retry count is retained while the message is legitimately held.
        assert identifier in sub.retry_counts

        # Recovery: lift the outage and run one more exhaust cycle.
        monkeypatch.setattr(broker, "publish", real_publish)
        reseed_in_flight()
        await sub._handle_failed_message(identifier, payload)

        # It now lands in the single documented DLQ, the native DLQ stays empty,
        # and the retry count is cleared on ACK, so nothing leaks.
        assert len(broker._messages.get(sub.dlq_stream, [])) == 1
        native_dlq = broker.get_dlq_messages(group, "integration_stream")
        dlq_ids = [entry[0] for entries in native_dlq.values() for entry in entries]
        assert identifier not in dlq_ids
        assert identifier not in sub.retry_counts

    def test_subscription_marks_its_stream_owned_on_the_broker(self, test_domain):
        """``BrokerSubscription.__init__`` marks its (stream, group) broker-owned.

        This pins the wiring: without the owned mark the broker keeps its own
        ceiling and the fix silently no-ops.
        """
        engine = Engine(test_domain, test_mode=True)
        broker = test_domain.brokers["default"]

        from protean.server.subscription.broker_subscription import (
            BrokerSubscription,
        )

        sub = BrokerSubscription(
            engine=engine,
            broker=broker,
            stream_name="integration_stream",
            handler=FailingSubscriber,
        )

        group_key = f"integration_stream:{sub.subscriber_name}"
        assert group_key in broker._subscription_owned_groups

    def test_broker_direct_group_still_ceilings_to_native_dlq(self, test_domain):
        """A stream consumed directly off the broker keeps its independent ceiling.

        The reconciliation covers subscription-consumed streams only. A consumer
        group that was never marked owned still trips the broker's nack ceiling
        and lands in the native DLQ, so the boundary is real.
        """
        broker = test_domain.brokers["default"]
        broker._max_retries = 1
        broker._retry_delay = 0

        stream = "broker_direct_stream"
        consumer_group = "broker_direct_group"
        message = {"data": "y"}

        identifier = broker.publish(stream, message)

        # First nack holds; second nack exceeds the ceiling and dead-letters.
        assert broker.get_next(stream, consumer_group) is not None
        assert broker.nack(stream, identifier, consumer_group) is True
        assert broker.get_next(stream, consumer_group) is not None
        assert broker.nack(stream, identifier, consumer_group) is True

        dlq_messages = broker.get_dlq_messages(consumer_group, stream)
        dlq_ids = [entry[0] for entry in dlq_messages.get(stream, [])]
        assert identifier in dlq_ids

    def test_owned_group_holds_and_redelivers_through_the_real_poll_loop(
        self, test_domain
    ):
        """An owned group redelivers a nacked message through the real loop.

        This drives the actual ``get_next`` → ``nack`` path (requeue included),
        not a hand-seeded in-flight state. Past the broker's own ceiling the
        message is redelivered every round and never dead-lettered; a later ack
        clears the broker-side retry count and failed-message entry.
        """
        broker = test_domain.brokers["default"]
        broker._max_retries = 1
        broker._retry_delay = 0  # redelivery is ready immediately

        stream = "owned_real_loop_stream"
        group = "owned_real_loop_group"
        broker._mark_subscription_owned(stream, group)

        identifier = broker.publish(stream, {"data": "z"})
        group_key = f"{stream}:{group}"

        # Read → nack for far more rounds than the ceiling of 1. Each round
        # redelivers the same message via the real requeue path.
        for _ in range(broker._max_retries + 5):
            delivered = broker.get_next(stream, group)
            assert delivered is not None
            assert delivered[0] == identifier
            assert broker.nack(stream, identifier, group) is True

        # Never dead-lettered, still held and redeliverable.
        native_dlq = broker.get_dlq_messages(group, stream)
        native_ids = [e[0] for entries in native_dlq.values() for e in entries]
        assert identifier not in native_ids
        assert identifier in [e[0] for e in broker._failed_messages[group_key]]

        # Held-then-succeed: redeliver once more, then ack. Broker-side retry
        # count and failed-message entry both clear.
        delivered = broker.get_next(stream, group)
        assert delivered is not None and delivered[0] == identifier
        assert broker.ack(stream, identifier, group) is True
        assert broker._get_retry_count(stream, group, identifier) == 0
        assert identifier not in [e[0] for e in broker._failed_messages[group_key]]

    @pytest.mark.parametrize(
        ("multiplier", "retry_count"),
        [(2.0, 5000), (1e20, 32)],
        ids=["high_retry_count", "large_configured_multiplier"],
    )
    def test_owned_nack_backoff_does_not_overflow(
        self, test_domain, multiplier, retry_count
    ):
        """The backoff calculation cannot overflow and freeze the message.

        ``backoff_multiplier ** retry_count`` raises OverflowError once the
        result leaves float range, either from an unbounded owned-stream retry
        count or from a large configured multiplier. Unguarded, ``nack`` returns
        False after the message has left in-flight and the message freezes. The
        nack must still hold the message, with a bounded scheduled delay.
        """
        from protean.adapters.broker.inline import MAX_BACKOFF_DELAY

        broker = test_domain.brokers["default"]
        broker._max_retries = 1
        broker._retry_delay = 1.0  # a real delay, so the cap is what bounds it
        broker._backoff_multiplier = multiplier

        stream = "owned_backoff_stream"
        group = "owned_backoff_group"
        broker._mark_subscription_owned(stream, group)

        identifier = broker.publish(stream, {"data": "z"})
        assert broker.get_next(stream, group) is not None

        broker._set_retry_count(stream, group, identifier, retry_count)

        assert broker.nack(stream, identifier, group) is True
        after = time.time()

        group_key = f"{stream}:{group}"
        held = [e for e in broker._failed_messages[group_key] if e[0] == identifier]
        assert len(held) == 1
        next_retry_time = held[0][3]
        # The scheduled delay is bounded by the cap, not an overflowed/astronomical
        # value. next_retry_time == t_nack + delay, and delay <= MAX_BACKOFF_DELAY.
        assert next_retry_time <= after + MAX_BACKOFF_DELAY

    @pytest.mark.parametrize(
        "stream",
        ["owned_stale_stream", "ecommerce::order", "owned_stale_stream:dlq"],
        ids=["plain", "namespaced", "dlq_stream"],
    )
    def test_owned_stale_message_is_redelivered_not_dead_lettered(
        self, test_domain, stream
    ):
        """A timed-out in-flight message on an owned group is held, not DLQ'd.

        ``_cleanup_stale_messages`` runs on every ``get_next``. For an owned
        group it must not move the message to the native DLQ; it holds it for
        redelivery instead. Stream names that carry the group separator
        themselves (``domain::aggregate``, ``{stream}:dlq``) must be held under
        their real group key, otherwise the redelivery never happens.
        """
        broker = test_domain.brokers["default"]
        broker._retry_delay = 0

        group = "owned_stale_group"
        broker._mark_subscription_owned(stream, group)

        identifier = broker.publish(stream, {"data": "z"})
        assert broker.get_next(stream, group) is not None  # now in-flight

        # A negative timeout makes the just-read message count as stale.
        broker._cleanup_stale_messages(group, -1)

        native_dlq = broker.get_dlq_messages(group, stream)
        native_ids = [e[0] for entries in native_dlq.values() for e in entries]
        assert identifier not in native_ids

        # Held and redeliverable on the next read.
        delivered = broker.get_next(stream, group)
        assert delivered is not None and delivered[0] == identifier

    def test_data_reset_keeps_subscription_ownership(self, test_domain):
        """A broker data reset does not forget a live subscription's ownership.

        Ownership is wiring set once at subscription init, not message data.
        Clearing it on reset would silently reinstate the ceiling for a still-
        alive subscription.
        """
        broker = test_domain.brokers["default"]
        stream = "owned_reset_stream"
        group = "owned_reset_group"
        broker._mark_subscription_owned(stream, group)

        broker._data_reset()

        assert f"{stream}:{group}" in broker._subscription_owned_groups


# ── Tests: StreamSubscription owns retry/DLQ (default subscription type) ──


class TestStreamSubscriptionDLQReconciliation:
    """StreamSubscription (the default type) owns retry/DLQ end-to-end too."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(DLQTestAggregate)
        test_domain.register(DLQTestEvent, part_of=DLQTestAggregate)
        test_domain.register(AlwaysFailHandler, part_of=DLQTestAggregate)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_initialize_marks_its_stream_owned_on_the_broker(self, test_domain):
        """``StreamSubscription.initialize`` marks its (stream, group) owned."""
        from protean.server.subscription.stream_subscription import StreamSubscription

        engine = Engine(test_domain, test_mode=True)
        sub = StreamSubscription(
            engine=engine,
            stream_category="stream_reconcile",
            handler=AlwaysFailHandler,
            max_retries=1,
            retry_delay_seconds=0,
        )
        await sub.initialize()

        broker = test_domain.brokers["default"]
        group_key = f"stream_reconcile:{sub.consumer_group}"
        assert group_key in broker._subscription_owned_groups

    @pytest.mark.asyncio
    async def test_persistent_dlq_outage_holds_never_native_dlq(
        self, test_domain, monkeypatch
    ):
        """Under a persistent DLQ outage a StreamSubscription-consumed message is
        held, never dead-lettered, then lands in {stream}:dlq on recovery.

        This is the same guarantee as BrokerSubscription, on the default
        subscription type named in the issue.
        """
        from protean.server.subscription.stream_subscription import StreamSubscription

        engine = Engine(test_domain, test_mode=True)
        sub = StreamSubscription(
            engine=engine,
            stream_category="stream_reconcile",
            handler=AlwaysFailHandler,
            max_retries=1,
            retry_delay_seconds=0,
        )
        await sub.initialize()

        broker = test_domain.brokers["default"]
        monkeypatch.setattr(broker, "_max_retries", 1)
        monkeypatch.setattr(broker, "_retry_delay", 0)

        real_publish = broker.publish

        def faulty_publish(stream, message):
            if stream == sub.dlq_stream:
                raise RuntimeError("DLQ down")
            return real_publish(stream, message)

        monkeypatch.setattr(broker, "publish", faulty_publish)

        identifier = "stream-persistent-1"
        payload = {"data": "x"}
        group = sub.consumer_group

        def reseed_in_flight():
            broker._message_ownership[identifier][group] = True
            broker._clear_operation_state(group, identifier)
            broker._store_in_flight_message(
                "stream_reconcile", group, identifier, payload
            )

        for _ in range(broker._max_retries + 5):
            reseed_in_flight()
            await sub.handle_failed_message(identifier, payload)

        # Never routed to the broker's native DLQ, and never to {stream}:dlq
        # (publish failed every round). It is held.
        assert len(broker._messages.get(sub.dlq_stream, [])) == 0
        native_dlq = broker.get_dlq_messages(group, "stream_reconcile")
        native_ids = [e[0] for entries in native_dlq.values() for e in entries]
        assert identifier not in native_ids
        group_key = f"stream_reconcile:{group}"
        assert identifier in [e[0] for e in broker._failed_messages[group_key]]
        assert identifier in sub.retry_counts

        # Recovery: lift the outage, run one more cycle. It lands in {stream}:dlq,
        # the native DLQ stays empty, and the retry count clears.
        monkeypatch.setattr(broker, "publish", real_publish)
        reseed_in_flight()
        await sub.handle_failed_message(identifier, payload)

        assert len(broker._messages.get(sub.dlq_stream, [])) == 1
        native_dlq = broker.get_dlq_messages(group, "stream_reconcile")
        native_ids = [e[0] for entries in native_dlq.values() for e in entries]
        assert identifier not in native_ids
        assert identifier not in sub.retry_counts


# ── Tests: EventStoreSubscription failed position tracking ──────────────


class TestEventStoreSubscriptionIntegration:
    """EventStoreSubscription handler failure → failed position → recovery."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(DLQTestAggregate)
        test_domain.register(DLQTestEvent, part_of=DLQTestAggregate)
        test_domain.register(AlwaysFailHandler, part_of=DLQTestAggregate)
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_handler_failure_records_failed_position(self, test_domain):
        """When a handler fails, the position is recorded as failed."""
        engine = Engine(test_domain, test_mode=True)

        from protean.server.subscription.event_store_subscription import (
            EventStoreSubscription,
        )

        sub = EventStoreSubscription(
            engine=engine,
            stream_category="dlq_test_aggregate",
            handler=AlwaysFailHandler,
            max_retries=2,
            retry_delay_seconds=0,
        )

        # Simulate a failed message
        await sub._record_failed_position(
            position=42,
            message_type="DLQTestEvent",
            message_id="evt-123",
            stream_name="dlq_test_aggregate-123",
            stream_position=10,
        )

        # Check that the failed position is tracked (keyed by global position)
        assert 42 in sub._failed_positions
        fp = sub._failed_positions[42]
        assert fp["stream_position"] == 10
        assert fp["retry_count"] == 0

    @pytest.mark.asyncio
    async def test_multiple_failures_tracked_independently(self, test_domain):
        """Multiple failed positions are tracked independently."""
        engine = Engine(test_domain, test_mode=True)

        from protean.server.subscription.event_store_subscription import (
            EventStoreSubscription,
        )

        sub = EventStoreSubscription(
            engine=engine,
            stream_category="dlq_test_aggregate",
            handler=AlwaysFailHandler,
            max_retries=3,
            retry_delay_seconds=0,
        )

        # Record two different failed positions
        await sub._record_failed_position(
            position=10,
            message_type="DLQTestEvent",
            message_id="evt-1",
            stream_name="dlq_test_aggregate-a",
            stream_position=5,
        )
        await sub._record_failed_position(
            position=20,
            message_type="DLQTestEvent",
            message_id="evt-2",
            stream_name="dlq_test_aggregate-b",
            stream_position=8,
        )

        assert len(sub._failed_positions) == 2
        assert 10 in sub._failed_positions
        assert 20 in sub._failed_positions
        assert sub._failed_positions[10]["stream_name"] == "dlq_test_aggregate-a"
        assert sub._failed_positions[20]["stream_name"] == "dlq_test_aggregate-b"


# ── Tests: DLQ Discovery across subscription types ──────────────────────


@pytest.mark.no_test_domain
class TestDLQDiscoveryIntegration:
    """DLQ discovery finds subscriptions from all handler types."""

    def test_discovers_event_handlers(self):
        domain = Domain(__file__, "DiscoverEvents")

        @domain.aggregate
        class Widget:
            name: str

        @domain.event(part_of=Widget)
        class WidgetCreated:
            name: str

        @domain.event_handler(part_of=Widget)
        class WidgetHandler:
            pass

        domain.init()

        infos = discover_subscriptions(domain)
        handler_names = [i.handler_name for i in infos]
        assert any("WidgetHandler" in n for n in handler_names)

    def test_discovers_command_handlers(self):
        domain = Domain(__file__, "DiscoverCommands")

        @domain.aggregate
        class Gadget:
            name: str

        @domain.command(part_of=Gadget)
        class CreateGadget:
            name: str

        @domain.command_handler(part_of=Gadget)
        class GadgetCommandHandler:
            pass

        domain.init()

        infos = discover_subscriptions(domain)
        handler_names = [i.handler_name for i in infos]
        assert any("GadgetCommandHandler" in n for n in handler_names)

    def test_discovers_subscribers(self):
        domain = Domain(__file__, "DiscoverSubs")

        class WebhookSub(BaseSubscriber):
            def __call__(self, data: dict):
                pass

        domain.register(WebhookSub, stream="webhooks")
        domain.init(traverse=False)

        infos = discover_subscriptions(domain)
        handler_names = [i.handler_name for i in infos]
        assert any("WebhookSub" in n for n in handler_names)

    def test_collect_dlq_streams_all_types(self):
        """collect_dlq_streams returns DLQ streams for all subscription types."""
        domain = Domain(__file__, "CollectAll")

        @domain.aggregate
        class Thing:
            name: str

        @domain.event(part_of=Thing)
        class ThingCreated:
            name: str

        @domain.event_handler(part_of=Thing)
        class ThingHandler:
            pass

        class ExternalSub(BaseSubscriber):
            def __call__(self, data: dict):
                pass

        domain.register(ExternalSub, stream="external_events")
        domain.init()

        streams = collect_dlq_streams(domain)
        assert len(streams) >= 2
        assert all(s.endswith(":dlq") for s in streams)
        assert "external_events:dlq" in streams

    def test_priority_lanes_adds_backfill_dlq(self):
        """When priority lanes enabled, backfill DLQ streams are included."""
        domain = Domain(__file__, "LanesInteg")
        domain.config["server"] = {
            "priority_lanes": {
                "enabled": True,
                "backfill_suffix": "backfill",
            }
        }

        @domain.aggregate
        class Item:
            name: str

        @domain.event(part_of=Item)
        class ItemAdded:
            name: str

        @domain.event_handler(part_of=Item)
        class ItemHandler:
            pass

        domain.init()

        streams = collect_dlq_streams(domain)
        backfill_streams = [s for s in streams if ":backfill:dlq" in s]
        assert len(backfill_streams) >= 1


# ── Tests: InlineBroker Internal DLQ Operations ─────────────────────────


class TestInlineBrokerDLQOperations:
    """Test InlineBroker's built-in DLQ management (list, inspect, replay, purge)."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(FailingSubscriber, stream="broker_dlq_test")
        test_domain.init(traverse=False)

    def _populate_broker_dlq(self, broker, stream, consumer_group, count=3):
        """Put messages into the broker's internal DLQ."""
        for i in range(count):
            identifier = f"msg-{i}"
            message = {"data": f"payload-{i}", "index": i}
            broker._store_dlq_message(
                stream, consumer_group, identifier, message, "test_failure"
            )

    def test_dlq_list_returns_entries(self, test_domain):
        """broker.dlq_list() returns DLQ entries."""
        broker = test_domain.brokers["default"]
        self._populate_broker_dlq(broker, "broker_dlq_test", "test_group", count=3)

        entries = broker.dlq_list(["broker_dlq_test:dlq"], limit=10)
        assert len(entries) == 3
        assert all(e.stream == "broker_dlq_test" for e in entries)
        assert all(e.dlq_stream == "broker_dlq_test:dlq" for e in entries)

    def test_dlq_inspect_returns_entry(self, test_domain):
        """broker.dlq_inspect() returns a specific entry by ID."""
        broker = test_domain.brokers["default"]
        self._populate_broker_dlq(broker, "broker_dlq_test", "test_group", count=1)

        entries = broker.dlq_list(["broker_dlq_test:dlq"], limit=10)
        assert len(entries) == 1
        dlq_id = entries[0].dlq_id

        entry = broker.dlq_inspect("broker_dlq_test:dlq", dlq_id)
        assert entry is not None
        assert entry.dlq_id == dlq_id
        assert entry.payload["data"] == "payload-0"

    def test_dlq_inspect_not_found(self, test_domain):
        """broker.dlq_inspect() returns None for unknown ID."""
        broker = test_domain.brokers["default"]
        entry = broker.dlq_inspect("broker_dlq_test:dlq", "nonexistent")
        assert entry is None

    def test_dlq_replay_single_message(self, test_domain):
        """broker.dlq_replay() moves message back to original stream."""
        broker = test_domain.brokers["default"]
        self._populate_broker_dlq(broker, "broker_dlq_test", "test_group", count=2)

        entries = broker.dlq_list(["broker_dlq_test:dlq"], limit=10)
        dlq_id = entries[0].dlq_id

        result = broker.dlq_replay("broker_dlq_test:dlq", dlq_id, "broker_dlq_test")
        assert result is True

        # One fewer in DLQ
        remaining = broker.dlq_list(["broker_dlq_test:dlq"], limit=10)
        assert len(remaining) == 1

        # Message republished to original stream
        assert len(broker._messages["broker_dlq_test"]) >= 1

    def test_dlq_replay_all(self, test_domain):
        """broker.dlq_replay_all() replays all messages from a DLQ stream."""
        broker = test_domain.brokers["default"]
        self._populate_broker_dlq(broker, "broker_dlq_test", "test_group", count=3)

        count = broker.dlq_replay_all("broker_dlq_test:dlq", "broker_dlq_test")
        assert count == 3

        # DLQ is empty
        remaining = broker.dlq_list(["broker_dlq_test:dlq"], limit=10)
        assert len(remaining) == 0

    def test_dlq_purge(self, test_domain):
        """broker.dlq_purge() clears all messages from a DLQ stream."""
        broker = test_domain.brokers["default"]
        self._populate_broker_dlq(broker, "broker_dlq_test", "test_group", count=5)

        count = broker.dlq_purge("broker_dlq_test:dlq")
        assert count == 5

        remaining = broker.dlq_list(["broker_dlq_test:dlq"], limit=10)
        assert len(remaining) == 0

    def test_dlq_purge_empty_stream(self, test_domain):
        """Purging an empty DLQ returns 0."""
        broker = test_domain.brokers["default"]
        count = broker.dlq_purge("nonexistent:dlq")
        assert count == 0

    def test_dlq_list_with_limit(self, test_domain):
        """broker.dlq_list() respects the limit parameter."""
        broker = test_domain.brokers["default"]
        self._populate_broker_dlq(broker, "broker_dlq_test", "test_group", count=10)

        entries = broker.dlq_list(["broker_dlq_test:dlq"], limit=3)
        assert len(entries) == 3

    def test_dlq_list_multiple_streams(self, test_domain):
        """broker.dlq_list() aggregates entries across multiple DLQ streams."""
        broker = test_domain.brokers["default"]
        self._populate_broker_dlq(broker, "stream_a", "group_a", count=2)
        self._populate_broker_dlq(broker, "stream_b", "group_b", count=3)

        entries = broker.dlq_list(["stream_a:dlq", "stream_b:dlq"], limit=100)
        assert len(entries) == 5

        streams = {e.dlq_stream for e in entries}
        assert "stream_a:dlq" in streams
        assert "stream_b:dlq" in streams


# ── Tests: Engine Error Resilience ──────────────────────────────────────


class TestEngineErrorResilience:
    """Engine continues processing after handler/subscriber failures."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(DLQTestAggregate)
        test_domain.register(DLQTestEvent, part_of=DLQTestAggregate)
        test_domain.register(AlwaysFailHandler, part_of=DLQTestAggregate)
        test_domain.register(FailingSubscriber, stream="resilience_test")
        test_domain.init(traverse=False)

    @pytest.mark.asyncio
    async def test_engine_continues_after_handler_failure(self, test_domain):
        """Engine.handle_message returns False but doesn't crash."""
        from protean.utils.eventing import Message

        engine = Engine(test_domain, test_mode=True)

        event = DLQTestEvent(name="test")
        msg = Message.from_domain_object(event)

        result = await engine.handle_message(AlwaysFailHandler, msg)
        assert result is False
        assert engine.shutting_down is False

    @pytest.mark.asyncio
    async def test_engine_continues_after_subscriber_failure(self, test_domain):
        """Engine.handle_broker_message returns False but doesn't crash."""
        engine = Engine(test_domain, test_mode=True)

        result = await engine.handle_broker_message(
            FailingSubscriber,
            {"data": "test"},
            message_id="fail-1",
            stream="resilience_test",
        )
        assert result is False
        assert engine.shutting_down is False

    @pytest.mark.asyncio
    async def test_handle_error_callback_invoked(self, test_domain, caplog):
        """Subscriber.handle_error() is called on failure."""

        class ErrorTrackingSubscriber(BaseSubscriber):
            error_received = None

            def __call__(self, data: dict):
                raise ValueError("tracked error")

            @classmethod
            def handle_error(cls, exc, message):
                cls.error_received = exc

        test_domain.register(ErrorTrackingSubscriber, stream="error_track")
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        await engine.handle_broker_message(
            ErrorTrackingSubscriber,
            {"data": "trigger"},
            message_id="err-1",
            stream="error_track",
        )

        assert ErrorTrackingSubscriber.error_received is not None
        assert isinstance(ErrorTrackingSubscriber.error_received, ValueError)

    @pytest.mark.asyncio
    async def test_handle_error_exception_caught(self, test_domain, caplog):
        """If handle_error() itself raises, the engine still continues."""

        class BrokenErrorHandler(BaseSubscriber):
            def __call__(self, data: dict):
                raise RuntimeError("primary failure")

            @classmethod
            def handle_error(cls, exc, message):
                raise RuntimeError("error handler also broken")

        test_domain.register(BrokenErrorHandler, stream="broken_error")
        test_domain.init(traverse=False)

        engine = Engine(test_domain, test_mode=True)

        with caplog.at_level(logging.ERROR):
            result = await engine.handle_broker_message(
                BrokenErrorHandler,
                {"data": "x"},
                message_id="brk-1",
                stream="broken_error",
            )

        assert result is False
        assert engine.shutting_down is False
        assert "broker.error_handler_failed" in caplog.text
