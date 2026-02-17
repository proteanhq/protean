"""Tests for the TraceEmitter class.

These tests require a running Redis instance and are gated behind @pytest.mark.redis.
"""

import json
import time

import pytest

from protean.server.tracing import (
    TRACE_CHANNEL,
    TraceEmitter,
    _SUBSCRIBER_CHECK_TTL,
)
from tests.shared import initialize_domain


@pytest.fixture
def redis_domain():
    """Domain configured with Redis broker."""
    domain = initialize_domain(name="Emitter Tests", root_path=__file__)
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain


@pytest.mark.redis
class TestEmitterInitialization:
    def test_lazy_initialization(self, redis_domain):
        """Emitter does not connect to Redis on construction."""
        emitter = TraceEmitter(redis_domain)
        assert emitter._initialized is False
        assert emitter._redis is None

    def test_ensure_initialized_returns_true_with_redis(self, redis_domain):
        """With Redis broker, _ensure_initialized returns True and sets _redis."""
        emitter = TraceEmitter(redis_domain)
        result = emitter._ensure_initialized()
        assert result is True
        assert emitter._redis is not None
        assert emitter._initialized is True

    def test_ensure_initialized_idempotent(self, redis_domain):
        """Second call returns cached result without re-probing."""
        emitter = TraceEmitter(redis_domain)
        emitter._ensure_initialized()
        redis_ref = emitter._redis
        emitter._ensure_initialized()
        assert emitter._redis is redis_ref  # Same instance

    def test_domain_name_captured(self, redis_domain):
        """Emitter captures domain name at init time."""
        emitter = TraceEmitter(redis_domain)
        assert emitter._domain_name == redis_domain.name


@pytest.mark.redis
class TestEmitterSubscriberCheck:
    def test_check_subscribers_returns_false_when_no_subscribers(self, redis_domain):
        """PUBSUB NUMSUB returns 0 when nobody is subscribed."""
        emitter = TraceEmitter(redis_domain)
        result = emitter._check_subscribers()
        assert result is False

    def test_check_subscribers_returns_true_with_subscriber(self, redis_domain):
        """PUBSUB NUMSUB returns > 0 when someone is subscribed."""
        emitter = TraceEmitter(redis_domain)
        emitter._ensure_initialized()

        # Create a subscriber
        pubsub = emitter._redis.pubsub()
        pubsub.subscribe(TRACE_CHANNEL)
        try:
            # Force cache expiry
            emitter._last_subscriber_check = 0.0
            result = emitter._check_subscribers()
            assert result is True
        finally:
            pubsub.unsubscribe(TRACE_CHANNEL)
            pubsub.close()

    def test_check_subscribers_caches_result(self, redis_domain):
        """_check_subscribers caches result for _SUBSCRIBER_CHECK_TTL."""
        emitter = TraceEmitter(redis_domain)
        emitter._ensure_initialized()

        # First call — sets the cache
        emitter._check_subscribers()
        first_check_time = emitter._last_subscriber_check

        # Second call within interval — should use cache
        emitter._check_subscribers()
        assert emitter._last_subscriber_check == first_check_time

    def test_check_subscribers_refreshes_after_interval(self, redis_domain):
        """After interval expires, _check_subscribers re-queries."""
        emitter = TraceEmitter(redis_domain)
        emitter._ensure_initialized()

        # First call
        emitter._check_subscribers()
        first_check_time = emitter._last_subscriber_check

        # Expire the cache
        emitter._last_subscriber_check = time.monotonic() - _SUBSCRIBER_CHECK_TTL - 1

        # Second call should refresh
        emitter._check_subscribers()
        assert emitter._last_subscriber_check > first_check_time


@pytest.mark.redis
class TestEmitterEmit:
    def test_emit_noop_when_no_subscribers(self, redis_domain):
        """emit() returns without publishing when no subscribers exist."""
        emitter = TraceEmitter(redis_domain)

        # Should not raise
        emitter.emit(
            event="handler.started",
            stream="test::user",
            message_id="abc-123",
            message_type="UserRegistered",
        )

    def test_emit_publishes_when_subscriber_present(self, redis_domain):
        """emit() publishes JSON to Redis when subscribers exist."""
        emitter = TraceEmitter(redis_domain)
        emitter._ensure_initialized()

        # Subscribe to channel
        pubsub = emitter._redis.pubsub()
        pubsub.subscribe(TRACE_CHANNEL)
        # Consume the subscription confirmation message
        pubsub.get_message(timeout=1.0)

        try:
            # Force cache expiry so emitter sees the subscriber
            emitter._last_subscriber_check = 0.0

            emitter.emit(
                event="handler.completed",
                stream="test::user",
                message_id="msg-456",
                message_type="UserRegistered",
                handler="UserHandler",
                duration_ms=12.5,
            )

            # Read the published message
            message = pubsub.get_message(timeout=2.0)
            assert message is not None
            assert message["type"] == "message"

            data = json.loads(message["data"])
            assert data["event"] == "handler.completed"
            assert data["domain"] == redis_domain.name
            assert data["stream"] == "test::user"
            assert data["message_id"] == "msg-456"
            assert data["message_type"] == "UserRegistered"
            assert data["handler"] == "UserHandler"
            assert data["duration_ms"] == 12.5
            assert data["timestamp"] != ""
        finally:
            pubsub.unsubscribe(TRACE_CHANNEL)
            pubsub.close()

    def test_emit_swallows_exceptions(self, redis_domain):
        """emit() never propagates exceptions from Redis."""
        emitter = TraceEmitter(redis_domain)
        emitter._ensure_initialized()

        # Force the emitter to think there are subscribers
        emitter._has_subscribers = True
        emitter._last_subscriber_check = time.monotonic()

        # Replace redis with a broken mock
        original_redis = emitter._redis

        class BrokenRedis:
            def publish(self, *args, **kwargs):
                raise ConnectionError("Redis is down")

            def pubsub_numsub(self, *args):
                return [(TRACE_CHANNEL, 1)]

        emitter._redis = BrokenRedis()

        try:
            # Should not raise
            emitter.emit(
                event="handler.started",
                stream="test",
                message_id="123",
                message_type="Foo",
            )
        finally:
            emitter._redis = original_redis

    def test_emit_includes_metadata(self, redis_domain):
        """emit() includes metadata in published trace."""
        emitter = TraceEmitter(redis_domain)
        emitter._ensure_initialized()

        pubsub = emitter._redis.pubsub()
        pubsub.subscribe(TRACE_CHANNEL)
        pubsub.get_message(timeout=1.0)

        try:
            emitter._last_subscriber_check = 0.0

            emitter.emit(
                event="message.dlq",
                stream="test::order",
                message_id="msg-789",
                message_type="OrderPlaced",
                status="error",
                metadata={"dlq_stream": "test::order-dlq", "retry_count": 3},
            )

            message = pubsub.get_message(timeout=2.0)
            data = json.loads(message["data"])
            assert data["metadata"]["dlq_stream"] == "test::order-dlq"
            assert data["metadata"]["retry_count"] == 3
            assert data["status"] == "error"
        finally:
            pubsub.unsubscribe(TRACE_CHANNEL)
            pubsub.close()
