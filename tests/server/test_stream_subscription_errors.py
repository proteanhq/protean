"""Tests for StreamSubscription error handling — retry, DLQ, traces, priority lanes.

The retry/DLQ logic only needs the broker interface (ack, nack, publish), so
these tests run on the domain's inline broker. Each test publishes a message,
reads it back for the subscription's consumer group, and checks the outcome on
the broker: an ACKed message is gone, a NACKed one is delivered again on the
next read, and a dead-lettered one is on the DLQ stream.
"""

import logging
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.server.subscription.stream_subscription import StreamSubscription
from protean.utils.eventing import Message

# ── Domain elements ─────────────────────────────────────────────────────


class StreamTestAggregate(BaseAggregate):
    test_id: Identifier(required=True)
    message: String()


class StreamTestEvent(BaseEvent):
    test_id: Identifier(required=True)
    message: String()


class SucceedingHandler(BaseEventHandler):
    @handle(StreamTestEvent)
    def handle_event(self, event):
        pass


class AlwaysFailingHandler(BaseEventHandler):
    @handle(StreamTestEvent)
    def handle_event(self, event):
        raise RuntimeError("Always fails")


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(StreamTestAggregate)
    test_domain.register(StreamTestEvent, part_of=StreamTestAggregate)
    test_domain.register(SucceedingHandler, part_of=StreamTestAggregate)
    test_domain.register(AlwaysFailingHandler, part_of=StreamTestAggregate)
    test_domain.init(traverse=False)


@pytest.fixture
def broker(test_domain, monkeypatch):
    """The domain's inline broker, set to redeliver a NACKed message at once."""
    broker = test_domain.brokers["default"]
    monkeypatch.setattr(broker, "_retry_delay", 0)
    return broker


def _make_subscription(
    test_domain,
    handler_cls,
    max_retries: int = 3,
    retry_delay_seconds: float = 0,
    enable_dlq: bool = True,
    lanes_enabled: bool = False,
) -> StreamSubscription:
    """Create a StreamSubscription on the domain's broker."""
    engine = Engine(test_domain, test_mode=True)

    if lanes_enabled:
        test_domain.config["server"]["priority_lanes"] = {
            "enabled": True,
            "backfill_suffix": "backfill",
        }

    sub = StreamSubscription(
        engine=engine,
        stream_category="test_stream",
        handler=handler_cls,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
        enable_dlq=enable_dlq,
    )
    sub.broker = test_domain.brokers["default"]
    return sub


def _read_ids(sub, stream: str | None = None) -> list[str]:
    """Read every message waiting on ``stream`` for the subscription's group."""
    messages = sub.broker.read(stream or sub.stream_category, sub.consumer_group, 10)
    return [identifier for identifier, _ in messages]


def _deliver(sub, payload: dict, stream: str | None = None) -> str:
    """Publish ``payload`` and read it back as the subscription; return its id."""
    stream = stream or sub.stream_category
    sub.broker.publish(stream, payload)
    [identifier] = _read_ids(sub, stream)
    return identifier


def _dlq(sub, dlq_stream: str) -> list[dict]:
    return [payload for _, payload in sub.broker.read(dlq_stream, "inspector", 10)]


def _in_flight(sub, stream: str) -> int:
    groups = sub.broker.info()["consumer_groups"]
    return groups[sub.consumer_group]["in_flight_messages"][stream]


def _publish_fails(broker, monkeypatch, times: int | None = None) -> None:
    """Make DLQ publishes raise, for the first ``times`` calls or for all."""
    real_publish = broker.publish
    calls = {"count": 0}

    def publish(stream, message):
        calls["count"] += 1
        if times is None or calls["count"] <= times:
            raise Exception("Broker down")
        return real_publish(stream, message)

    monkeypatch.setattr(broker, "publish", publish)


# ── Tests: blocking timeout checked at construction ─────────────────────


class TestBlockingTimeoutAtConstruction:
    """The constructor rejects a non-positive wait however the value reaches it."""

    @pytest.mark.parametrize("timeout_ms", [0, -1])
    def test_argument_must_be_positive(self, test_domain, timeout_ms):
        with pytest.raises(ConfigurationError, match="must be positive"):
            StreamSubscription(
                engine=Engine(test_domain, test_mode=True),
                stream_category="test_stream",
                handler=SucceedingHandler,
                blocking_timeout_ms=timeout_ms,
            )

    def test_server_config_value_must_be_positive(self, test_domain):
        test_domain.config["server"]["stream_subscription"]["blocking_timeout_ms"] = 0
        with pytest.raises(ConfigurationError, match="must be positive"):
            StreamSubscription(
                engine=Engine(test_domain, test_mode=True),
                stream_category="test_stream",
                handler=SucceedingHandler,
            )

    def test_positive_value_is_kept(self, test_domain):
        sub = StreamSubscription(
            engine=Engine(test_domain, test_mode=True),
            stream_category="test_stream",
            handler=SucceedingHandler,
            blocking_timeout_ms=1,
        )
        assert sub.blocking_timeout_ms == 1


# ── Tests: Full retry → DLQ round-trip ──────────────────────────────────


class TestRetryToDLQRoundTrip:
    """Full retry pipeline: fail N times → NACKs → DLQ → ACK."""

    @pytest.mark.asyncio
    async def test_full_3_retry_to_dlq(self, test_domain, broker):
        """Message NACKed 2 times, then moved to DLQ on 3rd failure."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=3)
        payload = {"data": "important"}
        identifier = _deliver(sub, payload)

        # Failures 1 and 2 → NACK, so the message comes back on the next read
        for attempt in (1, 2):
            await sub.handle_failed_message(identifier, payload)
            assert sub.retry_counts[identifier] == attempt
            assert _dlq(sub, "test_stream:dlq") == []
            assert _read_ids(sub) == [identifier]

        # Failure 3 → DLQ + ACK
        await sub.handle_failed_message(identifier, payload)
        assert identifier not in sub.retry_counts
        [dlq_msg] = _dlq(sub, "test_stream:dlq")
        assert dlq_msg["data"] == "important"
        assert dlq_msg["_dlq_metadata"]["retry_count"] == 3
        assert dlq_msg["_dlq_metadata"]["original_stream"] == "test_stream"
        assert dlq_msg["_dlq_metadata"]["original_id"] == identifier
        assert dlq_msg["_dlq_metadata"]["consumer_group"] == sub.consumer_group
        assert dlq_msg["_dlq_metadata"]["consumer"] == sub.consumer_name
        assert _read_ids(sub) == []
        assert _in_flight(sub, "test_stream") == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("lanes_enabled", [False, True])
    async def test_max_retries_1_single_retry(self, test_domain, broker, lanes_enabled):
        """With max_retries=1, first failure exhausts immediately, and a primary
        stream message goes to stream:dlq with or without priority lanes."""
        sub = _make_subscription(
            test_domain,
            AlwaysFailingHandler,
            max_retries=1,
            lanes_enabled=lanes_enabled,
        )
        identifier = _deliver(sub, {"data": "x"})

        await sub.handle_failed_message(identifier, {"data": "x"}, stream="test_stream")

        # Immediate DLQ (retry_count=1 >= max_retries=1)
        assert identifier not in sub.retry_counts
        assert len(_dlq(sub, "test_stream:dlq")) == 1

    @pytest.mark.asyncio
    async def test_retry_count_cleared_on_ack(self, test_domain, broker):
        """Successful ACK clears the retry count for a message."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=5)
        identifier = _deliver(sub, {"data": "x"})

        # One failure → retry count = 1
        await sub.handle_failed_message(identifier, {"data": "x"})
        assert sub.retry_counts[identifier] == 1

        # Acknowledge the redelivery (simulating success)
        assert _read_ids(sub) == [identifier]
        assert await sub._acknowledge_message(identifier) is True

        assert identifier not in sub.retry_counts
        assert _read_ids(sub) == []


# ── Tests: Priority Lanes DLQ Routing ────────────────────────────────────


class TestPriorityLanesDLQ:
    """Messages from backfill stream route to backfill DLQ."""

    @pytest.mark.asyncio
    async def test_backfill_stream_routes_to_backfill_dlq(self, test_domain, broker):
        """Backfill stream messages go to stream:backfill:dlq, and the DLQ
        metadata names the backfill stream as the source."""
        sub = _make_subscription(
            test_domain, AlwaysFailingHandler, max_retries=1, lanes_enabled=True
        )
        identifier = _deliver(sub, {"data": "x"}, stream=sub.backfill_stream)

        await sub.handle_failed_message(
            identifier, {"data": "x"}, stream=sub.backfill_stream
        )

        assert _dlq(sub, "test_stream:dlq") == []
        [dlq_msg] = _dlq(sub, "test_stream:backfill:dlq")
        assert dlq_msg["_dlq_metadata"]["original_stream"] == sub.backfill_stream


# ── Tests: Trace Events ──────────────────────────────────────────────────


class TestTraceEvents:
    """Verify trace event emission for ack, nack, and DLQ.

    The trace emitter publishes to Redis, so each test replaces it with a mock
    and reads the calls.
    """

    @pytest.mark.asyncio
    async def test_message_nacked_trace_on_retry(self, test_domain, broker):
        """message.nacked trace emitted when retrying."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=3)
        sub.engine.emitter = MagicMock()
        identifier = _deliver(sub, {"data": "x"})

        await sub.handle_failed_message(identifier, {"data": "x"})

        sub.engine.emitter.emit.assert_called_once()
        kwargs = sub.engine.emitter.emit.call_args.kwargs
        assert kwargs["event"] == "message.nacked"
        assert kwargs["stream"] == "test_stream"
        assert kwargs["message_id"] == identifier
        assert kwargs["status"] == "retry"
        assert kwargs["metadata"]["retry_count"] == 1
        assert kwargs["metadata"]["max_retries"] == 3

    @pytest.mark.asyncio
    async def test_message_dlq_trace_on_exhaustion(self, test_domain, broker):
        """message.dlq trace emitted when moved to DLQ."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=1)
        sub.engine.emitter = MagicMock()
        identifier = _deliver(sub, {"data": "x"})

        await sub.handle_failed_message(identifier, {"data": "x"})

        calls = sub.engine.emitter.emit.call_args_list
        assert len(calls) == 1
        kwargs = calls[0].kwargs
        assert kwargs["event"] == "message.dlq"
        assert kwargs["stream"] == "test_stream"
        assert kwargs["metadata"]["dlq_stream"] == "test_stream:dlq"

    @pytest.mark.asyncio
    async def test_message_acked_trace_on_success(self, test_domain, broker):
        """message.acked trace emitted on successful ACK."""
        sub = _make_subscription(test_domain, SucceedingHandler)
        sub.engine.emitter = MagicMock()
        msg = Message.from_domain_object(
            StreamTestEvent(test_id=str(uuid4()), message="test")
        )
        identifier = _deliver(sub, msg.to_dict())

        await sub._acknowledge_message(identifier, message=msg, stream="test_stream")

        sub.engine.emitter.emit.assert_called_once()
        kwargs = sub.engine.emitter.emit.call_args.kwargs
        assert kwargs["event"] == "message.acked"
        assert kwargs["stream"] == "test_stream"
        assert kwargs["handler"] == "SucceedingHandler"


# ── Tests: Deserialization → DLQ ─────────────────────────────────────────


class TestDeserializationDLQ:
    """Invalid messages go directly to DLQ (no retry)."""

    @pytest.mark.asyncio
    async def test_invalid_payload_moves_to_dlq(self, test_domain, broker):
        """A malformed payload goes straight to the DLQ with its original
        content, and no retry count is recorded."""
        sub = _make_subscription(test_domain, SucceedingHandler)
        payload = {"corrupt": "data", "extra": 42}
        identifier = _deliver(sub, payload)

        result = await sub._deserialize_message(identifier, payload, "test_stream")

        assert result is None
        [dlq_msg] = _dlq(sub, "test_stream:dlq")
        assert dlq_msg["corrupt"] == "data"
        assert dlq_msg["extra"] == 42
        assert "_dlq_metadata" in dlq_msg
        assert identifier not in sub.retry_counts


# ── Tests: DLQ Disabled ──────────────────────────────────────────────────


class TestDLQDisabled:
    """Behavior when enable_dlq=False."""

    @pytest.mark.asyncio
    async def test_exhaust_retries_still_acks_when_dlq_disabled(
        self, test_domain, broker
    ):
        """Even without DLQ, exhausted messages are ACKed to clear pending.
        move_to_dlq is a no-op that reports success (True), so the caller ACKs
        the discarded message rather than holding it."""
        sub = _make_subscription(
            test_domain, AlwaysFailingHandler, max_retries=1, enable_dlq=False
        )
        identifier = _deliver(sub, {"data": "x"})

        assert await sub.move_to_dlq(identifier, {"data": "x"}) is True
        await sub.handle_failed_message(identifier, {"data": "x"})

        # No DLQ publish
        assert _dlq(sub, "test_stream:dlq") == []
        # But message was ACKed
        assert _read_ids(sub) == []
        assert _in_flight(sub, "test_stream") == 0
        # And retry count cleared
        assert identifier not in sub.retry_counts


# ── Tests: DLQ Publish Failure ───────────────────────────────────────────


class TestDLQPublishFailure:
    """A failed DLQ publish holds the message for redelivery (issue #1263)."""

    @pytest.mark.asyncio
    async def test_message_reaches_dlq_after_transient_publish_failure(
        self, test_domain, broker, monkeypatch, caplog
    ):
        """A failed DLQ publish is logged and must NOT ACK the message: it NACKs
        and keeps the retry count, so the broker redelivers it. Once the DLQ
        publish succeeds on the redelivery it is moved to the DLQ and ACKed."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=1)
        identifier = _deliver(sub, {"data": "x"})
        _publish_fails(broker, monkeypatch, times=1)

        with caplog.at_level(logging.ERROR):
            await sub.handle_failed_message(identifier, {"data": "x"})

        assert f"Failed to move message {identifier} to DLQ" in caplog.text
        assert identifier in sub.retry_counts
        # Held, not acked: the NACK hands it back on the next read.
        assert _read_ids(sub) == [identifier]

        await sub.handle_failed_message(identifier, {"data": "x"})
        assert len(_dlq(sub, "test_stream:dlq")) == 1
        assert identifier not in sub.retry_counts
        assert _read_ids(sub) == []

    @pytest.mark.asyncio
    async def test_dlq_publish_failure_backs_off_before_holding(
        self, test_domain, broker, monkeypatch
    ):
        """The exhaust-path hold NACK backs off (retry_delay_seconds) first, so a
        downed DLQ is retried at the retry cadence rather than hammered at poll
        speed (the stream poll loop re-reads pending with no inter-poll delay)."""
        sub = _make_subscription(
            test_domain, AlwaysFailingHandler, max_retries=1, retry_delay_seconds=0.25
        )
        identifier = _deliver(sub, {"data": "x"})
        _publish_fails(broker, monkeypatch)

        sleeps: list[float] = []

        async def fake_sleep(delay):
            sleeps.append(delay)

        monkeypatch.setattr(
            "protean.server.subscription.stream_subscription.asyncio.sleep",
            fake_sleep,
        )

        await sub.handle_failed_message(identifier, {"data": "x"})

        # Backed off before holding, and still held (NACK, no ACK).
        assert 0.25 in sleeps
        assert _read_ids(sub) == [identifier]

    @pytest.mark.asyncio
    async def test_backfill_dlq_publish_failure_holds_on_backfill_stream(
        self, test_domain, broker, monkeypatch
    ):
        """A failed DLQ publish for a backfill-lane message NACKs on the backfill
        stream (not the primary), holding it for redelivery."""
        sub = _make_subscription(
            test_domain, AlwaysFailingHandler, max_retries=1, lanes_enabled=True
        )
        identifier = _deliver(sub, {"data": "x"}, stream=sub.backfill_stream)
        _publish_fails(broker, monkeypatch)

        await sub.handle_failed_message(
            identifier, {"data": "x"}, stream=sub.backfill_stream
        )

        assert _read_ids(sub, sub.backfill_stream) == [identifier]
        assert identifier in sub.retry_counts

    @pytest.mark.asyncio
    async def test_nack_failure_after_dlq_failure_is_logged(
        self, test_domain, broker, monkeypatch, caplog
    ):
        """If the hold NACK itself fails after a failed DLQ publish, it is logged
        and the message is still not ACKed."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=1)
        identifier = _deliver(sub, {"data": "x"})
        _publish_fails(broker, monkeypatch)
        monkeypatch.setattr(broker, "nack", MagicMock(return_value=False))

        with caplog.at_level(logging.WARNING):
            await sub.handle_failed_message(identifier, {"data": "x"})

        assert _in_flight(sub, "test_stream") == 1
        assert (
            f"Failed to NACK message {identifier} after a failed DLQ publish"
            in caplog.text
        )


# ── Tests: Configuration ─────────────────────────────────────────────────


class TestConfiguration:
    """Configuration defaults and overrides."""

    def test_default_config_values(self, test_domain):
        """StreamSubscription picks up defaults from config, and the DLQ and
        backfill stream names follow convention."""
        engine = Engine(test_domain, test_mode=True)
        sub = StreamSubscription(
            engine=engine, stream_category="orders", handler=SucceedingHandler
        )

        assert sub.max_retries == 3
        assert sub.retry_delay_seconds == 1.0
        assert sub.enable_dlq is True
        assert sub.dlq_stream == "orders:dlq"
        assert sub.backfill_dlq_stream == "orders:backfill:dlq"

    def test_constructor_overrides(self, test_domain):
        """Explicit constructor args override config."""
        engine = Engine(test_domain, test_mode=True)
        sub = StreamSubscription(
            engine=engine,
            stream_category="test",
            handler=SucceedingHandler,
            max_retries=10,
            retry_delay_seconds=5.0,
            enable_dlq=False,
        )

        assert sub.max_retries == 10
        assert sub.retry_delay_seconds == 5.0
        assert sub.enable_dlq is False
