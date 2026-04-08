"""Tests for the Engine health check HTTP server."""

import asyncio
import json

import pytest

from protean.domain import Domain
from protean.server.engine import Engine
from protean.server.health import (
    _check_liveness,
    _check_readiness,
    _json_response,
    _parse_request_line,
)


# ---------------------------------------------------------------------------
# Unit tests: HTTP helpers
# ---------------------------------------------------------------------------


class TestParseRequestLine:
    def test_parse_get_request(self):
        data = b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n\r\n"
        method, path = _parse_request_line(data)
        assert method == "GET"
        assert path == "/healthz"

    def test_parse_post_request(self):
        data = b"POST /readyz HTTP/1.1\r\n\r\n"
        method, path = _parse_request_line(data)
        assert method == "POST"
        assert path == "/readyz"

    def test_empty_data(self):
        method, path = _parse_request_line(b"")
        assert method == ""
        assert path == ""


class TestJsonResponse:
    def test_200_response(self):
        resp = _json_response(200, {"status": "ok"})
        assert b"HTTP/1.1 200 OK" in resp
        assert b"Content-Type: application/json" in resp
        assert b'{"status": "ok"}' in resp

    def test_503_response(self):
        resp = _json_response(503, {"status": "degraded"})
        assert b"HTTP/1.1 503 Service Unavailable" in resp
        assert b'{"status": "degraded"}' in resp


# ---------------------------------------------------------------------------
# Unit tests: health check logic
# ---------------------------------------------------------------------------


class TestCheckLiveness:
    @pytest.mark.no_test_domain
    def test_liveness_returns_ok(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            result = _check_liveness(engine)
            assert result["status"] == "ok"
            assert result["checks"]["event_loop"] == "responsive"


class TestCheckReadiness:
    @pytest.mark.no_test_domain
    def test_readiness_ok_with_memory_adapters(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            result = _check_readiness(engine)
            assert result["status"] == "ok"
            assert result["checks"]["shutting_down"] is False

    @pytest.mark.no_test_domain
    def test_readiness_unavailable_when_shutting_down(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            engine.shutting_down = True
            result = _check_readiness(engine)
            assert result["status"] == "unavailable"
            assert result["checks"]["shutting_down"] is True

    @pytest.mark.no_test_domain
    def test_readiness_reports_all_components(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            result = _check_readiness(engine)
            checks = result["checks"]
            assert "providers" in checks
            assert "brokers" in checks
            assert "event_store" in checks
            assert "caches" in checks
            assert checks["subscriptions"] == 0
            # Memory adapters are always alive
            for provider_status in checks["providers"].values():
                assert provider_status == "ok"
            assert checks["event_store"] == "ok"


# ---------------------------------------------------------------------------
# HealthServer configuration
# ---------------------------------------------------------------------------


class TestHealthServerConfig:
    @pytest.mark.no_test_domain
    def test_default_config(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            hs = engine._health_server
            assert hs.enabled is True
            assert hs.host == "0.0.0.0"
            assert hs.port == 8080

    @pytest.mark.no_test_domain
    def test_custom_config(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        domain.config["server"]["health"] = {
            "enabled": False,
            "host": "127.0.0.1",
            "port": 9090,
        }
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            hs = engine._health_server
            assert hs.enabled is False
            assert hs.host == "127.0.0.1"
            assert hs.port == 9090

    @pytest.mark.no_test_domain
    def test_disabled_server_does_not_start(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        domain.config["server"]["health"]["enabled"] = False
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            hs = engine._health_server
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(hs.start())
                assert hs._server is None
            finally:
                loop.close()


# ---------------------------------------------------------------------------
# HealthServer integration: start/stop and HTTP requests
# ---------------------------------------------------------------------------


def _fetch_health(
    loop, port: int, method: str = "GET", path: str = "/healthz"
) -> bytes:
    """Send an HTTP request to the health server and return the raw response."""

    async def _do_fetch():
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"{method} {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
        await writer.drain()
        data = await reader.read(4096)
        writer.close()
        await writer.wait_closed()
        return data

    return loop.run_until_complete(_do_fetch())


def _parse_http(response: bytes) -> tuple[str, dict]:
    """Split raw HTTP response into status line and parsed JSON body."""
    header_part, _, body = response.partition(b"\r\n\r\n")
    status_line = header_part.split(b"\r\n", 1)[0].decode()
    return status_line, json.loads(body)


@pytest.fixture
def health_server():
    """Yield a running HealthServer with its event loop and port.

    Automatically starts and stops the server around each test.
    """
    domain = Domain(name="Test")
    domain.init(traverse=False)
    domain.config["server"]["health"]["port"] = 0
    ctx = domain.domain_context()
    ctx.__enter__()
    engine = Engine(domain, test_mode=True)
    hs = engine._health_server
    loop = asyncio.new_event_loop()
    loop.run_until_complete(hs.start())
    port = hs._server.sockets[0].getsockname()[1]

    yield engine, hs, loop, port

    loop.run_until_complete(hs.stop())
    loop.close()
    ctx.__exit__(None, None, None)


@pytest.mark.no_test_domain
class TestHealthServerIntegration:
    def test_start_and_stop(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        domain.config["server"]["health"]["port"] = 0
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            hs = engine._health_server

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(hs.start())
                assert hs._server is not None
                assert hs._server.is_serving()
                loop.run_until_complete(hs.stop())
                assert hs._server is None
            finally:
                loop.close()

    def test_healthz_returns_200_ok(self, health_server):
        _, _, loop, port = health_server
        status, body = _parse_http(_fetch_health(loop, port, path="/healthz"))
        assert "200 OK" in status
        assert body["status"] == "ok"

    def test_readyz_returns_200_with_checks(self, health_server):
        _, _, loop, port = health_server
        status, body = _parse_http(_fetch_health(loop, port, path="/readyz"))
        assert "200 OK" in status
        assert body["status"] == "ok"
        assert "providers" in body["checks"]
        assert "brokers" in body["checks"]
        assert "event_store" in body["checks"]
        assert "caches" in body["checks"]

    def test_livez_alias(self, health_server):
        _, _, loop, port = health_server
        status, body = _parse_http(_fetch_health(loop, port, path="/livez"))
        assert "200 OK" in status
        assert body["status"] == "ok"

    def test_readyz_503_when_shutting_down(self, health_server):
        engine, _, loop, port = health_server
        engine.shutting_down = True
        status, body = _parse_http(_fetch_health(loop, port, path="/readyz"))
        assert "503 Service Unavailable" in status
        assert body["status"] == "unavailable"

    def test_unknown_path_returns_404(self, health_server):
        _, _, loop, port = health_server
        status, _ = _parse_http(_fetch_health(loop, port, path="/unknown"))
        assert "404" in status

    def test_post_returns_405(self, health_server):
        _, _, loop, port = health_server
        status, _ = _parse_http(
            _fetch_health(loop, port, method="POST", path="/healthz")
        )
        assert "405" in status
