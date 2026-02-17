"""Tests for Observatory REST API endpoints.

These tests require a running Redis instance and are gated behind @pytest.mark.redis.
Unit tests for error paths use mock domains and need no infrastructure.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import (
    Observatory,
    _GracefulShutdownMiddleware,
    create_observatory_app,
)
from protean.server.observatory.api import _broker_health, _broker_info, _outbox_status


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
        broker_info = data["infrastructure"]["broker"]
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

    def test_dashboard_fallback_when_html_missing(self, test_domain):
        """Dashboard returns 500 with fallback message when HTML file is missing."""
        # Patch before Observatory is created so the route closure captures the mock
        with patch("protean.server.observatory._DASHBOARD_HTML_PATH") as mock_path:
            mock_path.exists.return_value = False
            observatory = Observatory(domains=[test_domain])
            client = TestClient(observatory.app)
            response = client.get("/")

        assert response.status_code == 500
        assert "Dashboard HTML not found" in response.text


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
