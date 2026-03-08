"""Tests for StreamSubscription error handling — retry, DLQ, traces, priority lanes.

Fills gaps identified in step 10 of issue #489. Uses a FakeBroker to avoid
requiring Redis, since the internal retry/DLQ logic operates on the broker
interface (ack, nack, publish) without needing Redis Streams.
"""

import logging
from unittest.mock import MagicMock

import pytest

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.server.subscription.stream_subscription import StreamSubscription


# ── Domain elements ─────────────────────────────────────────────────────

handler_counter = 0


class StreamTestAggregate(BaseAggregate):
    test_id: Identifier(required=True)
    message: String()


class StreamTestEvent(BaseEvent):
    test_id: Identifier(required=True)
    message: String()


class SucceedingHandler(BaseEventHandler):
    @handle(StreamTestEvent)
    def handle_event(self, event):
        global handler_counter
        handler_counter += 1


class AlwaysFailingHandler(BaseEventHandler):
    @handle(StreamTestEvent)
    def handle_event(self, event):
        global handler_counter
        handler_counter += 1
        raise RuntimeError("Always fails")


# ── Fake broker ──────────────────────────────────────────────────────────


class FakeBroker:
    """Minimal broker stub for testing retry/DLQ logic."""

    def __init__(self):
        self.acked: list[tuple] = []
        self.nacked: list[tuple] = []
        self.published: list[tuple] = []

    def _ensure_group(self, consumer_group, stream):
        pass

    def ack(self, stream, identifier, consumer_group):
        self.acked.append((stream, identifier, consumer_group))
        return True

    def nack(self, stream, identifier, consumer_group):
        self.nacked.append((stream, identifier, consumer_group))
        return True

    def publish(self, stream, message):
        self.published.append((stream, message))
        return "dlq-id"


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_counters():
    global handler_counter
    handler_counter = 0


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(StreamTestAggregate)
    test_domain.register(StreamTestEvent, part_of=StreamTestAggregate)
    test_domain.register(SucceedingHandler, part_of=StreamTestAggregate)
    test_domain.register(AlwaysFailingHandler, part_of=StreamTestAggregate)
    test_domain.init(traverse=False)


def _make_subscription(
    test_domain,
    handler_cls,
    max_retries: int = 3,
    retry_delay_seconds: float = 0,
    enable_dlq: bool = True,
    lanes_enabled: bool = False,
) -> StreamSubscription:
    """Create a StreamSubscription with a FakeBroker attached."""
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
    sub.broker = FakeBroker()
    return sub


# ── Tests: Full retry → DLQ round-trip ──────────────────────────────────


class TestRetryToDLQRoundTrip:
    """Full retry pipeline: fail N times → NACKs → DLQ → ACK."""

    @pytest.mark.asyncio
    async def test_full_3_retry_to_dlq(self, test_domain):
        """Message NACKed 2 times, then moved to DLQ on 3rd failure."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=3)

        identifier = "msg-round-trip"
        payload = {"data": "important"}

        # Failures 1 and 2 → NACK
        await sub.handle_failed_message(identifier, payload)
        assert sub.retry_counts[identifier] == 1
        assert len(sub.broker.nacked) == 1
        assert len(sub.broker.published) == 0

        await sub.handle_failed_message(identifier, payload)
        assert sub.retry_counts[identifier] == 2
        assert len(sub.broker.nacked) == 2
        assert len(sub.broker.published) == 0

        # Failure 3 → DLQ + ACK
        await sub.handle_failed_message(identifier, payload)
        assert identifier not in sub.retry_counts
        assert len(sub.broker.published) == 1
        assert sub.broker.published[0][0] == "test_stream:dlq"
        assert len(sub.broker.acked) == 1

    @pytest.mark.asyncio
    async def test_max_retries_1_single_retry(self, test_domain):
        """With max_retries=1, first failure exhausts immediately."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=1)

        await sub.handle_failed_message("msg1", {"data": "x"})

        # Immediate DLQ (retry_count=1 >= max_retries=1)
        assert "msg1" not in sub.retry_counts
        assert len(sub.broker.published) == 1
        assert sub.broker.published[0][0] == "test_stream:dlq"

    @pytest.mark.asyncio
    async def test_retry_count_in_dlq_metadata(self, test_domain):
        """DLQ message contains correct retry_count in _dlq_metadata."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=2)

        # 2 failures → DLQ
        await sub.handle_failed_message("msg1", {"data": "x"})
        await sub.handle_failed_message("msg1", {"data": "x"})

        dlq_msg = sub.broker.published[0][1]
        assert dlq_msg["_dlq_metadata"]["retry_count"] == 2
        assert dlq_msg["_dlq_metadata"]["original_stream"] == "test_stream"
        assert dlq_msg["_dlq_metadata"]["original_id"] == "msg1"
        assert dlq_msg["_dlq_metadata"]["consumer_group"] == sub.consumer_group
        assert dlq_msg["_dlq_metadata"]["consumer"] == sub.consumer_name

    @pytest.mark.asyncio
    async def test_retry_count_cleared_on_ack(self, test_domain):
        """Successful ACK clears the retry count for a message."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=5)

        # One failure → retry count = 1
        await sub.handle_failed_message("msg1", {"data": "x"})
        assert sub.retry_counts["msg1"] == 1

        # Acknowledge (simulating success on re-delivery)
        await sub._acknowledge_message("msg1")

        assert "msg1" not in sub.retry_counts


# ── Tests: Priority Lanes DLQ Routing ────────────────────────────────────


class TestPriorityLanesDLQ:
    """Messages from backfill stream route to backfill DLQ."""

    @pytest.mark.asyncio
    async def test_primary_stream_routes_to_primary_dlq(self, test_domain):
        """Primary stream messages go to stream:dlq."""
        sub = _make_subscription(
            test_domain, AlwaysFailingHandler, max_retries=1, lanes_enabled=True
        )

        await sub.handle_failed_message("msg1", {"data": "x"}, stream="test_stream")

        assert sub.broker.published[0][0] == "test_stream:dlq"

    @pytest.mark.asyncio
    async def test_backfill_stream_routes_to_backfill_dlq(self, test_domain):
        """Backfill stream messages go to stream:backfill:dlq."""
        sub = _make_subscription(
            test_domain, AlwaysFailingHandler, max_retries=1, lanes_enabled=True
        )

        await sub.handle_failed_message(
            "msg1", {"data": "x"}, stream=sub.backfill_stream
        )

        assert sub.broker.published[0][0] == "test_stream:backfill:dlq"

    @pytest.mark.asyncio
    async def test_dlq_metadata_preserves_original_stream(self, test_domain):
        """DLQ metadata original_stream matches the source stream (backfill)."""
        sub = _make_subscription(
            test_domain, AlwaysFailingHandler, max_retries=1, lanes_enabled=True
        )

        await sub.handle_failed_message(
            "msg1", {"data": "x"}, stream=sub.backfill_stream
        )

        dlq_msg = sub.broker.published[0][1]
        assert dlq_msg["_dlq_metadata"]["original_stream"] == sub.backfill_stream


# ── Tests: Trace Events ──────────────────────────────────────────────────


class TestTraceEvents:
    """Verify trace event emission for ack, nack, and DLQ."""

    @pytest.mark.asyncio
    async def test_message_nacked_trace_on_retry(self, test_domain):
        """message.nacked trace emitted when retrying."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=3)
        sub.engine.emitter = MagicMock()

        await sub.handle_failed_message("msg1", {"data": "x"})

        sub.engine.emitter.emit.assert_called_once()
        kwargs = sub.engine.emitter.emit.call_args.kwargs
        assert kwargs["event"] == "message.nacked"
        assert kwargs["stream"] == "test_stream"
        assert kwargs["message_id"] == "msg1"
        assert kwargs["status"] == "retry"
        assert kwargs["metadata"]["retry_count"] == 1
        assert kwargs["metadata"]["max_retries"] == 3

    @pytest.mark.asyncio
    async def test_message_dlq_trace_on_exhaustion(self, test_domain):
        """message.dlq trace emitted when moved to DLQ."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=1)
        sub.engine.emitter = MagicMock()

        await sub.handle_failed_message("msg1", {"data": "x"})

        calls = sub.engine.emitter.emit.call_args_list
        assert len(calls) == 1
        kwargs = calls[0].kwargs
        assert kwargs["event"] == "message.dlq"
        assert kwargs["stream"] == "test_stream"
        assert kwargs["metadata"]["dlq_stream"] == "test_stream:dlq"

    @pytest.mark.asyncio
    async def test_message_acked_trace_on_success(self, test_domain):
        """message.acked trace emitted on successful ACK."""
        from protean.utils.eventing import Message

        sub = _make_subscription(test_domain, SucceedingHandler)
        sub.engine.emitter = MagicMock()

        # Create a proper Message for the trace
        from uuid import uuid4

        event = StreamTestEvent(test_id=str(uuid4()), message="test")
        msg = Message.from_domain_object(event)

        await sub._acknowledge_message("msg1", message=msg, stream="test_stream")

        sub.engine.emitter.emit.assert_called_once()
        kwargs = sub.engine.emitter.emit.call_args.kwargs
        assert kwargs["event"] == "message.acked"
        assert kwargs["stream"] == "test_stream"
        assert kwargs["handler"] == "SucceedingHandler"


# ── Tests: Deserialization → DLQ ─────────────────────────────────────────


class TestDeserializationDLQ:
    """Invalid messages go directly to DLQ (no retry)."""

    @pytest.mark.asyncio
    async def test_invalid_payload_moves_to_dlq(self, test_domain):
        """Malformed payload deserialization failure routes to DLQ."""
        sub = _make_subscription(test_domain, SucceedingHandler)

        result = await sub._deserialize_message(
            "bad-msg", {"not": "a valid message"}, "test_stream"
        )

        assert result is None
        assert len(sub.broker.published) == 1
        assert sub.broker.published[0][0] == "test_stream:dlq"

    @pytest.mark.asyncio
    async def test_deserialization_dlq_preserves_original_payload(self, test_domain):
        """DLQ message preserves the original invalid payload."""
        sub = _make_subscription(test_domain, SucceedingHandler)

        payload = {"corrupt": "data", "extra": 42}
        await sub._deserialize_message("bad-msg", payload, "test_stream")

        dlq_msg = sub.broker.published[0][1]
        assert dlq_msg["corrupt"] == "data"
        assert dlq_msg["extra"] == 42
        assert "_dlq_metadata" in dlq_msg

    @pytest.mark.asyncio
    async def test_deserialization_failure_no_retry(self, test_domain):
        """Deserialization failures go straight to DLQ — no retry tracking."""
        sub = _make_subscription(test_domain, SucceedingHandler)

        await sub._deserialize_message("bad-msg", {"bad": True}, "test_stream")

        # No retry count recorded
        assert "bad-msg" not in sub.retry_counts


# ── Tests: DLQ Disabled ──────────────────────────────────────────────────


class TestDLQDisabled:
    """Behavior when enable_dlq=False."""

    @pytest.mark.asyncio
    async def test_move_to_dlq_returns_none_when_disabled(self, test_domain):
        """move_to_dlq is a no-op when DLQ is disabled."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, enable_dlq=False)

        result = await sub.move_to_dlq("msg1", {"data": "x"})

        assert result is None
        assert len(sub.broker.published) == 0

    @pytest.mark.asyncio
    async def test_exhaust_retries_still_acks_when_dlq_disabled(self, test_domain):
        """Even without DLQ, exhausted messages are ACKed to clear pending."""
        sub = _make_subscription(
            test_domain, AlwaysFailingHandler, max_retries=1, enable_dlq=False
        )

        await sub.handle_failed_message("msg1", {"data": "x"})

        # No DLQ publish
        assert len(sub.broker.published) == 0
        # But message was ACKed
        assert len(sub.broker.acked) == 1
        # And retry count cleared
        assert "msg1" not in sub.retry_counts


# ── Tests: DLQ Publish Failure ───────────────────────────────────────────


class TestDLQPublishFailure:
    """DLQ publish exceptions are caught gracefully."""

    @pytest.mark.asyncio
    async def test_dlq_publish_exception_logged(self, test_domain, caplog):
        """Exception during DLQ publish is caught and logged."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=1)
        sub.broker.publish = MagicMock(side_effect=Exception("Broker down"))

        with caplog.at_level(logging.ERROR):
            await sub.handle_failed_message("msg1", {"data": "x"})

        assert "Failed to move message msg1 to DLQ" in caplog.text


# ── Tests: Configuration ─────────────────────────────────────────────────


class TestConfiguration:
    """Configuration defaults and overrides."""

    def test_default_config_values(self, test_domain):
        """StreamSubscription picks up defaults from config."""
        engine = Engine(test_domain, test_mode=True)
        sub = StreamSubscription(
            engine=engine, stream_category="test", handler=SucceedingHandler
        )

        assert sub.max_retries == 3
        assert sub.retry_delay_seconds == 1.0
        assert sub.enable_dlq is True

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

    def test_dlq_and_backfill_stream_naming(self, test_domain):
        """DLQ and backfill stream names follow convention."""
        engine = Engine(test_domain, test_mode=True)
        sub = StreamSubscription(
            engine=engine, stream_category="orders", handler=SucceedingHandler
        )

        assert sub.dlq_stream == "orders:dlq"
        assert sub.backfill_dlq_stream == "orders:backfill:dlq"
