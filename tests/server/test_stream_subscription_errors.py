"""Tests for StreamSubscription error handling — retry, DLQ, traces, priority lanes.

Uses a FakeBroker to avoid requiring Redis, since the internal retry/DLQ
logic operates on the broker interface (ack, nack, publish) without needing
Redis Streams.
"""

import logging
from unittest.mock import MagicMock

import pytest

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.server.subscription.stream_subscription import StreamSubscription
from tests.server.test_trace_correlation import _attach_recording_redis

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
    async def test_full_3_retry_to_dlq(self, test_domain):
        """Message NACKed 2 times, then moved to DLQ on 3rd failure."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=3)

        identifier = "msg-round-trip"
        payload = {"data": "important"}

        # Failures 1 and 2 → NACK
        await sub.handle_failed_message(identifier, payload)
        assert sub.retry_counts[f"test_stream:{identifier}"] == 1
        assert len(sub.broker.nacked) == 1
        assert len(sub.broker.published) == 0

        await sub.handle_failed_message(identifier, payload)
        assert sub.retry_counts[f"test_stream:{identifier}"] == 2
        assert len(sub.broker.nacked) == 2
        assert len(sub.broker.published) == 0

        # Failure 3 → DLQ + ACK
        await sub.handle_failed_message(identifier, payload)
        assert sub.retry_counts == {}
        assert len(sub.broker.published) == 1
        assert sub.broker.published[0][0] == "test_stream:dlq"
        assert len(sub.broker.acked) == 1

    @pytest.mark.asyncio
    async def test_max_retries_1_single_retry(self, test_domain):
        """With max_retries=1, first failure exhausts immediately."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=1)

        await sub.handle_failed_message("msg1", {"data": "x"})

        # Immediate DLQ (retry_count=1 >= max_retries=1)
        assert sub.retry_counts == {}
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
        assert sub.retry_counts["test_stream:msg1"] == 1

        # Acknowledge (simulating success on re-delivery)
        await sub._acknowledge_message("msg1")

        assert sub.retry_counts == {}


# ── Tests: Retry counts per stream ───────────────────────────────────────


class RecordingBroker:
    """Records ack, nack and publish calls, and scripts reclaimed counts.

    The inline broker assigns its own ids, so it cannot put the same id on the
    primary and the backfill stream. On Redis the two streams assign ids
    independently and can hand out the same one.
    """

    def __init__(self, reclaimed: dict[str, dict[str, int]] | None = None):
        self.reclaimed = reclaimed or {}
        self.acks: list[tuple[str, str]] = []
        self.nacks: list[tuple[str, str]] = []
        self.published: list[tuple[str, dict]] = []

    def ack(self, stream, identifier, consumer_group):
        self.acks.append((stream, identifier))
        return True

    def nack(self, stream, identifier, consumer_group):
        self.nacks.append((stream, identifier))
        return True

    def publish(self, stream, message):
        self.published.append((stream, message))
        return "dlq-1"

    def _reclaim_idle_pending(self, stream, consumer_group, consumer_name, idle_ms):
        return dict(self.reclaimed.get(stream, {}))


SHARED_ID = "1-0"


def _lanes_sub_on_recording_broker(test_domain, max_retries=3, reclaimed=None):
    sub = _make_subscription(
        test_domain, AlwaysFailingHandler, max_retries=max_retries, lanes_enabled=True
    )
    sub.broker = RecordingBroker(reclaimed)
    return sub


class TestRetryCountsPerStream:
    """An id pending on both the primary and the backfill stream keeps one
    retry count per stream."""

    @pytest.mark.asyncio
    async def test_primary_ack_keeps_the_backfill_count(self, test_domain):
        sub = _lanes_sub_on_recording_broker(test_domain)
        primary_key = f"{sub.stream_category}:{SHARED_ID}"
        backfill_key = f"{sub.backfill_stream}:{SHARED_ID}"

        await sub.handle_failed_message(
            SHARED_ID, {"data": "x"}, stream=sub.backfill_stream
        )
        assert sub.retry_counts == {backfill_key: 1}

        assert await sub._acknowledge_message(SHARED_ID, stream=sub.stream_category)

        assert sub.broker.acks == [(sub.stream_category, SHARED_ID)]
        assert sub.retry_counts == {backfill_key: 1}
        assert primary_key not in sub.retry_counts

    @pytest.mark.asyncio
    async def test_backfill_ack_keeps_the_primary_count(self, test_domain):
        sub = _lanes_sub_on_recording_broker(test_domain)
        primary_key = f"{sub.stream_category}:{SHARED_ID}"
        backfill_key = f"{sub.backfill_stream}:{SHARED_ID}"

        await sub.handle_failed_message(SHARED_ID, {"data": "x"})
        assert sub.retry_counts == {primary_key: 1}

        assert await sub._acknowledge_message(SHARED_ID, stream=sub.backfill_stream)

        assert sub.broker.acks == [(sub.backfill_stream, SHARED_ID)]
        assert sub.retry_counts == {primary_key: 1}
        assert backfill_key not in sub.retry_counts

    @pytest.mark.asyncio
    async def test_backfill_entry_reaches_its_dlq_after_max_retries(self, test_domain):
        sub = _lanes_sub_on_recording_broker(test_domain, max_retries=3)
        redis = _attach_recording_redis(sub.engine.emitter)
        primary_key = f"{sub.stream_category}:{SHARED_ID}"
        backfill_key = f"{sub.backfill_stream}:{SHARED_ID}"
        # The primary entry with the same id has failed once already.
        await sub.handle_failed_message(SHARED_ID, {"data": "primary"})
        assert sub.retry_counts == {primary_key: 1}

        for attempt in (1, 2):
            await sub.handle_failed_message(
                SHARED_ID, {"data": "backfill"}, stream=sub.backfill_stream
            )
            assert sub.retry_counts == {primary_key: 1, backfill_key: attempt}
            assert sub.broker.published == []

        sub.retry_counts[primary_key] = 2  # a count the DLQ message must not read
        await sub.handle_failed_message(
            SHARED_ID, {"data": "backfill"}, stream=sub.backfill_stream
        )

        [(dlq_stream, dlq_msg)] = sub.broker.published
        assert dlq_stream == sub.backfill_dlq_stream
        assert dlq_msg["data"] == "backfill"
        assert dlq_msg["_dlq_metadata"]["original_stream"] == sub.backfill_stream
        assert dlq_msg["_dlq_metadata"]["original_id"] == SHARED_ID
        assert dlq_msg["_dlq_metadata"]["retry_count"] == 3
        [dlq_trace] = [t for t in redis.traces() if t["event"] == "message.dlq"]
        assert dlq_trace["stream"] == sub.backfill_stream
        assert dlq_trace["metadata"]["retry_count"] == 3
        assert sub.broker.acks == [(sub.backfill_stream, SHARED_ID)]
        assert sub.retry_counts == {primary_key: 2}

    @pytest.mark.asyncio
    async def test_dlq_retry_count_reads_this_streams_count(self, test_domain):
        """With ``max_retries`` above the count, the DLQ message and trace carry
        the stream's own count, not the fallback."""
        sub = _lanes_sub_on_recording_broker(test_domain, max_retries=5)
        redis = _attach_recording_redis(sub.engine.emitter)
        sub.retry_counts[f"{sub.stream_category}:{SHARED_ID}"] = 4
        sub.retry_counts[f"{sub.backfill_stream}:{SHARED_ID}"] = 2

        assert await sub.move_to_dlq(SHARED_ID, {}, stream=sub.backfill_stream)

        [(_, dlq_msg)] = sub.broker.published
        assert dlq_msg["_dlq_metadata"]["retry_count"] == 2
        [dlq_trace] = redis.traces()
        assert dlq_trace["metadata"]["retry_count"] == 2

    def test_reclaimed_counts_are_keyed_by_stream(self, test_domain):
        sub = _lanes_sub_on_recording_broker(
            test_domain,
            reclaimed={
                "test_stream": {SHARED_ID: 2},
                "test_stream:backfill": {SHARED_ID: 1},
            },
        )

        sub._reclaim_idle_pending(sub.stream_category)
        sub._reclaim_idle_pending(sub.backfill_stream)

        assert sub.retry_counts == {
            f"{sub.stream_category}:{SHARED_ID}": 2,
            f"{sub.backfill_stream}:{SHARED_ID}": 1,
        }

    @pytest.mark.asyncio
    async def test_reclaimed_count_carries_toward_max_retries(self, test_domain):
        sub = _lanes_sub_on_recording_broker(
            test_domain, max_retries=3, reclaimed={"test_stream": {SHARED_ID: 2}}
        )
        sub._reclaim_idle_pending(sub.stream_category)

        await sub.handle_failed_message(SHARED_ID, {"data": "x"})

        [(dlq_stream, dlq_msg)] = sub.broker.published
        assert dlq_stream == sub.dlq_stream
        assert dlq_msg["_dlq_metadata"]["retry_count"] == 3
        assert sub.broker.nacks == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("lanes_enabled", [False, True])
    async def test_single_stream_entry_dead_letters_on_the_last_failure(
        self, test_domain, lanes_enabled
    ):
        sub = _make_subscription(
            test_domain,
            AlwaysFailingHandler,
            max_retries=3,
            lanes_enabled=lanes_enabled,
        )
        sub.broker = RecordingBroker()

        for _ in range(2):
            await sub.handle_failed_message(SHARED_ID, {"data": "x"})
        assert sub.broker.published == []
        assert sub.broker.nacks == [(sub.stream_category, SHARED_ID)] * 2

        await sub.handle_failed_message(SHARED_ID, {"data": "x"})

        [(dlq_stream, _)] = sub.broker.published
        assert dlq_stream == sub.dlq_stream
        assert sub.retry_counts == {}


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
        assert sub.retry_counts == {}


# ── Tests: DLQ Disabled ──────────────────────────────────────────────────


class TestDLQDisabled:
    """Behavior when enable_dlq=False."""

    @pytest.mark.asyncio
    async def test_move_to_dlq_returns_true_when_disabled(self, test_domain):
        """move_to_dlq is a no-op when DLQ is disabled, and reports success (True)
        so the caller ACKs the discarded message rather than holding it."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, enable_dlq=False)

        result = await sub.move_to_dlq("msg1", {"data": "x"})

        assert result is True
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
        assert sub.retry_counts == {}


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

    @pytest.mark.asyncio
    async def test_dlq_publish_failure_holds_message_for_redelivery(self, test_domain):
        """A failed DLQ publish must NOT ACK the message; it NACKs and retains the
        retry count so the broker redelivers it (issue #1263)."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=1)
        sub.broker.publish = MagicMock(side_effect=Exception("Broker down"))

        await sub.handle_failed_message("msg1", {"data": "x"})

        # Not ACKed away; NACKed for redelivery; retry count retained.
        assert len(sub.broker.acked) == 0
        assert len(sub.broker.nacked) == 1
        assert "test_stream:msg1" in sub.retry_counts

    @pytest.mark.asyncio
    async def test_message_reaches_dlq_after_transient_publish_failure(
        self, test_domain
    ):
        """The message is retried, not lost: once the DLQ publish succeeds on a
        redelivery it is moved to the DLQ and ACKed."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=1)
        # Publish fails on the first exhaust, succeeds on the redelivery.
        sub.broker.publish = MagicMock(side_effect=[Exception("Broker down"), "dlq-id"])

        await sub.handle_failed_message("msg1", {"data": "x"})
        assert len(sub.broker.acked) == 0  # held, not acked
        assert "test_stream:msg1" in sub.retry_counts

        await sub.handle_failed_message("msg1", {"data": "x"})
        assert sub.broker.publish.call_count == 2
        assert len(sub.broker.acked) == 1  # acked once the DLQ move succeeded
        assert sub.retry_counts == {}

    @pytest.mark.asyncio
    async def test_dlq_publish_failure_backs_off_before_holding(
        self, test_domain, monkeypatch
    ):
        """The exhaust-path hold NACK backs off (retry_delay_seconds) first, so a
        downed DLQ is retried at the retry cadence rather than hammered at poll
        speed (the stream poll loop re-reads pending with no inter-poll delay)."""
        sub = _make_subscription(
            test_domain, AlwaysFailingHandler, max_retries=1, retry_delay_seconds=0.25
        )
        sub.broker.publish = MagicMock(side_effect=Exception("Broker down"))

        sleeps: list[float] = []

        async def fake_sleep(delay):
            sleeps.append(delay)

        monkeypatch.setattr(
            "protean.server.subscription.stream_subscription.asyncio.sleep",
            fake_sleep,
        )

        await sub.handle_failed_message("msg1", {"data": "x"})

        # Backed off before holding, and still held (NACK, no ACK).
        assert 0.25 in sleeps
        assert len(sub.broker.nacked) == 1
        assert len(sub.broker.acked) == 0

    @pytest.mark.asyncio
    async def test_backfill_dlq_publish_failure_holds_on_backfill_stream(
        self, test_domain
    ):
        """A failed DLQ publish for a backfill-lane message NACKs on the backfill
        stream (not the primary), holding it for redelivery."""
        sub = _make_subscription(
            test_domain, AlwaysFailingHandler, max_retries=1, lanes_enabled=True
        )
        sub.broker.publish = MagicMock(side_effect=Exception("Broker down"))

        await sub.handle_failed_message(
            "msg1", {"data": "x"}, stream=sub.backfill_stream
        )

        assert len(sub.broker.acked) == 0
        assert sub.broker.nacked == [(sub.backfill_stream, "msg1", sub.consumer_group)]
        assert f"{sub.backfill_stream}:msg1" in sub.retry_counts

    @pytest.mark.asyncio
    async def test_nack_failure_after_dlq_failure_is_logged(self, test_domain, caplog):
        """If the hold NACK itself fails after a failed DLQ publish, it is logged
        and the message is still not ACKed."""
        sub = _make_subscription(test_domain, AlwaysFailingHandler, max_retries=1)
        sub.broker.publish = MagicMock(side_effect=Exception("Broker down"))
        sub.broker.nack = MagicMock(return_value=False)  # NACK also fails

        with caplog.at_level(logging.WARNING):
            await sub.handle_failed_message("msg1", {"data": "x"})

        assert len(sub.broker.acked) == 0
        assert "Failed to NACK message msg1 after a failed DLQ publish" in caplog.text


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
