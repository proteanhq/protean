"""Tests for BrokerSubscription retry tracking and DLQ routing.

Covers the error handling pipeline added in Steps 5-9 of issue #489:
retry counting, NACK on transient failure, DLQ routing after exhaustion,
configuration overrides, and trace event emission.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.domain import Processing
from protean.server import Engine
from protean.utils import fqn


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
    """Fails the first N times, then succeeds."""

    def __call__(self, data: dict):
        count = call_counts.get("transient", 0) + 1
        call_counts["transient"] = count
        if count <= 2:
            raise Exception(f"Transient failure #{count}")


class ErrorInErrorHandlerSubscriber(BaseSubscriber):
    """handle_error itself raises."""

    def __call__(self, data: dict):
        raise Exception("Primary failure")

    @classmethod
    def handle_error(cls, exc, message):
        raise Exception("Error handler exploded")


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_counts():
    yield
    call_counts.clear()


@pytest.fixture(autouse=True)
def set_message_processing_async(test_domain):
    test_domain.config["message_processing"] = Processing.ASYNC.value


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


# ── Test classes ─────────────────────────────────────────────────────────


class TestRetryTracking:
    """Verify retry count increments and NACK on failure."""

    def test_first_failure_increments_retry_count(self, test_domain):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain, AlwaysFailingSubscriber, retry_delay_seconds=0
        )

        # Mock broker operations
        sub.broker.nack = MagicMock(return_value=True)
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )

        assert sub.retry_counts.get("msg1") == 1

    def test_nack_called_on_retry(self, test_domain):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=3,
        )

        sub.broker.nack = MagicMock(return_value=True)
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )

        sub.broker.nack.assert_called_once_with(
            "fail_stream", "msg1", sub.subscriber_name
        )

    def test_multiple_failures_increment_retry_count(self, test_domain):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=5,
        )

        sub.broker.nack = MagicMock(return_value=True)
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        # Simulate the same message failing twice (re-delivered by broker)
        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )
        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )

        assert sub.retry_counts["msg1"] == 2
        assert sub.broker.nack.call_count == 2

    def test_retry_count_cleared_on_success(self, test_domain):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=5,
        )

        sub.broker.nack = MagicMock(return_value=True)
        sub.broker.ack = MagicMock(return_value=True)

        import asyncio

        # First call fails
        sub.engine.handle_broker_message = AsyncMock(return_value=False)
        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )
        assert "msg1" in sub.retry_counts

        # Second call succeeds
        sub.engine.handle_broker_message = AsyncMock(return_value=True)
        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )
        assert "msg1" not in sub.retry_counts


class TestDLQRouting:
    """Verify messages are moved to DLQ after exhausting retries."""

    def test_message_moved_to_dlq_after_max_retries(self, test_domain):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=2,
        )

        sub.broker.nack = MagicMock(return_value=True)
        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.publish = MagicMock()
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        # Fail twice (retry_count=1 → NACK, retry_count=2 → DLQ)
        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )
        assert sub.broker.nack.call_count == 1
        assert sub.broker.publish.call_count == 0

        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )

        # Should publish to DLQ and ACK from original stream
        sub.broker.publish.assert_called_once()
        dlq_stream_arg = sub.broker.publish.call_args[0][0]
        assert dlq_stream_arg == "fail_stream:dlq"

        # Should ACK after DLQ move
        sub.broker.ack.assert_called_with("fail_stream", "msg1", sub.subscriber_name)

    def test_retry_count_cleared_after_dlq(self, test_domain):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
        )

        sub.broker.nack = MagicMock(return_value=True)
        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.publish = MagicMock()
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        # max_retries=1 → first failure exhausts (retry_count=1 >= 1)
        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )

        assert "msg1" not in sub.retry_counts

    def test_dlq_message_metadata(self, test_domain):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
        )

        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.publish = MagicMock()
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        payload = {
            "data": "important",
            "metadata": {"headers": {"type": "OrderPlaced"}},
        }
        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg42", payload)])
        )

        dlq_message = sub.broker.publish.call_args[0][1]
        assert "_dlq_metadata" in dlq_message
        meta = dlq_message["_dlq_metadata"]
        assert meta["original_stream"] == "fail_stream"
        assert meta["original_id"] == "msg42"
        assert meta["consumer_group"] == sub.subscriber_name
        assert meta["consumer"] == sub.subscription_id
        assert "failed_at" in meta
        assert meta["retry_count"] == 1
        # Original payload preserved
        assert dlq_message["data"] == "important"

    def test_process_batch_returns_zero_on_dlq(self, test_domain):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
        )

        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.publish = MagicMock()
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )
        assert result == 0


class TestDLQDisabled:
    """Verify behavior when enable_dlq=False."""

    def test_no_dlq_publish_when_disabled(self, test_domain):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
            enable_dlq=False,
        )

        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.publish = MagicMock()
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )

        # No DLQ publish
        sub.broker.publish.assert_not_called()

        # But still ACK to clear from pending
        sub.broker.ack.assert_called_once_with(
            "fail_stream", "msg1", sub.subscriber_name
        )

    def test_retry_count_cleared_when_dlq_disabled(self, test_domain):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
            enable_dlq=False,
        )

        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.publish = MagicMock()
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )

        assert "msg1" not in sub.retry_counts

    def test_exhaustion_logged_as_discard(self, test_domain, caplog):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
            enable_dlq=False,
        )

        sub.broker.ack = MagicMock(return_value=True)
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        with caplog.at_level(logging.WARNING):
            asyncio.get_event_loop().run_until_complete(
                sub.process_batch([("msg1", {"data": "test"})])
            )

        assert "discarding" in caplog.text


class TestSuccessfulProcessing:
    """Verify normal success path still works correctly."""

    def test_successful_message_acked(self, test_domain):
        _register_and_init(test_domain, SucceedingSubscriber, "ok_stream")
        sub = _make_subscription(test_domain, SucceedingSubscriber)

        sub.broker.ack = MagicMock(return_value=True)
        sub.engine.handle_broker_message = AsyncMock(return_value=True)

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )

        assert result == 1
        sub.broker.ack.assert_called_once_with("ok_stream", "msg1", sub.subscriber_name)

    def test_multiple_messages_counted(self, test_domain):
        _register_and_init(test_domain, SucceedingSubscriber, "ok_stream")
        sub = _make_subscription(test_domain, SucceedingSubscriber)

        sub.broker.ack = MagicMock(return_value=True)
        sub.engine.handle_broker_message = AsyncMock(return_value=True)

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            sub.process_batch(
                [
                    ("msg1", {"data": "a"}),
                    ("msg2", {"data": "b"}),
                    ("msg3", {"data": "c"}),
                ]
            )
        )

        assert result == 3

    def test_mixed_batch_success_and_failure(self, test_domain):
        _register_and_init(test_domain, SucceedingSubscriber, "ok_stream")
        sub = _make_subscription(
            test_domain, SucceedingSubscriber, retry_delay_seconds=0, max_retries=3
        )

        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.nack = MagicMock(return_value=True)

        # First message succeeds, second fails
        sub.engine.handle_broker_message = AsyncMock(side_effect=[True, False])

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            sub.process_batch(
                [
                    ("msg1", {"data": "a"}),
                    ("msg2", {"data": "b"}),
                ]
            )
        )

        assert result == 1
        sub.broker.ack.assert_called_once()
        sub.broker.nack.assert_called_once()


class TestConfiguration:
    """Verify configuration defaults and overrides."""

    def test_default_config_values(self, test_domain):
        _register_and_init(test_domain, SucceedingSubscriber, "ok_stream")
        sub = _make_subscription(test_domain, SucceedingSubscriber)

        assert sub.max_retries == 3
        assert sub.retry_delay_seconds == 1.0
        assert sub.enable_dlq is True

    def test_constructor_overrides(self, test_domain):
        _register_and_init(test_domain, SucceedingSubscriber, "ok_stream")
        engine = Engine(test_domain, test_mode=True)

        from protean.server.subscription.broker_subscription import BrokerSubscription

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

    def test_dlq_stream_naming(self, test_domain):
        _register_and_init(test_domain, SucceedingSubscriber, "my_stream")
        sub = _make_subscription(test_domain, SucceedingSubscriber)

        assert sub.dlq_stream == "my_stream:dlq"


class TestTraceEvents:
    """Verify trace event emission on retry and DLQ."""

    def test_nacked_trace_emitted_on_retry(self, test_domain):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=3,
        )

        sub.broker.nack = MagicMock(return_value=True)
        sub.engine.handle_broker_message = AsyncMock(return_value=False)
        sub.engine.emitter = MagicMock()

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )

        sub.engine.emitter.emit.assert_called_once()
        call_kwargs = sub.engine.emitter.emit.call_args
        assert call_kwargs.kwargs["event"] == "message.nacked"
        assert call_kwargs.kwargs["stream"] == "fail_stream"
        assert call_kwargs.kwargs["message_id"] == "msg1"
        assert call_kwargs.kwargs["status"] == "retry"
        assert call_kwargs.kwargs["metadata"]["retry_count"] == 1
        assert call_kwargs.kwargs["metadata"]["max_retries"] == 3

    def test_dlq_trace_emitted_on_exhaustion(self, test_domain):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
        )

        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.publish = MagicMock()
        sub.engine.handle_broker_message = AsyncMock(return_value=False)
        sub.engine.emitter = MagicMock()

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg1", {"data": "test"})])
        )

        # Should emit message.dlq
        emit_calls = sub.engine.emitter.emit.call_args_list
        assert len(emit_calls) == 1
        call_kwargs = emit_calls[0].kwargs
        assert call_kwargs["event"] == "message.dlq"
        assert call_kwargs["stream"] == "fail_stream"
        assert call_kwargs["metadata"]["dlq_stream"] == "fail_stream:dlq"


class TestNACKFailure:
    """Verify behavior when broker NACK operation itself fails."""

    def test_nack_failure_logged(self, test_domain, caplog):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=3,
        )

        sub.broker.nack = MagicMock(return_value=False)
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        with caplog.at_level(logging.WARNING):
            asyncio.get_event_loop().run_until_complete(
                sub.process_batch([("msg1", {"data": "test"})])
            )

        assert "Failed to NACK message msg1" in caplog.text


class TestDLQPublishFailure:
    """Verify resilience when DLQ publish itself fails."""

    def test_dlq_publish_exception_caught(self, test_domain, caplog):
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=1,
        )

        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.publish = MagicMock(side_effect=Exception("Broker down"))
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        with caplog.at_level(logging.ERROR):
            asyncio.get_event_loop().run_until_complete(
                sub.process_batch([("msg1", {"data": "test"})])
            )

        assert "Failed to move message" in caplog.text

        # Should still ACK from original stream even if DLQ publish failed
        sub.broker.ack.assert_called_with("fail_stream", "msg1", sub.subscriber_name)


class TestACKFailure:
    """Verify behavior when ACK fails on successful processing."""

    def test_ack_failure_not_counted_as_success(self, test_domain, caplog):
        _register_and_init(test_domain, SucceedingSubscriber, "ok_stream")
        sub = _make_subscription(test_domain, SucceedingSubscriber)

        sub.broker.ack = MagicMock(return_value=False)
        sub.engine.handle_broker_message = AsyncMock(return_value=True)

        import asyncio

        with caplog.at_level(logging.WARNING):
            result = asyncio.get_event_loop().run_until_complete(
                sub.process_batch([("msg1", {"data": "test"})])
            )

        assert result == 0
        assert "Failed to acknowledge message msg1" in caplog.text


class TestEndToEndRetryToDLQ:
    """Full retry → DLQ pipeline with realistic message re-delivery."""

    def test_full_retry_to_dlq_pipeline(self, test_domain):
        """Simulate a message failing max_retries times then landing in DLQ."""
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=3,
        )

        sub.broker.nack = MagicMock(return_value=True)
        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.publish = MagicMock()
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        msg = ("msg_x", {"payload": "important"})

        # Attempt 1: retry_count=1 < 3 → NACK
        asyncio.get_event_loop().run_until_complete(sub.process_batch([msg]))
        assert sub.retry_counts["msg_x"] == 1
        assert sub.broker.nack.call_count == 1
        assert sub.broker.publish.call_count == 0

        # Attempt 2: retry_count=2 < 3 → NACK
        asyncio.get_event_loop().run_until_complete(sub.process_batch([msg]))
        assert sub.retry_counts["msg_x"] == 2
        assert sub.broker.nack.call_count == 2
        assert sub.broker.publish.call_count == 0

        # Attempt 3: retry_count=3 >= 3 → DLQ + ACK
        asyncio.get_event_loop().run_until_complete(sub.process_batch([msg]))
        assert "msg_x" not in sub.retry_counts  # Cleared
        assert sub.broker.publish.call_count == 1
        assert sub.broker.ack.call_count == 1

        # Verify DLQ message
        dlq_msg = sub.broker.publish.call_args[0][1]
        assert dlq_msg["payload"] == "important"
        assert dlq_msg["_dlq_metadata"]["original_id"] == "msg_x"
        assert dlq_msg["_dlq_metadata"]["retry_count"] == 3

    def test_independent_retry_tracking_per_message(self, test_domain):
        """Each message has its own retry counter."""
        _register_and_init(test_domain, AlwaysFailingSubscriber, "fail_stream")
        sub = _make_subscription(
            test_domain,
            AlwaysFailingSubscriber,
            retry_delay_seconds=0,
            max_retries=3,
        )

        sub.broker.nack = MagicMock(return_value=True)
        sub.broker.ack = MagicMock(return_value=True)
        sub.broker.publish = MagicMock()
        sub.engine.handle_broker_message = AsyncMock(return_value=False)

        import asyncio

        # Fail msg_a once
        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg_a", {"data": "a"})])
        )
        # Fail msg_b once
        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg_b", {"data": "b"})])
        )

        assert sub.retry_counts["msg_a"] == 1
        assert sub.retry_counts["msg_b"] == 1

        # Fail msg_a two more times → DLQ
        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg_a", {"data": "a"})])
        )
        asyncio.get_event_loop().run_until_complete(
            sub.process_batch([("msg_a", {"data": "a"})])
        )

        # msg_a exhausted, msg_b still at 1
        assert "msg_a" not in sub.retry_counts
        assert sub.retry_counts["msg_b"] == 1
