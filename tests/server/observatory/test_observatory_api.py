"""Tests for Observatory REST API endpoints.

These tests require a running Redis instance and are gated behind @pytest.mark.redis.
Unit tests for error paths use mock domains and need no infrastructure.
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

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
