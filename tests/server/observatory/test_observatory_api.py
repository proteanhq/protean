"""Tests for Observatory REST API endpoints.

These tests require a running Redis instance and are gated behind @pytest.mark.redis.
Unit tests for error paths use mock domains and need no infrastructure.
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from protean.port.broker import DLQEntry
from protean.server.observatory import (
    Observatory,
    _GracefulShutdownMiddleware,
    create_observatory_app,
)
from protean.server.observatory.api import (
    _INTERNAL_STREAMS,
    _broker_health,
    _broker_info,
    _discover_streams,
    _outbox_status,
    _parse_worker_key,
)


@pytest.fixture
def observatory(test_domain):
    """Observatory instance backed by a real domain."""
    return Observatory(domains=[test_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


@pytest.mark.redis
class TestDashboardEndpoint:
    def test_dashboard_returns_html(self, client):
        """GET / returns 200 with HTML content."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


@pytest.mark.redis
class TestHealthEndpoint:
    def test_health_endpoint_returns_ok(self, client):
        """GET /api/health returns 200 with status."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "domains" in data
        assert "infrastructure" in data

    def test_health_shows_broker_details(self, client):
        """Health response includes broker details."""
        response = client.get("/api/health")
        data = response.json()
        broker_info = data["infrastructure"]["redis"]
        assert "healthy" in broker_info
        assert "version" in broker_info
        assert "connected_clients" in broker_info
        assert "memory" in broker_info
        assert "ops_per_sec" in broker_info

    def test_health_lists_domain_names(self, client, test_domain):
        """Health response lists monitored domain names."""
        response = client.get("/api/health")
        data = response.json()
        assert test_domain.name in data["domains"]


@pytest.mark.redis
class TestOutboxEndpoint:
    def test_outbox_returns_counts(self, client, test_domain):
        """GET /api/outbox returns outbox counts keyed by domain name."""
        response = client.get("/api/outbox")
        assert response.status_code == 200
        data = response.json()
        assert test_domain.name in data

    def test_outbox_domain_has_status_field(self, client, test_domain):
        """Each domain entry in outbox has a status field."""
        response = client.get("/api/outbox")
        data = response.json()
        domain_data = data[test_domain.name]
        assert "status" in domain_data


@pytest.mark.redis
class TestStreamsEndpoint:
    def test_streams_returns_message_counts(self, client):
        """GET /api/streams returns message_counts and consumer_groups."""
        response = client.get("/api/streams")
        assert response.status_code == 200
        data = response.json()
        assert "message_counts" in data
        assert "streams" in data
        assert "consumer_groups" in data


@pytest.mark.redis
class TestStatsEndpoint:
    def test_stats_combines_outbox_and_stream_data(self, client, test_domain):
        """GET /api/stats returns outbox + stream data."""
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "outbox" in data
        assert "message_counts" in data
        assert "streams" in data
        assert test_domain.name in data["outbox"]


# --- Unit tests for error/edge-case paths (no Redis needed) ---


def _make_mock_domain(name: str = "mock-domain") -> MagicMock:
    """Create a mock Domain that simulates a domain without a broker."""
    mock = MagicMock()
    mock.name = name
    mock.domain_context.return_value.__enter__ = MagicMock(return_value=None)
    mock.domain_context.return_value.__exit__ = MagicMock(return_value=False)
    return mock


class TestOutboxStatusErrorPaths:
    def test_returns_error_on_exception(self):
        """_outbox_status returns generic error when outbox query fails."""
        mock_domain = _make_mock_domain()
        mock_domain._get_outbox_repo.side_effect = RuntimeError("connection lost")

        result = _outbox_status(mock_domain)

        assert result["status"] == "error"
        assert result["error"] == "Failed to query outbox"
        assert "connection lost" not in result["error"]


class TestBrokerHealthErrorPaths:
    def test_returns_error_when_no_broker(self):
        """_broker_health returns error when no default broker is configured."""
        mock_domain = _make_mock_domain()
        mock_domain.brokers.get.return_value = None

        result = _broker_health(mock_domain)

        assert result["status"] == "error"
        assert result["error"] == "No default broker configured"

    def test_returns_error_on_exception(self):
        """_broker_health returns generic error when broker query fails."""
        mock_domain = _make_mock_domain()
        mock_domain.brokers.get.side_effect = RuntimeError("connection refused")

        result = _broker_health(mock_domain)

        assert result["status"] == "error"
        assert result["error"] == "Failed to query broker health"
        assert "connection refused" not in result["error"]


class TestBrokerInfoErrorPaths:
    def test_returns_error_when_no_broker(self):
        """_broker_info returns error when no default broker is configured."""
        mock_domain = _make_mock_domain()
        mock_domain.brokers.get.return_value = None

        result = _broker_info(mock_domain)

        assert result["status"] == "error"
        assert result["error"] == "No default broker configured"

    def test_returns_error_on_exception(self):
        """_broker_info returns generic error when broker query fails."""
        mock_domain = _make_mock_domain()
        mock_domain.brokers.get.side_effect = RuntimeError("timeout")

        result = _broker_info(mock_domain)

        assert result["status"] == "error"
        assert result["error"] == "Failed to query broker info"
        assert "timeout" not in result["error"]


class TestAPIEndpointsWithFailingDomain:
    """Test API endpoints gracefully handle domain failures."""

    @pytest.fixture
    def failing_client(self):
        """Client backed by a mock domain whose broker always fails."""
        mock_domain = _make_mock_domain("failing-domain")
        mock_domain.brokers.get.return_value = None
        mock_domain._get_outbox_repo.side_effect = RuntimeError("no outbox")

        observatory = Observatory(domains=[mock_domain])
        return TestClient(observatory.app)

    def test_health_endpoint_with_no_broker(self, failing_client):
        """Health endpoint returns structured response even when broker is missing."""
        response = failing_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "domains" in data

    def test_outbox_endpoint_with_failing_domain(self, failing_client):
        """Outbox endpoint returns error status when outbox query fails."""
        response = failing_client.get("/api/outbox")
        assert response.status_code == 200
        data = response.json()
        assert "failing-domain" in data
        assert data["failing-domain"]["status"] == "error"

    def test_streams_endpoint_with_no_broker(self, failing_client):
        """Streams endpoint returns empty data when broker is unavailable."""
        response = failing_client.get("/api/streams")
        assert response.status_code == 200

    def test_stats_endpoint_with_failures(self, failing_client):
        """Stats endpoint returns structured response even with failures."""
        response = failing_client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "outbox" in data
        assert data["outbox"]["failing-domain"]["status"] == "error"


# --- Tests for Observatory class and factory (observatory/__init__.py) ---


class TestObservatoryFactory:
    def test_create_observatory_app_returns_fastapi(self, test_domain):
        """create_observatory_app returns a FastAPI instance."""
        from fastapi import FastAPI

        app = create_observatory_app(domains=[test_domain], title="Test Observatory")
        assert isinstance(app, FastAPI)

    def test_create_observatory_app_custom_title(self, test_domain):
        """create_observatory_app passes title to Observatory."""
        app = create_observatory_app(domains=[test_domain], title="Custom Title")
        assert app.title == "Custom Title"


class TestObservatoryConfiguration:
    def test_cors_disabled(self, test_domain):
        """Observatory can be created with CORS disabled."""
        observatory = Observatory(domains=[test_domain], enable_cors=False)

        # Should still have a working app
        client = TestClient(observatory.app)
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_root_renders_overview_template(self, test_domain):
        """GET / renders the Jinja2 overview template (not the old monolithic HTML)."""
        observatory = Observatory(domains=[test_domain])
        client = TestClient(observatory.app)
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        # The overview template extends base.html which has the Observatory title
        assert "Observatory" in response.text


class TestGracefulShutdownMiddleware:
    """Tests for _GracefulShutdownMiddleware ASGI handling."""

    def test_non_http_scope_passes_through(self):
        """Non-HTTP scopes (e.g. websocket, lifespan) are forwarded unchanged."""
        calls = []

        async def inner_app(scope, receive, send):
            calls.append(scope["type"])

        middleware = _GracefulShutdownMiddleware(inner_app)
        asyncio.run(middleware({"type": "websocket"}, None, None))
        assert calls == ["websocket"]

    def test_cancelled_error_absorbed_after_response_started(self):
        """CancelledError is absorbed when response headers were already sent."""

        async def inner_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            raise asyncio.CancelledError()

        sent_messages = []

        async def mock_send(message):
            sent_messages.append(message)

        middleware = _GracefulShutdownMiddleware(inner_app)
        # Should not raise
        asyncio.run(middleware({"type": "http"}, None, mock_send))
        # Should have sent the start message and a final empty body
        assert sent_messages[0]["type"] == "http.response.start"
        assert sent_messages[1] == {
            "type": "http.response.body",
            "body": b"",
            "more_body": False,
        }

    def test_cancelled_error_absorbed_before_response_started(self):
        """CancelledError is absorbed even if no headers were sent yet."""

        async def inner_app(scope, receive, send):
            raise asyncio.CancelledError()

        middleware = _GracefulShutdownMiddleware(inner_app)
        # Should not raise
        asyncio.run(middleware({"type": "http"}, None, None))

    def test_cancelled_error_with_broken_send(self):
        """CancelledError handling tolerates send() failures."""

        async def inner_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            raise asyncio.CancelledError()

        async def broken_send(message):
            if message.get("type") == "http.response.body":
                raise ConnectionResetError("client gone")

        middleware = _GracefulShutdownMiddleware(inner_app)
        # Should not raise despite broken send
        asyncio.run(middleware({"type": "http"}, None, broken_send))


class TestObservatoryRun:
    def test_run_calls_uvicorn(self, test_domain):
        """Observatory.run() delegates to uvicorn.run()."""
        observatory = Observatory(domains=[test_domain])

        with patch("protean.server.observatory.uvicorn") as mock_uvicorn:
            observatory.run(host="127.0.0.1", port=8888)
            mock_uvicorn.run.assert_called_once_with(
                observatory.app, host="127.0.0.1", port=8888
            )


# --- Tests for _discover_streams (mock-based, no Redis) ---


class TestDiscoverStreams:
    """Unit tests for _discover_streams() stream discovery from Redis."""

    def test_returns_empty_when_redis_is_none(self):
        """_discover_streams(None) returns an empty list."""
        assert _discover_streams(None) == []

    def test_discovers_application_streams(self):
        """Discovers streams from Redis SCAN and returns them."""
        mock_redis = MagicMock()
        mock_redis.scan.return_value = (
            0,
            [b"identity::customer", b"catalogue::product"],
        )

        result = _discover_streams(mock_redis)

        assert result == ["catalogue::product", "identity::customer"]

    def test_excludes_internal_trace_stream(self):
        """Filters out internal streams (e.g. protean:traces)."""
        from protean.server.tracing import TRACE_STREAM

        mock_redis = MagicMock()
        mock_redis.scan.return_value = (
            0,
            [TRACE_STREAM.encode(), b"identity::customer"],
        )

        result = _discover_streams(mock_redis)

        assert result == ["identity::customer"]
        assert TRACE_STREAM in _INTERNAL_STREAMS

    def test_decodes_bytes_keys(self):
        """Byte keys from Redis are decoded to str."""
        mock_redis = MagicMock()
        mock_redis.scan.return_value = (0, [b"ordering::order"])

        result = _discover_streams(mock_redis)

        assert result == ["ordering::order"]
        assert isinstance(result[0], str)

    def test_handles_string_keys(self):
        """String keys (non-bytes) are handled correctly."""
        mock_redis = MagicMock()
        mock_redis.scan.return_value = (0, ["ordering::order"])

        result = _discover_streams(mock_redis)

        assert result == ["ordering::order"]

    def test_returns_sorted_results(self):
        """Results are sorted alphabetically."""
        mock_redis = MagicMock()
        mock_redis.scan.return_value = (
            0,
            [b"z-stream", b"a-stream", b"m-stream"],
        )

        result = _discover_streams(mock_redis)

        assert result == ["a-stream", "m-stream", "z-stream"]

    def test_returns_empty_on_redis_error(self):
        """Returns empty list when Redis raises an exception."""
        mock_redis = MagicMock()
        mock_redis.scan.side_effect = Exception("connection lost")

        result = _discover_streams(mock_redis)

        assert result == []

    def test_paginates_through_cursor(self):
        """Follows multi-page SCAN results until cursor returns to 0."""
        mock_redis = MagicMock()
        mock_redis.scan.side_effect = [
            (42, [b"identity::customer"]),  # First page, cursor=42
            (0, [b"catalogue::product"]),  # Second page, cursor=0 (done)
        ]

        result = _discover_streams(mock_redis)

        assert result == ["catalogue::product", "identity::customer"]
        assert mock_redis.scan.call_count == 2


# --- Tests for queue-depth endpoint ---


@pytest.mark.redis
class TestQueueDepthEndpoint:
    """Integration tests for /api/queue-depth."""

    def test_queue_depth_returns_structure(self, client):
        """Response has expected top-level keys."""
        response = client.get("/api/queue-depth")
        assert response.status_code == 200
        data = response.json()
        assert "timestamp" in data
        assert "outbox" in data
        assert "streams" in data
        assert "totals" in data

    def test_queue_depth_totals_have_expected_keys(self, client):
        """totals contains outbox_pending, stream_depth, consumer_pending."""
        response = client.get("/api/queue-depth")
        data = response.json()
        totals = data["totals"]
        assert "outbox_pending" in totals
        assert "stream_depth" in totals
        assert "consumer_pending" in totals


class TestQueueDepthWithMockDomain:
    """Queue-depth endpoint with a mock domain that has no broker."""

    def test_queue_depth_returns_zeros_when_no_broker(self):
        """totals are all zero when domain has no working broker."""
        mock_domain = _make_mock_domain("no-broker-domain")
        mock_domain.brokers.get.return_value = None
        mock_domain._get_outbox_repo.side_effect = RuntimeError("no outbox")

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/queue-depth")
        assert response.status_code == 200
        data = response.json()
        assert data["totals"]["outbox_pending"] == 0
        assert data["totals"]["stream_depth"] == 0
        assert data["totals"]["consumer_pending"] == 0


# --- Tests for _parse_worker_key() ---


class TestParseWorkerKey:
    """Unit tests for _parse_worker_key() that extracts (hostname, pid) from consumer names."""

    def test_standard_consumer_name(self):
        """Parses standard format: ClassName-hostname-pid-hex."""
        hostname, pid = _parse_worker_key("OrderProjector-worker01-12345-abcdef")
        assert hostname == "worker01"
        assert pid == "12345"

    def test_docker_container_id_as_hostname(self):
        """Parses consumer name where hostname is a Docker container ID with hyphens."""
        hostname, pid = _parse_worker_key("CustomerProjector-abc123def456-7890-ff00ee")
        assert hostname == "abc123def456"
        assert pid == "7890"

    def test_hostname_with_hyphens(self):
        """Parses consumer name where hostname contains hyphens."""
        hostname, pid = _parse_worker_key("MyHandler-my-long-host-99-1234-aabbcc")
        assert hostname == "my-long-host-99"
        assert pid == "1234"

    def test_fallback_for_no_hyphens(self):
        """Falls back to (consumer_name, '0') when no hyphens exist."""
        hostname, pid = _parse_worker_key("simplestring")
        assert hostname == "simplestring"
        assert pid == "0"

    def test_fallback_when_pid_not_numeric(self):
        """Falls back when second-to-last segment is not a PID."""
        hostname, pid = _parse_worker_key("Handler-notanumber-abcdef")
        assert hostname == "Handler-notanumber-abcdef"
        assert pid == "0"

    def test_two_segment_name(self):
        """Handles names with only two segments (too few to parse)."""
        hostname, pid = _parse_worker_key("Handler-abcdef")
        assert hostname == "Handler-abcdef"
        assert pid == "0"

    def test_class_name_without_hyphen_prefix(self):
        """Falls back when prefix has no hyphen (class name == entire prefix)."""
        # "X-1234-abcdef" → prefix="X", pid="1234", hex="abcdef"
        # prefix "X" has no hyphen, so first_hyphen == -1 → fallback
        hostname, pid = _parse_worker_key("X-1234-abcdef")
        assert hostname == "X-1234-abcdef"
        assert pid == "0"


# --- Tests for /api/consumers endpoint ---


@pytest.mark.redis
class TestConsumersEndpoint:
    """Integration tests for /api/consumers using real Redis."""

    def test_consumers_returns_structure(self, client):
        """GET /api/consumers returns expected top-level keys."""
        response = client.get("/api/consumers")
        assert response.status_code == 200
        data = response.json()
        assert "consumers" in data
        assert "count" in data
        assert isinstance(data["consumers"], list)
        assert data["count"] == len(data["consumers"])

    def test_consumers_shows_real_consumers_after_xreadgroup(self, client, test_domain):
        """Consumers appear after creating a stream, group, and reading with a consumer."""
        broker = test_domain.brokers.get("default")
        redis_conn = broker.redis_instance
        stream = "observatory-test::consumer-check"
        group = "TestConsumerGroup"
        consumer_name = "TestHandler-testhost-1234-aabbcc"

        # Create stream with a message, set up group, and read
        redis_conn.xadd(stream, {"data": "hello"})
        try:
            redis_conn.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception:
            pass  # Group may already exist
        redis_conn.xreadgroup(group, consumer_name, {stream: ">"}, count=1)

        response = client.get("/api/consumers")
        data = response.json()

        # Find our consumer in the results
        matching = [
            c
            for c in data["consumers"]
            if c["consumer_name"] == consumer_name and c["stream"] == stream
        ]
        assert len(matching) == 1
        entry = matching[0]
        assert entry["group"] == group
        assert entry["stream"] == stream
        assert "pending" in entry
        assert "idle_ms" in entry

    def test_consumers_returns_empty_when_no_streams(self, test_domain):
        """Returns empty list when no application streams exist (fresh database)."""
        # Use a fresh domain with a fresh Redis database
        broker = test_domain.brokers.get("default")
        broker.redis_instance.flushdb()

        observatory = Observatory(domains=[test_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/consumers")
        data = response.json()
        assert isinstance(data["consumers"], list)
        assert data["count"] == 0


class TestConsumersEndpointNoRedis:
    """Error-path tests for /api/consumers when Redis is unavailable."""

    def test_consumers_returns_503_when_no_redis(self):
        """Returns 503 with error when Redis is unavailable."""
        mock_domain = _make_mock_domain("no-redis")
        mock_domain.brokers.get.return_value = None

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/consumers")
        assert response.status_code == 503
        data = response.json()
        assert data["error"] == "Redis not available"
        assert data["consumers"] == []
        assert data["count"] == 0


# --- Tests for /api/workers endpoint ---


@pytest.mark.redis
class TestWorkersEndpoint:
    """Integration tests for /api/workers using real Redis."""

    def test_workers_returns_structure(self, client):
        """GET /api/workers returns expected top-level keys."""
        response = client.get("/api/workers")
        assert response.status_code == 200
        data = response.json()
        assert "workers" in data
        assert "count" in data
        assert "timestamp" in data
        assert isinstance(data["workers"], list)

    def test_workers_groups_consumers_by_host_and_pid(self, client, test_domain):
        """Workers endpoint groups consumers from the same engine instance."""
        broker = test_domain.brokers.get("default")
        redis_conn = broker.redis_instance

        stream = "observatory-test::workers-grouping"
        group = "WorkerGroupTestHandler"

        # Simulate two workers (different hostname-pid) with consumers
        consumer_w1 = "WorkerGroupTestHandler-host1-1000-aaa111"
        consumer_w2 = "WorkerGroupTestHandler-host2-2000-bbb222"

        redis_conn.xadd(stream, {"data": "msg1"})
        redis_conn.xadd(stream, {"data": "msg2"})
        try:
            redis_conn.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception:
            pass

        redis_conn.xreadgroup(group, consumer_w1, {stream: ">"}, count=1)
        redis_conn.xreadgroup(group, consumer_w2, {stream: ">"}, count=1)

        response = client.get("/api/workers")
        data = response.json()
        assert data["count"] >= 2

        workers_by_id = {w["worker_id"]: w for w in data["workers"]}
        assert "host1-1000" in workers_by_id
        assert "host2-2000" in workers_by_id

        w1 = workers_by_id["host1-1000"]
        assert w1["hostname"] == "host1"
        assert w1["pid"] == 1000
        assert w1["subscription_count"] >= 1

    def test_workers_throughput_structure(self, client, test_domain):
        """Each worker has throughput object with sparkline fields."""
        broker = test_domain.brokers.get("default")
        redis_conn = broker.redis_instance

        stream = "observatory-test::workers-throughput"
        group = "ThroughputHandler"
        consumer = "ThroughputHandler-sparkhost-999-ccddee"

        redis_conn.xadd(stream, {"data": "msg"})
        try:
            redis_conn.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception:
            pass
        redis_conn.xreadgroup(group, consumer, {stream: ">"}, count=1)

        response = client.get("/api/workers")
        data = response.json()

        # Find our worker
        worker = None
        for w in data["workers"]:
            if w["worker_id"] == "sparkhost-999":
                worker = w
                break
        assert worker is not None

        tp = worker["throughput"]
        assert tp["window_seconds"] == 300
        assert tp["bucket_seconds"] == 10
        assert isinstance(tp["counts"], list)
        assert len(tp["counts"]) == 30  # 300s / 10s = 30 buckets
        assert "total" in tp

    def test_workers_active_when_recently_read(self, client, test_domain):
        """Worker that just read a message has low idle and is marked 'active'."""
        broker = test_domain.brokers.get("default")
        redis_conn = broker.redis_instance

        stream = "observatory-test::workers-active"
        group = "ActiveHandler"
        consumer = "ActiveHandler-activehost-111-ffffff"

        redis_conn.xadd(stream, {"data": "msg"})
        try:
            redis_conn.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception:
            pass
        # Read immediately — idle will be near 0
        redis_conn.xreadgroup(group, consumer, {stream: ">"}, count=1)

        response = client.get("/api/workers")
        data = response.json()

        worker = None
        for w in data["workers"]:
            if w["worker_id"] == "activehost-111":
                worker = w
                break
        assert worker is not None
        assert worker["status"] == "active"

    def test_workers_includes_subscriptions_list(self, client, test_domain):
        """Each worker has a list of its subscriptions (consumer entries)."""
        broker = test_domain.brokers.get("default")
        redis_conn = broker.redis_instance

        stream1 = "observatory-test::workers-subs-a"
        stream2 = "observatory-test::workers-subs-b"
        group1 = "SubsHandlerA"
        group2 = "SubsHandlerB"
        # Same host-pid, different handlers
        consumer1 = "SubsHandlerA-subshost-555-aaa"
        consumer2 = "SubsHandlerB-subshost-555-bbb"

        for stream, group, consumer in [
            (stream1, group1, consumer1),
            (stream2, group2, consumer2),
        ]:
            redis_conn.xadd(stream, {"data": "msg"})
            try:
                redis_conn.xgroup_create(stream, group, id="0", mkstream=True)
            except Exception:
                pass
            redis_conn.xreadgroup(group, consumer, {stream: ">"}, count=1)

        response = client.get("/api/workers")
        data = response.json()

        worker = None
        for w in data["workers"]:
            if w["worker_id"] == "subshost-555":
                worker = w
                break
        assert worker is not None
        assert worker["subscription_count"] == 2
        assert len(worker["subscriptions"]) == 2


class TestWorkersEndpointNoRedis:
    """Error-path tests for /api/workers when Redis is unavailable."""

    def test_workers_returns_503_when_no_redis(self):
        """Returns 503 with error when Redis is unavailable."""
        mock_domain = _make_mock_domain("no-redis")
        mock_domain.brokers.get.return_value = None

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/workers")
        assert response.status_code == 503
        data = response.json()
        assert data["error"] == "Redis not available"
        assert data["workers"] == []
        assert data["count"] == 0


class TestWorkersStatusThresholds:
    """Tests for worker status derivation.

    These use mocks because idle_ms thresholds are time-dependent and
    cannot be reliably controlled with real Redis.
    """

    def _make_client_with_idle(self, idle_ms: int) -> TestClient:
        """Create a client whose single worker has the specified idle_ms."""
        mock_domain = _make_mock_domain("test")
        mock_redis = MagicMock()
        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis
        mock_domain.brokers.get.return_value = mock_broker

        mock_redis.scan.return_value = (0, [b"test::stream"])
        mock_redis.xinfo_groups.return_value = [
            {"name": "Handler", "pending": 0, "lag": 0}
        ]
        mock_redis.xinfo_consumers.return_value = [
            {"name": "Handler-host1-1000-abc", "pending": 0, "idle": idle_ms}
        ]
        mock_redis.xrange.return_value = []  # No trace throughput

        observatory = Observatory(domains=[mock_domain])
        return TestClient(observatory.app)

    def test_status_active_when_idle_below_threshold(self):
        """Worker with idle < 5min is 'active'."""
        client = self._make_client_with_idle(1000)
        data = client.get("/api/workers").json()
        assert data["workers"][0]["status"] == "active"

    def test_status_idle_when_between_thresholds(self):
        """Worker with 5min < idle < 30min is 'idle'."""
        client = self._make_client_with_idle(600_000)  # 10 minutes
        data = client.get("/api/workers").json()
        assert data["workers"][0]["status"] == "idle"

    def test_status_offline_when_above_idle_threshold(self):
        """Worker with idle > 30min is 'offline'."""
        client = self._make_client_with_idle(3_600_000)  # 60 minutes
        data = client.get("/api/workers").json()
        assert data["workers"][0]["status"] == "offline"

    def test_status_active_with_trace_throughput_overrides_idle(self):
        """Worker with trace throughput is 'active' even with high idle."""
        mock_domain = _make_mock_domain("test")
        mock_redis = MagicMock()
        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis
        mock_domain.brokers.get.return_value = mock_broker

        mock_redis.scan.return_value = (0, [b"test::stream"])
        mock_redis.xinfo_groups.return_value = [
            {"name": "Handler", "pending": 0, "lag": 0}
        ]
        mock_redis.xinfo_consumers.return_value = [
            {"name": "Handler-host1-1000-abc123", "pending": 0, "idle": 3_600_000}
        ]

        import time

        now_ms = int(time.time() * 1000)
        trace_data = json.dumps(
            {"event": "handler.completed", "worker_id": "Handler-host1-1000-abc123"}
        )
        mock_redis.xrange.return_value = [
            (f"{now_ms - 1000}-0".encode(), {b"data": trace_data.encode()}),
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        data = client.get("/api/workers").json()
        worker = data["workers"][0]
        assert worker["status"] == "active"
        assert worker["throughput"]["total"] == 1


# --- Helper for mock domain with working broker ---


def _make_mock_domain_with_broker(
    name: str = "test",
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Create a mock Domain with a functioning mock broker and Redis.

    Returns (mock_domain, mock_broker, mock_redis).
    """
    mock = MagicMock()
    mock.name = name
    mock.domain_context.return_value.__enter__ = MagicMock(return_value=None)
    mock.domain_context.return_value.__exit__ = MagicMock(return_value=False)
    mock_broker = MagicMock()
    mock_redis = MagicMock()
    mock_broker.redis_instance = mock_redis
    mock.brokers.get.return_value = mock_broker
    return mock, mock_broker, mock_redis


def _make_dlq_entry(
    dlq_id: str = "1234-0",
    original_id: str = "orig-1",
    stream: str = "orders::order",
    consumer_group: str = "OrderHandler",
    failure_reason: str = "ValueError: bad data",
    failed_at: str = "2026-03-04T10:00:00Z",
    retry_count: int = 3,
    dlq_stream: str = "orders::order:dlq",
    payload: dict | None = None,
) -> DLQEntry:
    """Create a DLQEntry for testing."""
    return DLQEntry(
        dlq_id=dlq_id,
        original_id=original_id,
        stream=stream,
        consumer_group=consumer_group,
        payload=payload or {"type": "OrderPlaced", "data": {"order_id": "123"}},
        failure_reason=failure_reason,
        failed_at=failed_at,
        retry_count=retry_count,
        dlq_stream=dlq_stream,
    )


# --- Tests for _broker_info success path ---


class TestBrokerInfoSuccessPath:
    """Tests for _broker_info when broker is available and responds."""

    def test_returns_ok_with_broker_info(self):
        """_broker_info returns status ok with broker info when broker works."""
        mock_domain = _make_mock_domain("test-domain")
        mock_broker = MagicMock()
        mock_broker.info.return_value = {
            "consumer_groups": 5,
            "streams": ["orders::order"],
        }
        mock_domain.brokers.get.return_value = mock_broker

        result = _broker_info(mock_domain)

        assert result["status"] == "ok"
        assert result["consumer_groups"] == 5
        assert result["streams"] == ["orders::order"]


# --- Tests for streams endpoint with stream aggregation and consumer groups ---


class TestStreamsEndpointWithMockRedis:
    """Mock-based tests for /api/streams covering stream aggregation."""

    def test_streams_aggregates_xlen_and_consumer_groups(self):
        """Streams endpoint aggregates xlen and consumer group data."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_redis.scan.return_value = (
            0,
            [b"orders::order", b"inventory::product"],
        )
        mock_redis.xlen.side_effect = [100, 50]  # orders=100, inventory=50
        mock_redis.xinfo_groups.side_effect = [
            [{"name": "OrderHandler", "pending": 5, "lag": 10}],
            [{"name": "ProductHandler", "pending": 3, "lag": 7}],
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/streams")
        assert response.status_code == 200
        data = response.json()

        assert data["message_counts"]["total_messages"] == 150
        assert data["message_counts"]["in_flight"] == 8
        assert data["streams"]["count"] == 2
        assert "OrderHandler" in data["consumer_groups"]
        assert data["consumer_groups"]["OrderHandler"]["pending"] == 5
        assert data["consumer_groups"]["OrderHandler"]["lag"] == 10

    def test_streams_handles_bytes_keys_in_consumer_groups(self):
        """Streams endpoint handles consumer group dicts with bytes keys."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xlen.return_value = 42
        mock_redis.xinfo_groups.return_value = [
            {b"name": b"OrderHandler", b"pending": 3, b"lag": 5}
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/streams")
        data = response.json()

        assert data["message_counts"]["total_messages"] == 42
        assert data["message_counts"]["in_flight"] == 3
        assert "OrderHandler" in data["consumer_groups"]
        assert data["consumer_groups"]["OrderHandler"]["pending"] == 3
        assert data["consumer_groups"]["OrderHandler"]["lag"] == 5

    def test_streams_handles_mixed_string_and_bytes_keys(self):
        """Streams endpoint handles dicts with a mix of string and bytes keys."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xlen.return_value = 10
        # Dict with string "name" but bytes "pending"
        mock_redis.xinfo_groups.return_value = [
            {"name": "MixedHandler", b"pending": 7, "lag": 2}
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/streams")
        data = response.json()

        assert data["message_counts"]["in_flight"] == 7
        assert "MixedHandler" in data["consumer_groups"]

    def test_streams_skips_non_dict_group_entries(self):
        """Streams endpoint skips group entries that are not dicts."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xlen.return_value = 10
        mock_redis.xinfo_groups.return_value = [
            "not-a-dict",
            {"name": "RealHandler", "pending": 1, "lag": 0},
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/streams")
        data = response.json()

        assert data["message_counts"]["in_flight"] == 1
        assert "RealHandler" in data["consumer_groups"]

    def test_streams_handles_xinfo_groups_exception(self):
        """Streams endpoint handles exceptions from xinfo_groups gracefully."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xlen.side_effect = Exception("Redis error")

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/streams")
        assert response.status_code == 200
        data = response.json()
        # Totals remain zero on error
        assert data["message_counts"]["total_messages"] == 0


# --- Tests for consumers endpoint with bytes handling ---


class TestConsumersEndpointBytesHandling:
    """Tests for /api/consumers when Redis returns bytes keys."""

    def test_consumers_decodes_bytes_group_and_consumer_names(self):
        """Consumer endpoint decodes bytes keys in group and consumer info."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xinfo_groups.return_value = [
            {b"name": b"OrderHandler", "pending": 0, "lag": 0}
        ]
        mock_redis.xinfo_consumers.return_value = [
            {
                b"name": b"OrderHandler-host1-1000-abc123",
                b"pending": 2,
                b"idle": 5000,
            }
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/consumers")
        assert response.status_code == 200
        data = response.json()

        assert data["count"] == 1
        entry = data["consumers"][0]
        assert entry["consumer_name"] == "OrderHandler-host1-1000-abc123"
        assert entry["group"] == "OrderHandler"
        assert entry["stream"] == "orders::order"
        assert entry["pending"] == 2
        assert entry["idle_ms"] == 5000

    def test_consumers_handles_mixed_bytes_and_string_keys(self):
        """Consumer endpoint handles dicts with mixed bytes/string keys."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xinfo_groups.return_value = [
            {"name": "OrderHandler", b"pending": 0, "lag": 0}
        ]
        mock_redis.xinfo_consumers.return_value = [
            {
                "name": "OrderHandler-host1-1000-abc123",
                b"pending": 1,
                "idle": 3000,
            }
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/consumers")
        data = response.json()

        assert data["count"] == 1
        entry = data["consumers"][0]
        assert entry["pending"] == 1
        assert entry["idle_ms"] == 3000

    def test_consumers_skips_non_dict_consumer_entries(self):
        """Consumer endpoint skips consumer entries that are not dicts."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xinfo_groups.return_value = [
            {"name": "OrderHandler", "pending": 0, "lag": 0}
        ]
        mock_redis.xinfo_consumers.return_value = [
            "not-a-dict",
            {"name": "OrderHandler-host1-1000-abc123", "pending": 0, "idle": 0},
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/consumers")
        data = response.json()
        assert data["count"] == 1

    def test_consumers_skips_group_with_no_name(self):
        """Consumer endpoint skips groups where name resolves to None."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xinfo_groups.return_value = [
            {"pending": 0, "lag": 0},  # no "name" key at all
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/consumers")
        data = response.json()
        assert data["count"] == 0


# --- Tests for queue-depth endpoint stream aggregation ---


class TestQueueDepthStreamAggregation:
    """Mock-based tests for /api/queue-depth covering Redis stream aggregation."""

    def test_queue_depth_aggregates_lag_and_pending(self):
        """Queue depth totals include stream_depth (max lag) and consumer_pending."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_domain._get_outbox_repo.side_effect = RuntimeError("no outbox")

        # _discover_streams sorts alphabetically, so inventory comes first
        mock_redis.scan.return_value = (
            0,
            [b"orders::order", b"inventory::product"],
        )
        # xlen called in sorted order: inventory::product=100, orders::order=200
        mock_redis.xlen.side_effect = [100, 200]
        mock_redis.xinfo_groups.side_effect = [
            # inventory::product has 1 consumer group
            [
                {"name": "ProductHandler", "pending": 2, "lag": 8},
            ],
            # orders::order has 2 consumer groups
            [
                {"name": "OrderHandler", "pending": 5, "lag": 20},
                {"name": "OrderProjector", "pending": 3, "lag": 15},
            ],
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/queue-depth")
        assert response.status_code == 200
        data = response.json()

        # stream_depth = max lag across groups per stream, summed
        # inventory: max(8) = 8, orders: max(20, 15) = 20 => total = 28
        assert data["totals"]["stream_depth"] == 28
        # consumer_pending = sum of all pending
        assert data["totals"]["consumer_pending"] == 10  # 2 + 5 + 3

        # Per-stream detail
        assert "orders::order" in data["streams"]
        assert data["streams"]["orders::order"]["length"] == 200
        assert "OrderHandler" in data["streams"]["orders::order"]["consumer_groups"]
        assert (
            data["streams"]["orders::order"]["consumer_groups"]["OrderHandler"][
                "pending"
            ]
            == 5
        )

    def test_queue_depth_handles_bytes_keys_in_groups(self):
        """Queue depth handles consumer group dicts with bytes keys."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_domain._get_outbox_repo.side_effect = RuntimeError("no outbox")

        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xlen.return_value = 50
        mock_redis.xinfo_groups.return_value = [
            {b"name": b"OrderHandler", b"pending": 4, b"lag": 12}
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/queue-depth")
        data = response.json()

        assert data["totals"]["stream_depth"] == 12
        assert data["totals"]["consumer_pending"] == 4

    def test_queue_depth_handles_xlen_exception(self):
        """Queue depth handles Redis xlen exceptions gracefully."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_domain._get_outbox_repo.side_effect = RuntimeError("no outbox")

        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xlen.side_effect = Exception("Redis error")

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/queue-depth")
        assert response.status_code == 200
        data = response.json()

        # Totals remain zero when Redis errors
        assert data["totals"]["stream_depth"] == 0
        assert data["totals"]["consumer_pending"] == 0


# --- Tests for stats endpoint stream aggregation ---


class TestStatsEndpointStreamAggregation:
    """Mock-based tests for /api/stats covering Redis stream aggregation."""

    def test_stats_aggregates_xlen_and_pending(self):
        """Stats endpoint aggregates total_messages and in_flight counts."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_domain._get_outbox_repo.side_effect = RuntimeError("no outbox")

        mock_redis.scan.return_value = (
            0,
            [b"orders::order", b"inventory::product"],
        )
        mock_redis.xlen.side_effect = [100, 75]
        mock_redis.xinfo_groups.side_effect = [
            [{"name": "OrderHandler", "pending": 4, "lag": 0}],
            [
                {"name": "ProductHandler", "pending": 2, "lag": 0},
                {"name": "ProductProjector", "pending": 1, "lag": 0},
            ],
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()

        assert data["message_counts"]["total_messages"] == 175
        assert data["message_counts"]["in_flight"] == 7  # 4 + 2 + 1
        assert data["streams"]["count"] == 2

    def test_stats_handles_bytes_keys_in_groups(self):
        """Stats endpoint handles consumer group dicts with bytes keys."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_domain._get_outbox_repo.side_effect = RuntimeError("no outbox")

        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xlen.return_value = 30
        mock_redis.xinfo_groups.return_value = [
            {b"name": b"OrderHandler", b"pending": 6, "lag": 0}
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/stats")
        data = response.json()

        assert data["message_counts"]["total_messages"] == 30
        assert data["message_counts"]["in_flight"] == 6

    def test_stats_handles_xlen_exception(self):
        """Stats endpoint handles exceptions from stream queries gracefully."""
        mock_domain, mock_broker, mock_redis = _make_mock_domain_with_broker()
        mock_domain._get_outbox_repo.side_effect = RuntimeError("no outbox")

        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xlen.side_effect = Exception("Redis error")

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()

        assert data["message_counts"]["total_messages"] == 0
        assert data["message_counts"]["in_flight"] == 0


# --- Tests for DLQ list endpoint ---


class TestDLQListEndpoint:
    """Tests for GET /api/dlq."""

    def test_dlq_list_returns_entries(self):
        """DLQ list returns entries from the broker."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True

        entries = [
            _make_dlq_entry(dlq_id="1-0", original_id="orig-1"),
            _make_dlq_entry(dlq_id="2-0", original_id="orig-2"),
        ]
        mock_broker.dlq_list.return_value = entries

        with patch("protean.utils.dlq.collect_dlq_streams") as mock_collect:
            mock_collect.return_value = ["orders::order:dlq"]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.get("/api/dlq")
            assert response.status_code == 200
            data = response.json()

            assert data["total_count"] == 2
            assert data["entries"][0]["dlq_id"] == "1-0"
            assert data["entries"][1]["dlq_id"] == "2-0"
            assert data["entries"][0]["failure_reason"] == "ValueError: bad data"

    def test_dlq_list_with_subscription_filter(self):
        """DLQ list filters by subscription when query param provided."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True

        entries = [_make_dlq_entry(dlq_id="1-0")]
        mock_broker.dlq_list.return_value = entries

        mock_info = MagicMock()
        mock_info.stream_category = "orders::order"
        mock_info.dlq_stream = "orders::order:dlq"
        mock_info.backfill_dlq_stream = None

        with patch("protean.utils.dlq.discover_subscriptions") as mock_discover:
            mock_discover.return_value = [mock_info]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.get("/api/dlq?subscription=orders::order")
            assert response.status_code == 200
            data = response.json()
            assert data["total_count"] == 1

    def test_dlq_list_with_subscription_filter_includes_backfill(self):
        """DLQ list includes backfill DLQ stream when present."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True

        entries = [_make_dlq_entry(dlq_id="1-0")]
        mock_broker.dlq_list.return_value = entries

        mock_info = MagicMock()
        mock_info.stream_category = "orders::order"
        mock_info.dlq_stream = "orders::order:dlq"
        mock_info.backfill_dlq_stream = "orders::order:backfill:dlq"

        with patch("protean.utils.dlq.discover_subscriptions") as mock_discover:
            mock_discover.return_value = [mock_info]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.get("/api/dlq?subscription=orders::order")
            assert response.status_code == 200

            # Verify dlq_list was called with both streams
            call_args = mock_broker.dlq_list.call_args[0][0]
            assert "orders::order:dlq" in call_args
            assert "orders::order:backfill:dlq" in call_args

    def test_dlq_list_subscription_not_found(self):
        """DLQ list returns 404 when subscription filter matches nothing."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True

        with patch("protean.utils.dlq.discover_subscriptions") as mock_discover:
            mock_discover.return_value = []

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.get("/api/dlq?subscription=nonexistent::stream")
            assert response.status_code == 404
            assert "No subscription" in response.json()["error"]

    def test_dlq_list_no_broker(self):
        """DLQ list returns 503 when no broker configured."""
        mock_domain = _make_mock_domain("no-broker")
        mock_domain.brokers.get.return_value = None

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/dlq")
        assert response.status_code == 503
        assert response.json()["error"] == "No default broker configured"

    def test_dlq_list_broker_no_capability(self):
        """DLQ list returns 501 when broker lacks DLQ capability."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = False

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/dlq")
        assert response.status_code == 501
        assert response.json()["error"] == "Broker does not support DLQ"

    def test_dlq_list_handles_exception(self):
        """DLQ list returns 500 on unexpected exception."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.side_effect = RuntimeError("unexpected")

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/dlq")
        assert response.status_code == 500
        assert response.json()["error"] == "Failed to list DLQ messages"


# --- Tests for DLQ inspect endpoint ---


class TestDLQInspectEndpoint:
    """Tests for GET /api/dlq/{dlq_id}."""

    def test_dlq_inspect_returns_entry_with_payload(self):
        """DLQ inspect returns entry details including payload."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True

        entry = _make_dlq_entry(
            dlq_id="1-0",
            payload={
                "type": "OrderPlaced",
                "data": {"order_id": "123"},
                "_dlq_metadata": {"internal": "hidden"},
            },
        )
        mock_broker.dlq_inspect.return_value = entry

        with patch("protean.utils.dlq.collect_dlq_streams") as mock_collect:
            mock_collect.return_value = ["orders::order:dlq"]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.get("/api/dlq/1-0")
            assert response.status_code == 200
            data = response.json()

            assert data["dlq_id"] == "1-0"
            assert data["original_id"] == "orig-1"
            assert data["stream"] == "orders::order"
            assert data["consumer_group"] == "OrderHandler"
            assert data["failure_reason"] == "ValueError: bad data"
            assert data["retry_count"] == 3
            # _dlq_metadata should be stripped from payload
            assert "_dlq_metadata" not in data["payload"]
            assert data["payload"]["type"] == "OrderPlaced"

    def test_dlq_inspect_not_found(self):
        """DLQ inspect returns 404 when message is not in any DLQ stream."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True
        mock_broker.dlq_inspect.return_value = None

        with patch("protean.utils.dlq.collect_dlq_streams") as mock_collect:
            mock_collect.return_value = ["orders::order:dlq"]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.get("/api/dlq/nonexistent-id")
            assert response.status_code == 404
            assert "not found" in response.json()["error"]

    def test_dlq_inspect_searches_multiple_streams(self):
        """DLQ inspect searches across multiple DLQ streams."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True

        entry = _make_dlq_entry(dlq_id="2-0", dlq_stream="inventory::product:dlq")
        # Not found in first stream, found in second
        mock_broker.dlq_inspect.side_effect = [None, entry]

        with patch("protean.utils.dlq.collect_dlq_streams") as mock_collect:
            mock_collect.return_value = [
                "orders::order:dlq",
                "inventory::product:dlq",
            ]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.get("/api/dlq/2-0")
            assert response.status_code == 200
            assert response.json()["dlq_id"] == "2-0"

    def test_dlq_inspect_no_broker(self):
        """DLQ inspect returns 503 when broker is unavailable."""
        mock_domain = _make_mock_domain("no-broker")
        mock_domain.brokers.get.return_value = None

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/dlq/some-id")
        assert response.status_code == 503
        assert response.json()["error"] == "DLQ not available"

    def test_dlq_inspect_no_capability(self):
        """DLQ inspect returns 503 when broker lacks DLQ capability."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = False

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/dlq/some-id")
        assert response.status_code == 503
        assert response.json()["error"] == "DLQ not available"

    def test_dlq_inspect_handles_exception(self):
        """DLQ inspect returns 500 on unexpected exception."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.side_effect = RuntimeError("unexpected")

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/dlq/some-id")
        assert response.status_code == 500
        assert response.json()["error"] == "Failed to inspect DLQ message"


# --- Tests for DLQ replay endpoint ---


class TestDLQReplayEndpoint:
    """Tests for POST /api/dlq/{dlq_id}/replay."""

    def test_dlq_replay_success(self):
        """DLQ replay replays a message back to its original stream."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True

        entry = _make_dlq_entry(dlq_id="1-0", stream="orders::order")
        mock_broker.dlq_inspect.return_value = entry
        mock_broker.dlq_replay.return_value = True

        with patch("protean.utils.dlq.collect_dlq_streams") as mock_collect:
            mock_collect.return_value = ["orders::order:dlq"]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.post("/api/dlq/1-0/replay")
            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "ok"
            assert data["replayed"] is True
            assert data["target_stream"] == "orders::order"

    def test_dlq_replay_failure(self):
        """DLQ replay returns 500 when replay operation fails."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True

        entry = _make_dlq_entry(dlq_id="1-0")
        mock_broker.dlq_inspect.return_value = entry
        mock_broker.dlq_replay.return_value = False

        with patch("protean.utils.dlq.collect_dlq_streams") as mock_collect:
            mock_collect.return_value = ["orders::order:dlq"]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.post("/api/dlq/1-0/replay")
            assert response.status_code == 500
            assert response.json()["error"] == "Replay failed"

    def test_dlq_replay_not_found(self):
        """DLQ replay returns 404 when message is not in any DLQ stream."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True
        mock_broker.dlq_inspect.return_value = None

        with patch("protean.utils.dlq.collect_dlq_streams") as mock_collect:
            mock_collect.return_value = ["orders::order:dlq"]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.post("/api/dlq/nonexistent-id/replay")
            assert response.status_code == 404
            assert "not found" in response.json()["error"]

    def test_dlq_replay_no_broker(self):
        """DLQ replay returns 503 when broker is unavailable."""
        mock_domain = _make_mock_domain("no-broker")
        mock_domain.brokers.get.return_value = None

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.post("/api/dlq/some-id/replay")
        assert response.status_code == 503
        assert response.json()["error"] == "DLQ not available"

    def test_dlq_replay_no_capability(self):
        """DLQ replay returns 503 when broker lacks DLQ capability."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = False

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.post("/api/dlq/some-id/replay")
        assert response.status_code == 503
        assert response.json()["error"] == "DLQ not available"

    def test_dlq_replay_handles_exception(self):
        """DLQ replay returns 500 on unexpected exception."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.side_effect = RuntimeError("unexpected")

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.post("/api/dlq/some-id/replay")
        assert response.status_code == 500
        assert response.json()["error"] == "Failed to replay DLQ message"


# --- Tests for DLQ replay-all endpoint ---


class TestDLQReplayAllEndpoint:
    """Tests for POST /api/dlq/replay-all."""

    def test_dlq_replay_all_success(self):
        """DLQ replay-all replays all messages for a subscription."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True
        mock_broker.dlq_replay_all.return_value = 5

        mock_info = MagicMock()
        mock_info.stream_category = "orders::order"
        mock_info.dlq_stream = "orders::order:dlq"
        mock_info.backfill_dlq_stream = None

        with patch("protean.utils.dlq.discover_subscriptions") as mock_discover:
            mock_discover.return_value = [mock_info]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.post("/api/dlq/replay-all?subscription=orders::order")
            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "ok"
            assert data["replayed"] == 5
            assert data["target_stream"] == "orders::order"

    def test_dlq_replay_all_with_backfill(self):
        """DLQ replay-all includes backfill DLQ streams."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True
        mock_broker.dlq_replay_all.side_effect = [3, 2]  # primary=3, backfill=2

        mock_info = MagicMock()
        mock_info.stream_category = "orders::order"
        mock_info.dlq_stream = "orders::order:dlq"
        mock_info.backfill_dlq_stream = "orders::order:backfill:dlq"

        with patch("protean.utils.dlq.discover_subscriptions") as mock_discover:
            mock_discover.return_value = [mock_info]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.post("/api/dlq/replay-all?subscription=orders::order")
            assert response.status_code == 200
            data = response.json()

            assert data["replayed"] == 5  # 3 + 2

    def test_dlq_replay_all_subscription_not_found(self):
        """DLQ replay-all returns 404 when subscription not found."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True

        with patch("protean.utils.dlq.discover_subscriptions") as mock_discover:
            mock_discover.return_value = []

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.post(
                "/api/dlq/replay-all?subscription=nonexistent::stream"
            )
            assert response.status_code == 404
            assert "No subscription" in response.json()["error"]

    def test_dlq_replay_all_no_broker(self):
        """DLQ replay-all returns 503 when broker is unavailable."""
        mock_domain = _make_mock_domain("no-broker")
        mock_domain.brokers.get.return_value = None

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.post("/api/dlq/replay-all?subscription=orders::order")
        assert response.status_code == 503
        assert response.json()["error"] == "DLQ not available"

    def test_dlq_replay_all_no_capability(self):
        """DLQ replay-all returns 503 when broker lacks DLQ capability."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = False

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.post("/api/dlq/replay-all?subscription=orders::order")
        assert response.status_code == 503
        assert response.json()["error"] == "DLQ not available"

    def test_dlq_replay_all_handles_exception(self):
        """DLQ replay-all returns 500 on unexpected exception."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.side_effect = RuntimeError("unexpected")

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.post("/api/dlq/replay-all?subscription=orders::order")
        assert response.status_code == 500
        assert response.json()["error"] == "Failed to replay DLQ messages"


# --- Tests for DLQ purge endpoint ---


class TestDLQPurgeEndpoint:
    """Tests for DELETE /api/dlq."""

    def test_dlq_purge_success(self):
        """DLQ purge removes all messages for a subscription."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True
        mock_broker.dlq_purge.return_value = 7

        mock_info = MagicMock()
        mock_info.stream_category = "orders::order"
        mock_info.dlq_stream = "orders::order:dlq"
        mock_info.backfill_dlq_stream = None

        with patch("protean.utils.dlq.discover_subscriptions") as mock_discover:
            mock_discover.return_value = [mock_info]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.delete("/api/dlq?subscription=orders::order")
            assert response.status_code == 200
            data = response.json()

            assert data["status"] == "ok"
            assert data["purged"] == 7

    def test_dlq_purge_with_backfill(self):
        """DLQ purge includes backfill DLQ streams."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True
        mock_broker.dlq_purge.side_effect = [4, 3]  # primary=4, backfill=3

        mock_info = MagicMock()
        mock_info.stream_category = "orders::order"
        mock_info.dlq_stream = "orders::order:dlq"
        mock_info.backfill_dlq_stream = "orders::order:backfill:dlq"

        with patch("protean.utils.dlq.discover_subscriptions") as mock_discover:
            mock_discover.return_value = [mock_info]

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.delete("/api/dlq?subscription=orders::order")
            assert response.status_code == 200
            data = response.json()

            assert data["purged"] == 7  # 4 + 3

    def test_dlq_purge_subscription_not_found(self):
        """DLQ purge returns 404 when subscription not found."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = True

        with patch("protean.utils.dlq.discover_subscriptions") as mock_discover:
            mock_discover.return_value = []

            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)

            response = client.delete("/api/dlq?subscription=nonexistent::stream")
            assert response.status_code == 404
            assert "No subscription" in response.json()["error"]

    def test_dlq_purge_no_broker(self):
        """DLQ purge returns 503 when broker is unavailable."""
        mock_domain = _make_mock_domain("no-broker")
        mock_domain.brokers.get.return_value = None

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.delete("/api/dlq?subscription=orders::order")
        assert response.status_code == 503
        assert response.json()["error"] == "DLQ not available"

    def test_dlq_purge_no_capability(self):
        """DLQ purge returns 503 when broker lacks DLQ capability."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.return_value = False

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.delete("/api/dlq?subscription=orders::order")
        assert response.status_code == 503
        assert response.json()["error"] == "DLQ not available"

    def test_dlq_purge_handles_exception(self):
        """DLQ purge returns 500 on unexpected exception."""
        mock_domain, mock_broker, _ = _make_mock_domain_with_broker()
        mock_broker.has_capability.side_effect = RuntimeError("unexpected")

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.delete("/api/dlq?subscription=orders::order")
        assert response.status_code == 500
        assert response.json()["error"] == "Failed to purge DLQ"


# --- Mock-based tests for /api/workers endpoint ---


@pytest.mark.no_test_domain
class TestWorkersEndpointMocked:
    """Mock-based tests for /api/workers covering grouping, throughput, and error paths."""

    def test_workers_returns_503_when_no_redis(self):
        """Returns 503 with error when no domain has a redis_instance."""
        mock_domain = _make_mock_domain("no-redis")
        mock_domain.brokers.get.return_value = None

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/workers")
        assert response.status_code == 503
        data = response.json()
        assert data["error"] == "Redis not available"
        assert data["workers"] == []
        assert data["count"] == 0

    def test_workers_returns_empty_list_when_no_consumers(self):
        """Returns empty workers list when streams exist but have no consumers."""
        mock_domain, _, mock_redis = _make_mock_domain_with_broker()
        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xinfo_groups.return_value = []
        mock_redis.xrange.return_value = []

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/workers")
        assert response.status_code == 200
        data = response.json()
        assert data["workers"] == []
        assert data["count"] == 0
        assert "timestamp" in data

    def test_workers_groups_consumers_by_hostname_pid(self):
        """Consumers from the same host-pid are grouped into a single worker."""
        mock_domain, _, mock_redis = _make_mock_domain_with_broker()

        mock_redis.scan.return_value = (
            0,
            [b"orders::order", b"inventory::product"],
        )
        # Two streams, each with one group
        mock_redis.xinfo_groups.side_effect = [
            [{"name": "OrderHandler", "pending": 0, "lag": 0}],
            [{"name": "InventoryHandler", "pending": 0, "lag": 0}],
        ]
        # Both groups have consumers from the same worker (host1-1000)
        # and one consumer from a different worker (host2-2000)
        mock_redis.xinfo_consumers.side_effect = [
            # Consumers for OrderHandler on orders::order
            [
                {"name": "OrderHandler-host1-1000-aaa111", "pending": 2, "idle": 500},
                {"name": "OrderHandler-host2-2000-bbb222", "pending": 1, "idle": 300},
            ],
            # Consumers for InventoryHandler on inventory::product
            [
                {
                    "name": "InventoryHandler-host1-1000-ccc333",
                    "pending": 3,
                    "idle": 400,
                },
            ],
        ]
        mock_redis.xrange.return_value = []  # No trace data

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/workers")
        assert response.status_code == 200
        data = response.json()

        assert data["count"] == 2
        workers_by_id = {w["worker_id"]: w for w in data["workers"]}

        # host1-1000 should have 2 subscriptions (OrderHandler + InventoryHandler)
        w1 = workers_by_id["host1-1000"]
        assert w1["hostname"] == "host1"
        assert w1["pid"] == 1000
        assert w1["subscription_count"] == 2
        assert w1["total_pending"] == 5  # 2 + 3
        assert len(w1["subscriptions"]) == 2

        # host2-2000 should have 1 subscription (OrderHandler only)
        w2 = workers_by_id["host2-2000"]
        assert w2["hostname"] == "host2"
        assert w2["pid"] == 2000
        assert w2["subscription_count"] == 1
        assert w2["total_pending"] == 1

    def test_workers_computes_throughput_from_trace_stream(self):
        """Per-worker throughput counts are computed from trace stream entries."""
        import time as time_mod

        mock_domain, _, mock_redis = _make_mock_domain_with_broker()

        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xinfo_groups.return_value = [
            {"name": "OrderHandler", "pending": 0, "lag": 0}
        ]
        mock_redis.xinfo_consumers.return_value = [
            {"name": "OrderHandler-host1-1000-abc123", "pending": 0, "idle": 100}
        ]

        # Simulate two trace entries within the last 5 minutes
        now_ms = int(time_mod.time() * 1000)
        trace1 = json.dumps(
            {
                "event": "handler.completed",
                "worker_id": "OrderHandler-host1-1000-abc123",
            }
        )
        trace2 = json.dumps(
            {
                "event": "handler.completed",
                "worker_id": "OrderHandler-host1-1000-abc123",
            }
        )
        # A non-matching event that should be skipped
        trace_skip = json.dumps(
            {"event": "handler.started", "worker_id": "OrderHandler-host1-1000-abc123"}
        )

        mock_redis.xrange.return_value = [
            (f"{now_ms - 2000}-0".encode(), {b"data": trace1.encode()}),
            (f"{now_ms - 1500}-0".encode(), {b"data": trace2.encode()}),
            (f"{now_ms - 1000}-0".encode(), {b"data": trace_skip.encode()}),
        ]

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/workers")
        assert response.status_code == 200
        data = response.json()

        assert data["count"] == 1
        worker = data["workers"][0]
        assert worker["worker_id"] == "host1-1000"

        tp = worker["throughput"]
        assert tp["window_seconds"] == 300
        assert tp["bucket_seconds"] == 10
        assert isinstance(tp["counts"], list)
        assert len(tp["counts"]) == 30  # 300s / 10s
        # Only "handler.completed" events should be counted (2, not 3)
        assert tp["total"] == 2
        # Worker should be active because of throughput
        assert worker["status"] == "active"

    def test_workers_handles_trace_stream_exception_gracefully(self):
        """Workers endpoint still returns results when trace stream read fails."""
        mock_domain, _, mock_redis = _make_mock_domain_with_broker()

        mock_redis.scan.return_value = (0, [b"orders::order"])
        mock_redis.xinfo_groups.return_value = [
            {"name": "OrderHandler", "pending": 0, "lag": 0}
        ]
        mock_redis.xinfo_consumers.return_value = [
            {"name": "OrderHandler-host1-1000-abc123", "pending": 0, "idle": 100}
        ]
        # xrange raises an exception (e.g., trace stream does not exist)
        mock_redis.xrange.side_effect = Exception("NOGROUP No such stream")

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/api/workers")
        assert response.status_code == 200
        data = response.json()

        # Worker still appears with zero throughput
        assert data["count"] == 1
        worker = data["workers"][0]
        assert worker["worker_id"] == "host1-1000"
        assert worker["throughput"]["total"] == 0
        assert all(c == 0 for c in worker["throughput"]["counts"])
