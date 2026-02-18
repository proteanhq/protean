"""Tests for Observatory trace history and stats endpoints, and TraceEmitter persistence.

Tests for the trace stream persistence (XADD) in TraceEmitter, the
/api/traces history endpoint, and the /api/traces/stats aggregation endpoint.
"""

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory
from protean.server.tracing import (
    DEFAULT_TRACE_RETENTION_DAYS,
    TRACE_CHANNEL,
    TRACE_STREAM,
    MessageTrace,
    TraceEmitter,
)

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain(request):
    if "no_test_domain" in request.keywords:
        yield
    else:
        domain = initialize_domain(name="Observatory Trace Tests", root_path=__file__)
        domain.init(traverse=False)

        with domain.domain_context():
            yield domain


@pytest.fixture
def observatory(test_domain):
    return Observatory(domains=[test_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


@pytest.fixture
def redis_conn(test_domain):
    """Get a raw Redis connection for test setup/teardown."""
    with test_domain.domain_context():
        broker = test_domain.brokers.get("default")
        if broker and hasattr(broker, "redis_instance"):
            conn = broker.redis_instance
            # Clean up trace stream before and after test
            try:
                conn.delete(TRACE_STREAM)
            except Exception:
                pass
            yield conn
            try:
                conn.delete(TRACE_STREAM)
            except Exception:
                pass
        else:
            pytest.skip("Redis broker not available")


def _seed_traces(redis_conn, traces: list[dict]) -> None:
    """Write trace dicts directly to the Redis trace stream."""
    for trace in traces:
        redis_conn.xadd(TRACE_STREAM, {"data": json.dumps(trace)})


def _make_trace(
    event: str = "handler.completed",
    domain: str = "test",
    stream: str = "test::entity",
    message_id: str = "msg-001",
    message_type: str = "TestEvent",
    status: str = "ok",
    handler: str = "TestHandler",
    duration_ms: float | None = 10.0,
    error: str | None = None,
    payload: dict | None = None,
) -> dict:
    """Build a trace dict matching MessageTrace structure."""
    trace = {
        "event": event,
        "domain": domain,
        "stream": stream,
        "message_id": message_id,
        "message_type": message_type,
        "status": status,
        "handler": handler,
        "duration_ms": duration_ms,
        "error": error,
        "metadata": {},
        "payload": payload,
        "timestamp": "2026-01-15T10:00:00+00:00",
    }
    return trace


# ===== MessageTrace dataclass tests =====


class TestMessageTrace:
    def test_to_json_serializes_all_fields(self):
        trace = MessageTrace(
            event="handler.completed",
            domain="test",
            stream="test::entity",
            message_id="msg-001",
            message_type="TestEvent",
            status="ok",
            handler="TestHandler",
            duration_ms=12.5,
        )
        data = json.loads(trace.to_json())
        assert data["event"] == "handler.completed"
        assert data["domain"] == "test"
        assert data["duration_ms"] == 12.5
        assert data["handler"] == "TestHandler"

    def test_auto_populates_timestamp(self):
        trace = MessageTrace(
            event="test",
            domain="d",
            stream="s",
            message_id="m",
            message_type="t",
            status="ok",
        )
        assert trace.timestamp != ""
        assert "T" in trace.timestamp  # ISO 8601


# ===== TraceEmitter persistence tests =====


@pytest.mark.redis
class TestTraceEmitterPersistence:
    def test_emitter_defaults_to_persistence_enabled(self, test_domain):
        """TraceEmitter enables persistence by default with 7-day retention."""
        emitter = TraceEmitter(test_domain)
        assert emitter._persist is True
        assert emitter._retention_ms == DEFAULT_TRACE_RETENTION_DAYS * 86_400_000

    def test_emitter_persistence_disabled_when_zero(self, test_domain):
        """TraceEmitter disables persistence when trace_retention_days=0."""
        emitter = TraceEmitter(test_domain, trace_retention_days=0)
        assert emitter._persist is False

    def test_emit_writes_to_stream(self, test_domain, redis_conn):
        """emit() writes to the trace Redis Stream when persistence is enabled."""
        emitter = TraceEmitter(test_domain, trace_retention_days=1)
        emitter.emit(
            event="handler.completed",
            stream="test::entity",
            message_id="msg-001",
            message_type="TestEvent",
            handler="TestHandler",
            duration_ms=15.0,
        )

        # Verify entry in stream
        entries = redis_conn.xrange(TRACE_STREAM)
        assert len(entries) >= 1

        # Parse the last entry
        _, fields = entries[-1]
        data_raw = fields.get(b"data") or fields.get("data")
        if isinstance(data_raw, bytes):
            data_raw = data_raw.decode("utf-8")
        trace = json.loads(data_raw)
        assert trace["event"] == "handler.completed"
        assert trace["message_id"] == "msg-001"
        assert trace["handler"] == "TestHandler"
        assert trace["duration_ms"] == 15.0

    def test_emit_uses_minid_trimming(self, test_domain, redis_conn):
        """emit() uses MINID-based time trimming instead of MAXLEN."""
        emitter = TraceEmitter(test_domain, trace_retention_days=7)

        # Write several events
        for i in range(10):
            emitter.emit(
                event="handler.completed",
                stream="test::entity",
                message_id=f"msg-{i:03d}",
                message_type="TestEvent",
            )

        # All recent entries should be retained (they're all within the 7-day window)
        stream_len = redis_conn.xlen(TRACE_STREAM)
        assert stream_len == 10

    def test_emit_does_not_write_when_persistence_disabled(
        self, test_domain, redis_conn
    ):
        """emit() skips stream write when persistence is disabled and no subscribers."""
        emitter = TraceEmitter(test_domain, trace_retention_days=0)
        emitter.emit(
            event="handler.completed",
            stream="test::entity",
            message_id="msg-001",
            message_type="TestEvent",
        )

        stream_len = redis_conn.xlen(TRACE_STREAM)
        assert stream_len == 0

    def test_emit_skips_persist_when_retention_zero_but_publishes_to_subscribers(
        self, test_domain, redis_conn
    ):
        """emit() publishes to Pub/Sub but does NOT write to stream when persistence is off."""
        # Subscribe so the publish path is triggered
        pubsub = redis_conn.pubsub()
        pubsub.subscribe(TRACE_CHANNEL)
        pubsub.get_message(timeout=1)  # consume subscribe confirmation

        try:
            emitter = TraceEmitter(test_domain, trace_retention_days=0)
            emitter._last_subscriber_check = 0.0  # force refresh

            emitter.emit(
                event="handler.completed",
                stream="test::entity",
                message_id="msg-no-persist",
                message_type="TestEvent",
            )

            # Should NOT be in the stream (persistence disabled)
            stream_len = redis_conn.xlen(TRACE_STREAM)
            assert stream_len == 0

            # Should be published via Pub/Sub
            msg = pubsub.get_message(timeout=2)
            assert msg is not None
            assert msg["type"] == "message"
            data = json.loads(msg["data"])
            assert data["message_id"] == "msg-no-persist"
        finally:
            pubsub.unsubscribe(TRACE_CHANNEL)
            pubsub.close()

    def test_emit_publishes_to_pubsub_when_subscribers_exist(
        self, test_domain, redis_conn
    ):
        """emit() publishes to Pub/Sub channel when subscribers are present."""
        # Subscribe to the channel so NUMSUB > 0
        pubsub = redis_conn.pubsub()
        pubsub.subscribe(TRACE_CHANNEL)
        # Consume subscribe confirmation
        pubsub.get_message(timeout=1)

        try:
            emitter = TraceEmitter(test_domain, trace_retention_days=1)
            # Force refresh of subscriber check
            emitter._last_subscriber_check = 0.0

            emitter.emit(
                event="handler.completed",
                stream="test::entity",
                message_id="msg-pubsub",
                message_type="TestEvent",
            )

            # The message should appear on pubsub
            msg = pubsub.get_message(timeout=2)
            assert msg is not None
            assert msg["type"] == "message"
            data = json.loads(msg["data"])
            assert data["message_id"] == "msg-pubsub"
        finally:
            pubsub.unsubscribe(TRACE_CHANNEL)
            pubsub.close()

    def test_emit_writes_payload_to_stream(self, test_domain, redis_conn):
        """emit() includes payload in the persisted trace when provided."""
        emitter = TraceEmitter(test_domain, trace_retention_days=1)
        test_payload = {"order_id": "abc-123", "items": [{"sku": "X1", "qty": 2}]}

        emitter.emit(
            event="outbox.published",
            stream="test::order",
            message_id="msg-payload",
            message_type="OrderPlaced",
            payload=test_payload,
        )

        entries = redis_conn.xrange(TRACE_STREAM)
        assert len(entries) >= 1

        _, fields = entries[-1]
        data_raw = fields.get(b"data") or fields.get("data")
        if isinstance(data_raw, bytes):
            data_raw = data_raw.decode("utf-8")
        trace = json.loads(data_raw)
        assert trace["payload"] == test_payload

    def test_emit_writes_null_payload_when_not_provided(self, test_domain, redis_conn):
        """emit() writes null payload when no payload is provided."""
        emitter = TraceEmitter(test_domain, trace_retention_days=1)

        emitter.emit(
            event="handler.completed",
            stream="test::entity",
            message_id="msg-no-payload",
            message_type="TestEvent",
        )

        entries = redis_conn.xrange(TRACE_STREAM)
        assert len(entries) >= 1

        _, fields = entries[-1]
        data_raw = fields.get(b"data") or fields.get("data")
        if isinstance(data_raw, bytes):
            data_raw = data_raw.decode("utf-8")
        trace = json.loads(data_raw)
        assert trace["payload"] is None


# ===== /api/traces endpoint tests =====


@pytest.mark.redis
class TestTracesEndpoint:
    def test_traces_returns_empty_when_no_data(self, client, redis_conn):
        """GET /api/traces returns empty list when no traces exist."""
        response = client.get("/api/traces")
        assert response.status_code == 200
        data = response.json()
        assert data["traces"] == []
        assert data["count"] == 0

    def test_traces_returns_seeded_data(self, client, redis_conn):
        """GET /api/traces returns traces from the stream."""
        traces = [
            _make_trace(event="outbox.published", message_id="msg-001"),
            _make_trace(event="handler.started", message_id="msg-001"),
            _make_trace(event="handler.completed", message_id="msg-001"),
        ]
        _seed_traces(redis_conn, traces)

        response = client.get("/api/traces")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3
        # Newest first (XREVRANGE order)
        assert data["traces"][0]["event"] == "handler.completed"
        assert data["traces"][2]["event"] == "outbox.published"

    def test_traces_respects_count_limit(self, client, redis_conn):
        """GET /api/traces?count=2 limits results."""
        traces = [_make_trace(message_id=f"msg-{i}") for i in range(5)]
        _seed_traces(redis_conn, traces)

        response = client.get("/api/traces?count=2")
        data = response.json()
        assert data["count"] == 2
        assert len(data["traces"]) == 2

    def test_traces_filters_by_domain(self, client, redis_conn):
        """GET /api/traces?domain=identity returns only matching traces."""
        traces = [
            _make_trace(domain="identity", message_id="msg-1"),
            _make_trace(domain="catalogue", message_id="msg-2"),
            _make_trace(domain="identity", message_id="msg-3"),
        ]
        _seed_traces(redis_conn, traces)

        response = client.get("/api/traces?domain=identity")
        data = response.json()
        assert data["count"] == 2
        for t in data["traces"]:
            assert t["domain"] == "identity"

    def test_traces_filters_by_stream(self, client, redis_conn):
        """GET /api/traces?stream=test::order returns only matching traces."""
        traces = [
            _make_trace(stream="test::order", message_id="msg-1"),
            _make_trace(stream="test::customer", message_id="msg-2"),
        ]
        _seed_traces(redis_conn, traces)

        response = client.get("/api/traces?stream=test::order")
        data = response.json()
        assert data["count"] == 1
        assert data["traces"][0]["stream"] == "test::order"

    def test_traces_filters_by_event(self, client, redis_conn):
        """GET /api/traces?event=handler.failed returns only matching traces."""
        traces = [
            _make_trace(event="handler.completed", message_id="msg-1"),
            _make_trace(event="handler.failed", message_id="msg-2", status="error"),
            _make_trace(event="handler.completed", message_id="msg-3"),
        ]
        _seed_traces(redis_conn, traces)

        response = client.get("/api/traces?event=handler.failed")
        data = response.json()
        assert data["count"] == 1
        assert data["traces"][0]["event"] == "handler.failed"

    def test_traces_includes_stream_id(self, client, redis_conn):
        """Each trace in the response includes a _stream_id field."""
        _seed_traces(redis_conn, [_make_trace()])

        response = client.get("/api/traces")
        data = response.json()
        assert "_stream_id" in data["traces"][0]
        # Stream ID format: <timestamp>-<sequence>
        assert "-" in data["traces"][0]["_stream_id"]

    def test_delete_traces_clears_stream(self, client, redis_conn):
        """DELETE /api/traces clears the trace stream."""
        _seed_traces(redis_conn, [_make_trace(), _make_trace(message_id="msg-2")])
        assert redis_conn.xlen(TRACE_STREAM) == 2

        response = client.delete("/api/traces")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Stream should be gone
        assert redis_conn.xlen(TRACE_STREAM) == 0

        # GET should now return empty
        response = client.get("/api/traces")
        assert response.json()["count"] == 0

    def test_delete_traces_when_already_empty(self, client, redis_conn):
        """DELETE /api/traces succeeds even when stream doesn't exist."""
        response = client.delete("/api/traces")
        assert response.status_code == 200


# ===== /api/traces/stats endpoint tests =====


@pytest.mark.redis
class TestTracesStatsEndpoint:
    def test_stats_returns_empty_when_no_data(self, client, redis_conn):
        """GET /api/traces/stats returns zero counts when no traces exist."""
        response = client.get("/api/traces/stats?window=5m")
        assert response.status_code == 200
        data = response.json()
        assert data["window"] == "5m"
        assert data["total"] == 0
        assert data["error_count"] == 0
        assert data["error_rate"] == 0.0
        assert data["avg_latency_ms"] == 0.0

    def test_stats_counts_events_by_type(self, client, redis_conn):
        """GET /api/traces/stats counts events by type from recent stream data."""
        # Seed traces with recent timestamps (these will fall within the 5m window
        # because they are added via XADD with auto-generated IDs = now)
        traces = [
            _make_trace(event="outbox.published", message_id="msg-1"),
            _make_trace(event="outbox.published", message_id="msg-2"),
            _make_trace(event="handler.completed", message_id="msg-1", duration_ms=10),
            _make_trace(event="handler.completed", message_id="msg-2", duration_ms=20),
            _make_trace(
                event="handler.failed", message_id="msg-3", status="error", error="oops"
            ),
        ]
        _seed_traces(redis_conn, traces)

        response = client.get("/api/traces/stats?window=5m")
        data = response.json()
        assert data["total"] == 5
        assert data["counts"]["outbox.published"] == 2
        assert data["counts"]["handler.completed"] == 2
        assert data["counts"]["handler.failed"] == 1

    def test_stats_computes_error_rate(self, client, redis_conn):
        """Error rate is computed as error_count / total * 100."""
        traces = [
            _make_trace(event="handler.completed", message_id="msg-1"),
            _make_trace(event="handler.completed", message_id="msg-2"),
            _make_trace(event="handler.completed", message_id="msg-3"),
            _make_trace(event="handler.failed", message_id="msg-4", status="error"),
            _make_trace(event="message.dlq", message_id="msg-5", status="error"),
        ]
        _seed_traces(redis_conn, traces)

        response = client.get("/api/traces/stats?window=5m")
        data = response.json()
        assert data["error_count"] == 2
        # 2/5 = 40%
        assert data["error_rate"] == 40.0

    def test_stats_computes_avg_latency(self, client, redis_conn):
        """Avg latency is mean of duration_ms from handler.completed events."""
        traces = [
            _make_trace(
                event="handler.completed", message_id="msg-1", duration_ms=10.0
            ),
            _make_trace(
                event="handler.completed", message_id="msg-2", duration_ms=30.0
            ),
            # This should NOT count toward latency (not handler.completed)
            _make_trace(event="handler.failed", message_id="msg-3", duration_ms=50.0),
        ]
        _seed_traces(redis_conn, traces)

        response = client.get("/api/traces/stats?window=5m")
        data = response.json()
        # (10 + 30) / 2 = 20.0
        assert data["avg_latency_ms"] == 20.0

    def test_stats_rejects_invalid_window(self, client):
        """Invalid window parameter returns 400."""
        response = client.get("/api/traces/stats?window=10m")
        assert response.status_code == 400
        assert "Invalid window" in response.json()["error"]

    def test_stats_supports_all_windows(self, client, redis_conn):
        """All valid windows (5m, 15m, 1h, 24h, 7d) return 200."""
        for window in ["5m", "15m", "1h", "24h", "7d"]:
            response = client.get(f"/api/traces/stats?window={window}")
            assert response.status_code == 200
            assert response.json()["window"] == window


# ===== MessageTrace payload serialization tests =====


class TestMessageTracePayload:
    def test_payload_included_when_set(self):
        """MessageTrace serialization includes payload field when provided."""
        trace = MessageTrace(
            event="outbox.published",
            domain="test",
            stream="test::order",
            message_id="msg-001",
            message_type="OrderPlaced",
            status="ok",
            payload={"order_id": "abc-123", "total": 99.99},
        )
        data = json.loads(trace.to_json())
        assert data["payload"] == {"order_id": "abc-123", "total": 99.99}

    def test_payload_none_when_not_set(self):
        """MessageTrace serialization has null payload when not provided."""
        trace = MessageTrace(
            event="handler.completed",
            domain="test",
            stream="test::entity",
            message_id="msg-001",
            message_type="TestEvent",
            status="ok",
        )
        data = json.loads(trace.to_json())
        assert data["payload"] is None


# ===== /api/traces message_id filter tests =====


@pytest.mark.redis
class TestTracesMessageIdFilter:
    def test_filter_by_message_id_returns_matching_traces(self, client, redis_conn):
        """GET /api/traces?message_id=xxx returns only traces for that message."""
        traces = [
            _make_trace(
                event="outbox.published", message_id="target-msg", stream="test::order"
            ),
            _make_trace(
                event="handler.completed", message_id="other-msg", stream="test::order"
            ),
            _make_trace(
                event="handler.started", message_id="target-msg", stream="test::order"
            ),
            _make_trace(
                event="handler.completed",
                message_id="target-msg",
                stream="test::order",
                duration_ms=22.0,
            ),
        ]
        _seed_traces(redis_conn, traces)

        response = client.get("/api/traces?message_id=target-msg")
        data = response.json()
        assert data["count"] == 3
        for t in data["traces"]:
            assert t["message_id"] == "target-msg"

    def test_filter_by_message_id_no_match_returns_empty(self, client, redis_conn):
        """GET /api/traces?message_id=xxx returns empty when no match found."""
        _seed_traces(redis_conn, [_make_trace(message_id="existing-msg")])

        response = client.get("/api/traces?message_id=nonexistent-msg")
        data = response.json()
        assert data["count"] == 0
        assert data["traces"] == []

    def test_filter_by_message_id_returns_all_lifecycle_events(
        self, client, redis_conn
    ):
        """message_id filter returns all lifecycle events without count limit."""
        # Seed more lifecycle events than the default count limit
        traces = [
            _make_trace(event="outbox.published", message_id="lifecycle-msg"),
            _make_trace(event="handler.started", message_id="lifecycle-msg"),
            _make_trace(event="handler.completed", message_id="lifecycle-msg"),
            _make_trace(event="message.acked", message_id="lifecycle-msg"),
        ]
        _seed_traces(redis_conn, traces)

        response = client.get("/api/traces?message_id=lifecycle-msg")
        data = response.json()
        assert data["count"] == 4


# ===== /api/traces payload in response tests =====


@pytest.mark.redis
class TestTracesPayloadInResponse:
    def test_traces_response_includes_payload(self, client, redis_conn):
        """GET /api/traces returns payload data when present in traces."""
        payload_data = {"user_id": "u-123", "email": "test@example.com"}
        traces = [
            _make_trace(
                event="outbox.published",
                message_id="msg-with-payload",
                payload=payload_data,
            ),
        ]
        _seed_traces(redis_conn, traces)

        response = client.get("/api/traces")
        data = response.json()
        assert data["count"] == 1
        assert data["traces"][0]["payload"] == payload_data

    def test_traces_response_handles_null_payload(self, client, redis_conn):
        """GET /api/traces returns null payload when not captured."""
        traces = [_make_trace(event="handler.completed", message_id="msg-no-payload")]
        _seed_traces(redis_conn, traces)

        response = client.get("/api/traces")
        data = response.json()
        assert data["count"] == 1
        assert data["traces"][0]["payload"] is None


# ===== Error path tests (no Redis needed) =====


@pytest.mark.no_test_domain
class TestTracesEndpointNoRedis:
    def test_traces_returns_503_when_no_redis(self):
        """GET /api/traces returns 503 when Redis is unavailable."""
        mock_domain = MagicMock()
        mock_domain.name = "mock"
        mock_domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        mock_domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        mock_broker = MagicMock(spec=[])  # No redis_instance attribute
        mock_domain.brokers.get.return_value = mock_broker

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/traces")
        assert response.status_code == 503
        assert response.json()["error"] == "Redis not available"

    def test_traces_stats_returns_503_when_no_redis(self):
        """GET /api/traces/stats returns 503 when Redis is unavailable."""
        mock_domain = MagicMock()
        mock_domain.name = "mock"
        mock_domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        mock_domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        mock_broker = MagicMock(spec=[])
        mock_domain.brokers.get.return_value = mock_broker

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/traces/stats?window=5m")
        assert response.status_code == 503
        assert response.json()["error"] == "Redis not available"

    def test_delete_traces_returns_503_when_no_redis(self):
        """DELETE /api/traces returns 503 when Redis is unavailable."""
        mock_domain = MagicMock()
        mock_domain.name = "mock"
        mock_domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        mock_domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        mock_broker = MagicMock(spec=[])
        mock_domain.brokers.get.return_value = mock_broker

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.delete("/api/traces")
        assert response.status_code == 503
        assert response.json()["error"] == "Redis not available"

    def test_traces_returns_500_when_xrevrange_fails(self):
        """GET /api/traces returns 500 when Redis XREVRANGE raises an error."""
        mock_domain = MagicMock()
        mock_domain.name = "mock"
        mock_domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        mock_domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        mock_redis = MagicMock()
        mock_redis.xrevrange.side_effect = Exception("Redis connection lost")
        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis
        mock_domain.brokers.get.return_value = mock_broker

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/traces")
        assert response.status_code == 500
        assert response.json()["error"] == "Failed to read traces"

    def test_traces_stats_returns_500_when_xrange_fails(self):
        """GET /api/traces/stats returns 500 when Redis XRANGE raises an error."""
        mock_domain = MagicMock()
        mock_domain.name = "mock"
        mock_domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        mock_domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        mock_redis = MagicMock()
        mock_redis.xrange.side_effect = Exception("Redis timeout")
        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis
        mock_domain.brokers.get.return_value = mock_broker

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/traces/stats?window=5m")
        assert response.status_code == 500
        assert response.json()["error"] == "Failed to read traces"

    def test_delete_traces_returns_500_when_delete_fails(self):
        """DELETE /api/traces returns 500 when Redis delete raises an error."""
        mock_domain = MagicMock()
        mock_domain.name = "mock"
        mock_domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        mock_domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        mock_redis = MagicMock()
        mock_redis.delete.side_effect = Exception("Redis connection refused")
        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis
        mock_domain.brokers.get.return_value = mock_broker

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.delete("/api/traces")
        assert response.status_code == 500
        assert response.json()["error"] == "Failed to delete traces"

    def test_get_redis_skips_domain_on_exception(self):
        """_get_redis continues to next domain when one raises an exception."""
        from protean.server.observatory.api import _get_redis

        # First domain raises, second has Redis
        mock_domain1 = MagicMock()
        mock_domain1.domain_context.return_value.__enter__ = MagicMock(
            side_effect=RuntimeError("broken")
        )
        mock_domain1.domain_context.return_value.__exit__ = MagicMock(
            return_value=False
        )

        mock_redis = MagicMock()
        mock_domain2 = MagicMock()
        mock_domain2.domain_context.return_value.__enter__ = MagicMock(
            return_value=None
        )
        mock_domain2.domain_context.return_value.__exit__ = MagicMock(
            return_value=False
        )
        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis
        mock_domain2.brokers.get.return_value = mock_broker

        result = _get_redis([mock_domain1, mock_domain2])
        assert result is mock_redis


@pytest.mark.no_test_domain
class TestTracesEdgeCases:
    """Test edge cases in trace processing: malformed data, bytes decoding, etc."""

    def _make_mock_redis_domain(self, mock_redis: MagicMock) -> MagicMock:
        mock_domain = MagicMock()
        mock_domain.name = "mock"
        mock_domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        mock_domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis
        mock_domain.brokers.get.return_value = mock_broker
        return mock_domain

    def test_traces_skips_entries_with_no_data_field(self):
        """Entries without a 'data' field are silently skipped."""
        mock_redis = MagicMock()
        # Return entry with no 'data' key
        mock_redis.xrevrange.return_value = [
            (b"1234-0", {b"other": b"value"}),
        ]
        mock_domain = self._make_mock_redis_domain(mock_redis)

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/traces")
        assert response.status_code == 200
        assert response.json()["count"] == 0

    def test_traces_handles_malformed_json(self):
        """Entries with invalid JSON are silently skipped."""
        mock_redis = MagicMock()
        mock_redis.xrevrange.return_value = [
            (b"1234-0", {b"data": b"not-valid-json{{{"}),
        ]
        mock_domain = self._make_mock_redis_domain(mock_redis)

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/traces")
        assert response.status_code == 200
        assert response.json()["count"] == 0

    def test_traces_decodes_bytes_stream_id(self):
        """Stream IDs returned as bytes are decoded to strings."""
        trace_data = json.dumps(_make_trace())
        mock_redis = MagicMock()
        mock_redis.xrevrange.return_value = [
            (b"1700000000000-0", {b"data": trace_data.encode()}),
        ]
        mock_domain = self._make_mock_redis_domain(mock_redis)

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/traces")
        data = response.json()
        assert data["count"] == 1
        assert data["traces"][0]["_stream_id"] == "1700000000000-0"

    def test_traces_decodes_string_stream_id(self):
        """Stream IDs returned as strings are handled correctly."""
        from protean.server.observatory.api import _decode_stream_id

        assert _decode_stream_id("1234-0") == "1234-0"
        assert _decode_stream_id(b"1234-0") == "1234-0"

    def test_traces_stats_skips_entries_with_no_data(self):
        """Stats endpoint skips entries without a 'data' field."""
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            (b"1234-0", {b"other": b"value"}),
        ]
        mock_domain = self._make_mock_redis_domain(mock_redis)

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/traces/stats?window=7d")
        data = response.json()
        assert data["total"] == 0

    def test_traces_stats_skips_malformed_json(self):
        """Stats endpoint skips entries with invalid JSON."""
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            (b"1234-0", {b"data": b"{{invalid"}),
        ]
        mock_domain = self._make_mock_redis_domain(mock_redis)

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/traces/stats?window=7d")
        data = response.json()
        assert data["total"] == 0

    def test_traces_stats_decodes_bytes_data(self):
        """Stats endpoint correctly decodes bytes data fields."""
        trace_data = json.dumps(
            _make_trace(event="handler.completed", duration_ms=25.0)
        )
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            (b"1234-0", {b"data": trace_data.encode("utf-8")}),
        ]
        mock_domain = self._make_mock_redis_domain(mock_redis)

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/traces/stats?window=7d")
        data = response.json()
        assert data["total"] == 1
        assert data["avg_latency_ms"] == 25.0
