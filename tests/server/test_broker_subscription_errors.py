"""Tests for BrokerSubscription retry tracking and DLQ routing.

Covers the error handling pipeline: retry counting, NACK on transient
failure, DLQ routing after exhaustion, configuration overrides, and trace
event emission.

Every test except the two configuration tests publishes to the real inline
broker, reads the batch back through the subscription and processes it with
real subscribers. The configuration tests only build a subscription and read
its attributes. An ACKed message is
gone from the stream; a NACKed one is delivered again on the next read.
"""

import logging
from unittest.mock import MagicMock

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.domain import Processing
from protean.server import Engine
from protean.server.subscription.broker_subscription import BrokerSubscription
from protean.utils import fqn
from tests.server.test_trace_correlation import _attach_recording_redis

# ── Domain elements ─────────────────────────────────────────────────────

call_counts: dict[str, int] = {}


class SucceedingSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        call_counts["succeed"] = call_counts.get("succeed", 0) + 1


class AlwaysFailingSubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        call_counts["fail"] = call_counts.get("fail", 0) + 1
        raise Exception("Always fails")


class TransientFailingSubscriber(BaseSubscriber):
    """Fails on the first call, then succeeds."""

    def __call__(self, data: dict):
        count = call_counts.get("transient", 0) + 1
        call_counts["transient"] = count
        if count == 1:
            raise Exception("Transient failure")


class SelectiveSubscriber(BaseSubscriber):
    """Fails on a payload that carries ``fail``, succeeds otherwise."""

    def __call__(self, data: dict):
        if data.get("fail"):
            raise Exception("Selected to fail")


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_counts():
    yield
    call_counts.clear()


@pytest.fixture(autouse=True)
def set_message_processing_async(test_domain):
    test_domain.config["message_processing"] = Processing.ASYNC.value


@pytest.fixture
def broker(test_domain, monkeypatch):
    """The domain's inline broker, set to redeliver a NACKed message at once."""
    broker = test_domain.brokers["default"]
    monkeypatch.setattr(broker, "_retry_delay", 0)
    return broker


def _register_and_init(test_domain, subscriber_cls, stream: str = "test_stream"):
    test_domain.register(subscriber_cls, stream=stream)
    test_domain.init(traverse=False)


def _make_subscription(test_domain, subscriber_cls, **overrides):
    """Create an Engine and return the BrokerSubscription for ``subscriber_cls``.

    Accepts keyword overrides that are patched onto the subscription after
    creation (e.g. max_retries, retry_delay_seconds, enable_dlq).
    """
    engine = Engine(test_domain, test_mode=True)
    sub = engine._broker_subscriptions[fqn(subscriber_cls)]
    for key, value in overrides.items():
        setattr(sub, key, value)
    return sub


async def _deliver(sub) -> tuple[list[str], int]:
    """Read the next batch for ``sub`` and process it.

    Returns the identifiers read and the count ``process_batch`` reports.
    """
    messages = await sub.get_next_batch_of_messages()
    processed = await sub.process_batch(messages)
    return [identifier for identifier, _ in messages], processed


def _dlq_payloads(broker, stream: str) -> list[dict]:
    return [payload for _, payload in broker.read(f"{stream}:dlq", "inspector", 10)]


def _in_flight(broker, sub) -> int:
    groups = broker.info()["consumer_groups"]
    return groups[sub.subscriber_name]["in_flight_messages"][sub.stream_name]


# ── Test classes ─────────────────────────────────────────────────────────


class TestRetryTracking:
    """Verify retry count increments and NACK on failure."""

    async def test_failed_message_is_nacked_and_redelivered(self, test_domain, broker):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=5,
        )
        identifier = broker.publish("fail_stream", {"data": "test"})

        assert await _deliver(sub) == ([identifier], 0)
        assert sub.retry_counts[identifier] == 1

        # The NACK hands the same message back on the next read.
        assert await _deliver(sub) == ([identifier], 0)
        assert sub.retry_counts[identifier] == 2
        assert call_counts["fail"] == 2
        assert _dlq_payloads(broker, "fail_stream") == []

    async def test_retry_count_cleared_on_success(self, test_domain, broker):
        _register_and_init(test_domain, TransientFailingSubscriber, "flaky_stream")
        sub = _make_subscription(
            test_domain,
            TransientFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=5,
        )
        identifier = broker.publish("flaky_stream", {"data": "test"})

        await _deliver(sub)
        assert sub.retry_counts == {identifier: 1}

        assert await _deliver(sub) == ([identifier], 1)
        assert identifier not in sub.retry_counts
        # Acknowledged: nothing is left to read.
        assert await _deliver(sub) == ([], 0)

    async def test_retry_counts_are_kept_per_message(self, test_domain, broker):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=3,
        )
        msg_a = broker.publish("fail_stream", {"data": "a"})
        msg_b = broker.publish("fail_stream", {"data": "b"})

        await _deliver(sub)
        assert sub.retry_counts == {msg_a: 1, msg_b: 1}

        # Fail msg_a two more times, leaving msg_b alone.
        for _ in range(2):
            messages = await sub.get_next_batch_of_messages()
            await sub.process_batch([m for m in messages if m[0] == msg_a])

        assert msg_a not in sub.retry_counts
        assert sub.retry_counts[msg_b] == 1
        assert [p["data"] for p in _dlq_payloads(broker, "fail_stream")] == ["a"]


class TestDLQRouting:
    """Verify messages are moved to DLQ after exhausting retries."""

    async def test_message_moved_to_dlq_after_max_retries(self, test_domain, broker):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=3,
        )
        identifier = broker.publish("fail_stream", {"payload": "important"})

        # Attempts 1 and 2 stay below max_retries: NACKed, no DLQ.
        for attempt in (1, 2):
            assert await _deliver(sub) == ([identifier], 0)
            assert sub.retry_counts[identifier] == attempt
            assert _dlq_payloads(broker, "fail_stream") == []

        # Attempt 3 reaches max_retries: moved to the DLQ and ACKed.
        assert await _deliver(sub) == ([identifier], 0)
        assert identifier not in sub.retry_counts
        [dlq_msg] = _dlq_payloads(broker, "fail_stream")
        assert dlq_msg["payload"] == "important"
        assert dlq_msg["_dlq_metadata"]["original_id"] == identifier
        assert dlq_msg["_dlq_metadata"]["retry_count"] == 3
        assert _in_flight(broker, sub) == 0
        assert await _deliver(sub) == ([], 0)

    async def test_dlq_message_metadata(self, test_domain, broker):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
        )
        identifier = broker.publish(
            "fail_stream",
            {"data": "important", "metadata": {"headers": {"type": "OrderPlaced"}}},
        )

        # max_retries=1: the first failure exhausts, and nothing counts as processed.
        assert await _deliver(sub) == ([identifier], 0)
        assert identifier not in sub.retry_counts

        [dlq_message] = _dlq_payloads(broker, "fail_stream")
        meta = dlq_message["_dlq_metadata"]
        assert meta["original_stream"] == "fail_stream"
        assert meta["original_id"] == identifier
        assert meta["consumer_group"] == sub.subscriber_name
        assert meta["consumer"] == sub.subscription_id
        assert "failed_at" in meta
        assert meta["retry_count"] == 1
        # Original payload preserved
        assert dlq_message["data"] == "important"


class TestDLQDisabled:
    """Verify behavior when enable_dlq=False."""

    async def test_exhausted_message_is_discarded(self, test_domain, broker, caplog):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
            enable_dlq=False,
        )
        broker.publish("fail_stream", {"data": "test"})

        with caplog.at_level(logging.WARNING):
            await _deliver(sub)

        assert "discarding" in caplog.text
        assert _dlq_payloads(broker, "fail_stream") == []
        assert sub.retry_counts == {}
        # Still ACKed to clear it from pending: nothing is redelivered.
        assert _in_flight(broker, sub) == 0
        assert await _deliver(sub) == ([], 0)


class TestSuccessfulProcessing:
    """Verify normal success path still works correctly."""

    async def test_successful_messages_are_acked_and_counted(self, test_domain, broker):
        _register_and_init(test_domain, SucceedingSubscriber, "ok_stream")
        sub = _make_subscription(test_domain, SucceedingSubscriber)
        for data in ("a", "b", "c"):
            broker.publish("ok_stream", {"data": data})

        identifiers, processed = await _deliver(sub)

        assert len(identifiers) == 3
        assert processed == 3
        assert call_counts["succeed"] == 3
        assert await _deliver(sub) == ([], 0)

    async def test_mixed_batch_success_and_failure(self, test_domain, broker):
        _register_and_init(test_domain, SelectiveSubscriber, "mixed_stream")
        sub = _make_subscription(
            test_domain, SelectiveSubscriber, retry_delay_seconds=0, max_retries=3
        )
        broker.publish("mixed_stream", {"data": "a"})
        failing = broker.publish("mixed_stream", {"data": "b", "fail": True})

        identifiers, processed = await _deliver(sub)

        assert len(identifiers) == 2
        assert processed == 1
        # Only the failed message was NACKed and comes back.
        assert await _deliver(sub) == ([failing], 0)


class TestConfiguration:
    """Verify configuration defaults and overrides."""

    def test_default_config_values(self, test_domain):
        _register_and_init(test_domain, SucceedingSubscriber, "my_stream")
        sub = _make_subscription(test_domain, SucceedingSubscriber)

        assert sub.max_retries == 3
        assert sub.retry_delay_seconds == 1.0
        assert sub.enable_dlq is True
        assert sub.dlq_stream == "my_stream:dlq"

    def test_constructor_overrides(self, test_domain):
        _register_and_init(test_domain, SucceedingSubscriber, "ok_stream")
        engine = Engine(test_domain, test_mode=True)

        sub = BrokerSubscription(
            engine=engine,
            broker=test_domain.brokers["default"],
            stream_name="custom_stream",
            handler=SucceedingSubscriber,
            max_retries=10,
            retry_delay_seconds=5.0,
            enable_dlq=False,
        )

        assert sub.max_retries == 10
        assert sub.retry_delay_seconds == 5.0
        assert sub.enable_dlq is False


class TestTraceEvents:
    """Verify trace event emission on retry and DLQ.

    The engine's real trace emitter writes to Redis, so each test gives it a
    Redis stand-in and reads the traces it recorded.
    """

    async def test_nacked_trace_emitted_on_retry(self, test_domain, broker):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=3,
        )
        redis = _attach_recording_redis(sub.engine.emitter)
        identifier = broker.publish("fail_stream", {"data": "test"})

        await _deliver(sub)

        [trace] = redis.traces()
        assert trace["event"] == "message.nacked"
        assert trace["stream"] == "fail_stream"
        assert trace["message_id"] == identifier
        assert trace["status"] == "retry"
        assert trace["metadata"]["retry_count"] == 1
        assert trace["metadata"]["max_retries"] == 3

    async def test_dlq_trace_emitted_on_exhaustion(self, test_domain, broker):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
        )
        redis = _attach_recording_redis(sub.engine.emitter)
        broker.publish("fail_stream", {"data": "test"})

        await _deliver(sub)

        # Should emit message.dlq
        [trace] = redis.traces()
        assert trace["event"] == "message.dlq"
        assert trace["stream"] == "fail_stream"
        assert trace["metadata"]["dlq_stream"] == "fail_stream:dlq"


class TestNACKFailure:
    """Verify behavior when broker NACK operation itself fails."""

    async def test_nack_failure_logged(self, test_domain, broker, monkeypatch, caplog):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=3,
        )
        identifier = broker.publish("fail_stream", {"data": "test"})
        monkeypatch.setattr(broker, "nack", MagicMock(return_value=False))

        with caplog.at_level(logging.WARNING):
            await _deliver(sub)

        assert f"Failed to NACK message {identifier}" in caplog.text


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


class TestDLQPublishFailure:
    """Verify a failed DLQ publish holds the message for redelivery (issue #1263)."""

    async def test_message_reaches_dlq_after_transient_publish_failure(
        self, test_domain, broker, monkeypatch, caplog
    ):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
        )
        identifier = broker.publish("fail_stream", {"data": "test"})
        _publish_fails(broker, monkeypatch, times=1)

        # First delivery: exhausts, DLQ publish fails, message held (NACKed).
        with caplog.at_level(logging.ERROR):
            await _deliver(sub)
        assert "Failed to move message" in caplog.text
        # Retry count is retained so the redelivery stays on the exhaust path.
        assert sub.retry_counts[identifier] == 1
        assert _dlq_payloads(broker, "fail_stream") == []

        # Redelivery: exhausts again, DLQ publish now succeeds, message ACKed.
        assert await _deliver(sub) == ([identifier], 0)
        assert identifier not in sub.retry_counts
        [dlq_msg] = _dlq_payloads(broker, "fail_stream")
        assert dlq_msg["_dlq_metadata"]["original_id"] == identifier
        assert await _deliver(sub) == ([], 0)

    async def test_nack_failure_after_dlq_failure_is_logged(
        self, test_domain, broker, monkeypatch, caplog
    ):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
        )
        identifier = broker.publish("fail_stream", {"data": "test"})
        _publish_fails(broker, monkeypatch)
        monkeypatch.setattr(broker, "nack", MagicMock(return_value=False))

        with caplog.at_level(logging.WARNING):
            await _deliver(sub)

        # Still not ACKed away (the message stays in-flight for redelivery), and
        # the failed NACK is surfaced.
        assert _in_flight(broker, sub) == 1
        assert (
            f"Failed to NACK message {identifier} after a failed DLQ publish"
            in caplog.text
        )

    async def test_dlq_publish_failure_backs_off_before_holding(
        self, test_domain, broker, monkeypatch
    ):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0.25,
            max_retries=1,
        )
        identifier = broker.publish("fail_stream", {"data": "test"})
        _publish_fails(broker, monkeypatch)

        sleeps: list[float] = []

        async def fake_sleep(delay):
            sleeps.append(delay)

        monkeypatch.setattr(
            "protean.server.subscription.broker_subscription.asyncio.sleep",
            fake_sleep,
        )

        await _deliver(sub)

        # Backed off before the hold NACK, and still held: redelivered, not ACKed.
        assert 0.25 in sleeps
        assert [m[0] for m in await sub.get_next_batch_of_messages()] == [identifier]


class TestACKFailure:
    """Verify behavior when ACK fails on successful processing."""

    async def test_ack_failure_not_counted_as_success(
        self, test_domain, broker, monkeypatch, caplog
    ):
        _register_and_init(test_domain, SucceedingSubscriber, "ok_stream")
        sub = _make_subscription(test_domain, SucceedingSubscriber)
        identifier = broker.publish("ok_stream", {"data": "test"})
        monkeypatch.setattr(broker, "ack", MagicMock(return_value=False))

        with caplog.at_level(logging.WARNING):
            assert await _deliver(sub) == ([identifier], 0)

        assert f"Failed to acknowledge message {identifier}" in caplog.text
