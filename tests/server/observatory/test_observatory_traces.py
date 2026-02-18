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
    DEFAULT_TRACE_HISTORY_SIZE,
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
) -> dict:
    """Build a trace dict matching MessageTrace structure."""
    return {
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
        "timestamp": "2026-01-15T10:00:00+00:00",
    }


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
        """TraceEmitter enables persistence by default with DEFAULT_TRACE_HISTORY_SIZE."""
        emitter = TraceEmitter(test_domain)
        assert emitter._persist is True
        assert emitter._max_len == DEFAULT_TRACE_HISTORY_SIZE

    def test_emitter_persistence_disabled_when_zero(self, test_domain):
        """TraceEmitter disables persistence when trace_history_size=0."""
        emitter = TraceEmitter(test_domain, trace_history_size=0)
        assert emitter._persist is False

    def test_emit_writes_to_stream(self, test_domain, redis_conn):
        """emit() writes to the trace Redis Stream when persistence is enabled."""
        emitter = TraceEmitter(test_domain, trace_history_size=100)
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

    def test_emit_respects_maxlen(self, test_domain, redis_conn):
        """emit() caps the stream at approximately trace_history_size."""
        # Use a larger maxlen to make approximate trimming more effective.
        # Redis approximate trimming (MAXLEN ~) is imprecise for very small values.
        emitter = TraceEmitter(test_domain, trace_history_size=50)

        # Write significantly more events than the cap
        for i in range(120):
            emitter.emit(
                event="handler.completed",
                stream="test::entity",
                message_id=f"msg-{i:03d}",
                message_type="TestEvent",
            )

        # Stream should be roughly capped (approximate trimming allows some slack)
        stream_len = redis_conn.xlen(TRACE_STREAM)
        assert stream_len <= 80  # ~50 with approximate trimming
        assert stream_len >= 30  # But not aggressively trimmed below target

    def test_emit_does_not_write_when_persistence_disabled(
        self, test_domain, redis_conn
    ):
        """emit() skips stream write when persistence is disabled and no subscribers."""
        emitter = TraceEmitter(test_domain, trace_history_size=0)
        emitter.emit(
            event="handler.completed",
            stream="test::entity",
            message_id="msg-001",
            message_type="TestEvent",
        )

        stream_len = redis_conn.xlen(TRACE_STREAM)
        assert stream_len == 0

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
            emitter = TraceEmitter(test_domain, trace_history_size=100)
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
        """All valid windows (5m, 15m, 1h) return 200."""
        for window in ["5m", "15m", "1h"]:
            response = client.get(f"/api/traces/stats?window={window}")
            assert response.status_code == 200
            assert response.json()["window"] == window


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
