"""Tests for the Engine health check HTTP server."""

import asyncio
import json
import logging
import os
import threading
import time
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.server.health import (
    HealthServer,
    _check_liveness,
    _check_readiness,
    _json_response,
    _parse_request_line,
    _SubscriptionBlockRefresher,
)
from protean.server.subscription.profiles import CircuitBreakerState
from protean.server.subscription_status import SubscriptionStatus
from protean.utils.mixins import handle


async def _readiness(engine, **kwargs):
    """Collect the block once, then run the probe with it.

    Mirrors what HealthServer does (refresh in the background, probe reads
    memory) while keeping tests to a single deterministic collection.
    """
    refresher = _SubscriptionBlockRefresher(engine, **kwargs)
    await refresher._refresh_once()
    return await _check_readiness(engine, refresher.block)


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
    async def test_readiness_ok_with_memory_adapters(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            result = await _readiness(engine)
            assert result["status"] == "ok"
            assert result["checks"]["shutting_down"] is False

    @pytest.mark.no_test_domain
    async def test_readiness_unavailable_when_shutting_down(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            engine.shutting_down = True
            result = await _readiness(engine)
            assert result["status"] == "unavailable"
            assert result["checks"]["shutting_down"] is True

    @pytest.mark.no_test_domain
    async def test_readiness_unavailable_when_draining(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            engine.draining = True
            result = await _readiness(engine)
            assert result["status"] == "unavailable"
            assert result["checks"]["draining"] is True
            # Distinct from the shutting_down payload: a draining pod is
            # finishing in-flight work, not tearing down.
            assert "shutting_down" not in result["checks"]

    @pytest.mark.no_test_domain
    async def test_readiness_ready_when_not_draining(self):
        """Negative: with no drain triggered, readiness reports ready."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            assert engine.draining is False
            result = await _readiness(engine)
            assert result["status"] == "ok"
            assert result["checks"]["draining"] is False

    @pytest.mark.no_test_domain
    async def test_readiness_reports_all_components(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            result = await _readiness(engine)
            checks = result["checks"]
            assert "providers" in checks
            assert "brokers" in checks
            assert "event_store" in checks
            assert "caches" in checks
            assert checks["subscriptions"]["total"] == 0
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
            assert hs.host == "127.0.0.1"
            assert hs.port == 8080
            assert hs.port_auto_increment is False

    @pytest.mark.no_test_domain
    def test_custom_config(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        domain.config["server"]["health"] = {
            "enabled": False,
            "host": "0.0.0.0",
            "port": 9090,
            "port_auto_increment": True,
        }
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            hs = engine._health_server
            assert hs.enabled is False
            assert hs.host == "0.0.0.0"
            assert hs.port == 9090
            assert hs.port_auto_increment is True

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

    def test_readyz_carries_the_subscription_block_over_http(self, health_server):
        """The block survives the real probe path, not just a direct call."""
        engine, hs, loop, port = health_server
        subscription = MagicMock()
        subscription.circuit_state = CircuitBreakerState.CLOSED
        engine._subscriptions["orders-handler"] = subscription

        with patch(
            "protean.server.health.collect_subscription_statuses",
            return_value=[_status("orders-handler", lag=4, status="lagging")],
        ):
            loop.run_until_complete(hs._subscriptions._refresh_once())
            status, body = _parse_http(_fetch_health(loop, port, path="/readyz"))

        assert "200 OK" in status
        subscriptions = body["checks"]["subscriptions"]
        assert subscriptions["total"] == 1
        assert subscriptions["details"][0]["lag"] == 4
        assert subscriptions["details"][0]["status"] == "lagging"
        assert subscriptions["details"][0]["circuit_state"] == "closed"

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

    def test_drainz_flips_draining_and_returns_200(self, health_server):
        """POST /drainz flips engine.draining to True and answers 200."""
        engine, _, loop, port = health_server
        assert engine.draining is False
        status, body = _parse_http(
            _fetch_health(loop, port, method="POST", path="/drainz")
        )
        assert "200 OK" in status
        assert body["status"] == "draining"
        assert engine.draining is True

    def test_drainz_reports_the_pid_it_drained(self, health_server):
        """The response names the process that drained.

        The flag lives on this process's Engine, so a POST drains one worker.
        Under --workers N the caller has to hit every worker's port, and the pid
        is how it tells them apart.
        """
        _, _, loop, port = health_server
        _, body = _parse_http(_fetch_health(loop, port, method="POST", path="/drainz"))
        assert body["pid"] == os.getpid()

    def test_drainz_logs_the_drain_request(self, health_server, caplog):
        """The drain is announced on the operational log with the pid.

        A drain takes a worker out of service, so the record is the audit trail
        for who went quiet and when.
        """
        _, _, loop, port = health_server
        with caplog.at_level(logging.INFO, logger="protean.server.health"):
            _parse_http(_fetch_health(loop, port, method="POST", path="/drainz"))

        records = [r for r in caplog.records if r.message == "engine.drain_requested"]
        assert len(records) == 1
        assert records[0].pid == os.getpid()

    def test_non_draining_request_logs_nothing(self, health_server, caplog):
        """Negative: a request that does not drain emits no drain record."""
        engine, _, loop, port = health_server
        with caplog.at_level(logging.INFO, logger="protean.server.health"):
            _parse_http(_fetch_health(loop, port, path="/readyz"))
            _parse_http(_fetch_health(loop, port, method="POST", path="/readyz"))
            _parse_http(_fetch_health(loop, port, method="GET", path="/drainz"))

        assert engine.draining is False
        assert not [r for r in caplog.records if r.message == "engine.drain_requested"]

    def test_readyz_503_when_draining(self, health_server):
        """After /drainz, readiness reports not-ready with a draining marker."""
        _, _, loop, port = health_server
        _parse_http(_fetch_health(loop, port, method="POST", path="/drainz"))
        status, body = _parse_http(_fetch_health(loop, port, path="/readyz"))
        assert "503 Service Unavailable" in status
        assert body["status"] == "unavailable"
        assert body["checks"]["draining"] is True
        # Distinct from the shutting_down payload.
        assert "shutting_down" not in body["checks"]

    def test_healthz_200_while_draining(self, health_server):
        """Liveness stays green while draining: healthy, just not taking work."""
        engine, _, loop, port = health_server
        _parse_http(_fetch_health(loop, port, method="POST", path="/drainz"))
        # Prove the engine is actually draining before asserting liveness stays
        # green: otherwise a 405 no-op on /drainz would make this pass vacuously.
        assert engine.draining is True
        status, body = _parse_http(_fetch_health(loop, port, path="/healthz"))
        assert "200 OK" in status
        assert body["status"] == "ok"

    def test_livez_200_while_draining(self, health_server):
        engine, _, loop, port = health_server
        _parse_http(_fetch_health(loop, port, method="POST", path="/drainz"))
        assert engine.draining is True
        status, body = _parse_http(_fetch_health(loop, port, path="/livez"))
        assert "200 OK" in status
        assert body["status"] == "ok"

    def test_get_drainz_returns_404(self, health_server):
        """Only POST /drainz drains; a GET to it is an unknown path (404)."""
        engine, _, loop, port = health_server
        status, _ = _parse_http(_fetch_health(loop, port, method="GET", path="/drainz"))
        # GET is not POST-and-/drainz, so it misses the drain branch and the
        # non-GET 405 branch, landing on the unknown-path 404. Draining unchanged.
        assert "404" in status
        assert engine.draining is False

    def test_post_readyz_still_405(self, health_server):
        """A non-/drainz POST still returns 405, not a drain."""
        engine, _, loop, port = health_server
        status, _ = _parse_http(
            _fetch_health(loop, port, method="POST", path="/readyz")
        )
        assert "405" in status
        assert engine.draining is False

    def test_empty_request_handled_gracefully(self, health_server):
        """Connection that sends no data is handled without error."""
        _, _, loop, port = health_server

        async def _send_empty():
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()

        loop.run_until_complete(_send_empty())

    def test_readyz_degraded_when_provider_fails(self, health_server):
        """Readiness returns degraded when a provider is unavailable."""
        engine, _, loop, port = health_server
        for provider in engine.domain.providers.values():
            provider.is_alive = lambda: False
        status, body = _parse_http(_fetch_health(loop, port, path="/readyz"))
        assert "503" in status
        assert body["status"] == "degraded"

    def test_readyz_degraded_when_broker_fails(self, health_server):
        engine, _, loop, port = health_server
        for broker in engine.domain.brokers.values():
            broker.ping = lambda: False
        status, body = _parse_http(_fetch_health(loop, port, path="/readyz"))
        assert "503" in status
        assert body["status"] == "degraded"

    def test_readyz_degraded_when_event_store_fails(self, health_server):
        engine, _, loop, port = health_server

        def _raise(*a, **kw):
            raise ConnectionError("unreachable")

        engine.domain.event_store.store._read_last_message = _raise
        status, body = _parse_http(_fetch_health(loop, port, path="/readyz"))
        assert "503" in status
        assert body["checks"]["event_store"] == "unavailable"

    def test_readyz_degraded_when_cache_fails(self, health_server):
        engine, _, loop, port = health_server

        def _raise():
            raise ConnectionError("cache down")

        for cache in engine.domain.caches.values():
            cache.ping = _raise
        status, body = _parse_http(_fetch_health(loop, port, path="/readyz"))
        assert "503" in status
        assert body["status"] == "degraded"


# ---------------------------------------------------------------------------
# HealthServer edge cases and error paths
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestHealthServerEdgeCases:
    def test_config_fallback_on_broken_config(self):
        """HealthServer falls back to defaults when config.get raises."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        original_config = domain.config
        mock_config = MagicMock()
        mock_config.get.side_effect = AttributeError("broken")
        mock_config.__getitem__ = original_config.__getitem__
        mock_config.__contains__ = original_config.__contains__
        domain.config = mock_config

        with (
            domain.domain_context(),
            patch.object(
                type(domain),
                "has_outbox",
                new_callable=PropertyMock,
                return_value=False,
            ),
        ):
            engine = Engine(domain, test_mode=True)
            hs = engine._health_server
            assert hs.enabled is True
            assert hs.host == "127.0.0.1"
            assert hs.port == 8080
            assert hs.port_auto_increment is False

    def test_start_fails_gracefully_on_port_conflict(self):
        """HealthServer logs a warning and continues if port is in use."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        domain.config["server"]["health"]["port"] = 0
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            hs = engine._health_server

            loop = asyncio.new_event_loop()
            try:
                # Start successfully first
                loop.run_until_complete(hs.start())
                port = hs._server.sockets[0].getsockname()[1]

                # Try to start a second server on the same port
                hs2 = HealthServer(engine)
                hs2.port = port
                loop.run_until_complete(hs2.start())
                # Should not crash — just logs a warning
                assert hs2._server is None
            finally:
                loop.run_until_complete(hs.stop())
                loop.close()

    def test_auto_increment_binds_next_free_port(self):
        """With port_auto_increment, a taken port rolls forward to a free one."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        domain.config["server"]["health"]["port"] = 0
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            hs = engine._health_server  # occupies an ephemeral port

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(hs.start())
                taken = hs.port

                hs2 = HealthServer(engine)
                hs2.port = taken
                hs2.port_auto_increment = True
                loop.run_until_complete(hs2.start())
                try:
                    # Rolled forward to a different, serving port.
                    assert hs2._server is not None
                    assert hs2._server.is_serving()
                    assert hs2.port > taken
                    assert hs2.port == hs2._server.sockets[0].getsockname()[1]
                finally:
                    loop.run_until_complete(hs2.stop())
            finally:
                loop.run_until_complete(hs.stop())
                loop.close()

    def test_out_of_range_port_is_handled_gracefully(self):
        """A port past 0-65535 is caught (ValueError), not propagated."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            hs = engine._health_server
            hs.port = 70000  # invalid; asyncio raises ValueError, not OSError

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(hs.start())  # must not raise
                assert hs._server is None
            finally:
                loop.close()

    def test_auto_increment_gives_up_after_max_attempts(self):
        """Auto-increment stays bounded: it does not scan forever."""
        import protean.server.health as health_module

        domain = Domain(name="Test")
        domain.init(traverse=False)
        domain.config["server"]["health"]["port"] = 0
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            occupied = engine._health_server

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(occupied.start())
                taken = occupied.port

                hs = HealthServer(engine)
                hs.port = taken
                hs.port_auto_increment = True
                # Only allow the single taken port to be attempted, so the
                # scan exhausts and returns without binding.
                with patch.object(health_module, "_MAX_PORT_ATTEMPTS", 1):
                    loop.run_until_complete(hs.start())
                assert hs._server is None
            finally:
                loop.run_until_complete(occupied.stop())
                loop.close()


# ---------------------------------------------------------------------------
# Engine._on_health_server_done callback
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestOnHealthServerDone:
    def test_callback_logs_exception(self, caplog):
        """Done callback logs exceptions from the health task."""
        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = OSError("bind failed")

        import logging

        with caplog.at_level(logging.WARNING, logger="protean.server.engine"):
            Engine._on_health_server_done(task)

        assert any("bind failed" in r.message for r in caplog.records)

    def test_callback_ignores_cancelled_task(self, caplog):
        """Done callback does nothing for cancelled tasks."""
        task = MagicMock()
        task.cancelled.return_value = True

        import logging

        with caplog.at_level(logging.WARNING, logger="protean.server.engine"):
            Engine._on_health_server_done(task)

        assert not any("failed" in r.message for r in caplog.records)

    def test_callback_ignores_successful_task(self, caplog):
        """Done callback does nothing when task succeeds."""
        task = MagicMock()
        task.cancelled.return_value = False
        task.exception.return_value = None

        import logging

        with caplog.at_level(logging.WARNING, logger="protean.server.engine"):
            Engine._on_health_server_done(task)

        assert not any("failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Subscription health block in the readiness response
# ---------------------------------------------------------------------------


class HealthUser(BaseAggregate):
    email: String()


class HealthUserRegistered(BaseEvent):
    user_id: Identifier()
    email: String()


class HealthUserHandler(BaseEventHandler):
    @handle(HealthUserRegistered)
    def on_registered(self, event: HealthUserRegistered):
        pass


def _status(name, **overrides):
    """Build a SubscriptionStatus with sensible defaults for the fields
    the readiness block does not exercise."""
    defaults = {
        "name": name,
        "handler_name": "OrderProjector",
        "subscription_type": "stream",
        "stream_category": "order",
        "lag": 0,
        "pending": 0,
        "current_position": "5",
        "head_position": "5",
        "status": "ok",
        "consumer_count": 1,
        "dlq_depth": 0,
    }
    defaults.update(overrides)
    return SubscriptionStatus(**defaults)


@pytest.mark.no_test_domain
class TestSubscriptionHealthBlock:
    """The readiness probe reports per-subscription lag, status and breaker state."""

    def _domain(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        return domain

    async def test_block_reports_lag_and_status_per_subscription(self):
        """A subscription with known lag surfaces that lag in the block."""
        domain = self._domain()
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            collected = [
                _status("orders-handler", lag=7, pending=2, status="lagging"),
                _status("audit-handler", handler_name="AuditHandler", lag=0),
            ]
            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=collected,
            ):
                result = await _readiness(engine)

            details = result["checks"]["subscriptions"]["details"]
            assert len(details) == 2

            by_name = {d["name"]: d for d in details}
            assert by_name["orders-handler"]["lag"] == 7
            assert by_name["orders-handler"]["pending"] == 2
            assert by_name["orders-handler"]["status"] == "lagging"
            assert by_name["orders-handler"]["handler_name"] == "OrderProjector"
            assert by_name["orders-handler"]["stream_category"] == "order"
            assert by_name["audit-handler"]["lag"] == 0
            assert by_name["audit-handler"]["status"] == "ok"

    async def test_lag_seconds_survives_position_field_strip(self):
        """``lag_seconds`` is health data, so it survives the cursor strip while
        ``last_updated`` (a position field) is dropped."""
        domain = self._domain()
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[
                    _status(
                        "orders-handler",
                        lag=5,
                        lag_seconds=12.5,
                        last_updated="2026-01-01T12:00:00Z",
                        status="lagging",
                    )
                ],
            ):
                result = await _readiness(engine)

            detail = result["checks"]["subscriptions"]["details"][0]
            assert detail["lag_seconds"] == 12.5
            # The position cursor is stripped; the seconds-behind is kept.
            assert "last_updated" not in detail

    async def test_unknown_lag_is_reported_as_null_not_zero(self):
        """An unreachable backend must not be reported as zero lag."""
        domain = self._domain()
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[_status("orders-handler", lag=None, status="unknown")],
            ):
                result = await _readiness(engine)

            detail = result["checks"]["subscriptions"]["details"][0]
            assert detail["lag"] is None
            assert detail["status"] == "unknown"

    async def test_circuit_breaker_state_merged_from_live_subscription(self):
        """Breaker state comes off the engine's live subscription objects."""
        domain = self._domain()
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            subscription = MagicMock()
            subscription.circuit_state = CircuitBreakerState.OPEN
            engine._subscriptions["orders-handler"] = subscription

            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[_status("orders-handler")],
            ):
                result = await _readiness(engine)

            detail = result["checks"]["subscriptions"]["details"][0]
            assert detail["circuit_state"] == "open"

    async def test_circuit_state_absent_when_subscription_has_no_breaker(self):
        """Subscriptions without a breaker are not given a fabricated state."""
        domain = self._domain()
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            # An event-store subscription is live but carries no breaker.
            engine._subscriptions["es-handler"] = MagicMock(circuit_state=None)

            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[_status("es-handler", subscription_type="event_store")],
            ):
                result = await _readiness(engine)

            detail = result["checks"]["subscriptions"]["details"][0]
            assert "circuit_state" not in detail

    async def test_breaker_with_no_matching_status_is_still_reported(self):
        """A ``sequential_by`` process manager is keyed ``{name}-partitioned``
        by the engine but reported per stream category by the status
        collector, so its breaker matches no status entry. It must still
        surface rather than vanish."""
        domain = self._domain()
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            subscription = MagicMock()
            subscription.circuit_state = CircuitBreakerState.OPEN
            engine._subscriptions["OrderProcessManager-partitioned"] = subscription

            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[_status("OrderProcessManager-order")],
            ):
                result = await _readiness(engine)

            details = result["checks"]["subscriptions"]["details"]
            by_name = {d["name"]: d for d in details}

            # The collector's entry is present, carrying lag but no breaker.
            assert "circuit_state" not in by_name["OrderProcessManager-order"]

            # The orphaned breaker is reported rather than silently dropped.
            orphan = by_name["OrderProcessManager-partitioned"]
            assert orphan["circuit_state"] == "open"
            assert orphan["status"] == "unknown"
            # Nothing is known about this key, so every count is null. A 0 here
            # would read as "no backlog" rather than "no data".
            assert orphan["lag"] is None
            assert orphan["lag_seconds"] is None
            assert orphan["pending"] is None
            assert orphan["dlq_depth"] is None

    async def test_lagging_subscription_does_not_make_engine_unready(self):
        """Lag is informational: it must never pull the pod out of service."""
        domain = self._domain()
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[_status("orders-handler", lag=9999, status="lagging")],
            ):
                result = await _readiness(engine)

            # The lag was seen and reported...
            assert result["checks"]["subscriptions"]["details"][0]["lag"] == 9999
            assert (
                result["checks"]["subscriptions"]["details"][0]["status"] == "lagging"
            )
            # ...and deliberately not allowed to change the verdict.
            assert result["status"] == "ok"

    async def test_open_circuit_breaker_does_not_make_engine_unready(self):
        """An open breaker pauses one handler; the engine is still ready."""
        domain = self._domain()
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            subscription = MagicMock()
            subscription.circuit_state = CircuitBreakerState.OPEN
            engine._subscriptions["orders-handler"] = subscription

            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[_status("orders-handler")],
            ):
                result = await _readiness(engine)

            # The open breaker was seen and reported...
            detail = result["checks"]["subscriptions"]["details"][0]
            assert detail["circuit_state"] == "open"
            # ...and deliberately not allowed to change the verdict.
            assert result["status"] == "ok"

    async def test_collection_failure_degrades_gracefully(self):
        """A monitoring read that blows up must not break the probe."""
        domain = self._domain()
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            with patch(
                "protean.server.health.collect_subscription_statuses",
                side_effect=RuntimeError("redis is down"),
            ):
                result = await _readiness(engine)

            block = result["checks"]["subscriptions"]
            assert result["status"] == "ok"
            assert block["collection_error"] is True
            assert block["details"] == []

    async def test_total_counts_every_subscription_kind(self):
        """``total`` spans stream/event-store, broker, and outbox processors."""
        domain = self._domain()
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            engine._subscriptions["a"] = MagicMock(circuit_state=None)
            engine._broker_subscriptions["b"] = MagicMock()
            engine._outbox_processors["c"] = MagicMock()

            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[],
            ):
                result = await _readiness(engine)

            assert result["checks"]["subscriptions"]["total"] == 3

    async def test_block_is_json_serialisable(self):
        """The probe writes JSON, so every value in the block must encode."""
        domain = self._domain()
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            subscription = MagicMock()
            subscription.circuit_state = CircuitBreakerState.HALF_OPEN
            engine._subscriptions["orders-handler"] = subscription

            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[_status("orders-handler", lag=3, status="lagging")],
            ):
                result = await _readiness(engine)

            encoded = json.loads(json.dumps(result))
            assert (
                encoded["checks"]["subscriptions"]["details"][0]["circuit_state"]
                == "half_open"
            )


@pytest.mark.no_test_domain
class TestSubscriptionHealthAgainstRealDomain:
    """Exercise the real collector through the worker thread, unpatched.

    The rest of the block's tests patch ``collect_subscription_statuses`` to pin
    lag values.  This one does not: it proves the collection runs to completion
    in the worker thread against a live domain, producing a real, serialisable
    row.  The collector enters its own ``domain_context()`` inside that worker,
    which is the part most likely to break silently, since the context is
    established on the event loop here in the test body.
    """

    async def test_real_handler_appears_in_the_block(self):
        domain = Domain(name="Test")
        domain.register(HealthUser)
        domain.register(HealthUserRegistered, part_of=HealthUser)
        domain.register(HealthUserHandler, part_of=HealthUser)
        domain.init(traverse=False)

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            result = await _readiness(engine)

            block = result["checks"]["subscriptions"]
            assert "collection_error" not in block
            assert block["total"] >= 1

            names = [d["handler_name"] for d in block["details"]]
            assert "HealthUserHandler" in names

            detail = next(
                d for d in block["details"] if d["handler_name"] == "HealthUserHandler"
            )
            assert detail["stream_category"].endswith("health_user")
            assert detail["status"] in {"ok", "lagging", "unknown"}
            # Serialisable straight out of the real collector.
            json.dumps(result)


@pytest.mark.no_test_domain
class TestSubscriptionBlockRefresher:
    """The probe reads memory; a background task does the collecting."""

    def _blocking_collector(self, release):
        """A collector that hangs until *release* is set, like a stalled Redis."""

        def _collect(_domain):
            release.wait(timeout=10)
            return [_status("orders-handler", lag=1, status="lagging")]

        return _collect

    async def test_block_is_empty_until_the_first_refresh_lands(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            engine._subscriptions["a"] = MagicMock(circuit_state=None)
            refresher = _SubscriptionBlockRefresher(engine)

            block = refresher.block
            assert block["collection_pending"] is True
            assert block["details"] == []
            # The count is still honest before anything has been collected.
            assert block["total"] == 1

    async def test_probing_never_collects(self):
        """The whole point: a probe must not touch infrastructure."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = _SubscriptionBlockRefresher(engine)
            await refresher._refresh_once()

            with patch(
                "protean.server.health.collect_subscription_statuses"
            ) as collect:
                for _ in range(10):
                    await _check_readiness(engine, refresher.block)

            assert collect.call_count == 0

    async def test_a_hung_collection_cannot_delay_a_probe(self):
        """A stalled backend must not cost the pod its place in the LB."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        release = threading.Event()
        try:
            with domain.domain_context():
                engine = Engine(domain, test_mode=True)
                refresher = _SubscriptionBlockRefresher(engine, interval=0.01)

                with patch(
                    "protean.server.health.collect_subscription_statuses",
                    side_effect=self._blocking_collector(release),
                ):
                    await refresher.start()
                    await asyncio.sleep(0.05)  # let the refresh wedge

                    started = time.monotonic()
                    result = await _check_readiness(engine, refresher.block)
                    elapsed = time.monotonic() - started

                    await refresher.stop()

                assert elapsed < 0.5
                assert result["status"] == "ok"
                assert result["checks"]["subscriptions"]["collection_pending"] is True
        finally:
            release.set()

    async def test_a_failed_refresh_keeps_the_previous_block(self):
        """An error the block builder cannot absorb must not wipe good data."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = _SubscriptionBlockRefresher(engine)

            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[_status("orders-handler", lag=3, status="lagging")],
            ):
                await refresher._refresh_once()

            with patch(
                "protean.server.health._snapshot_and_collect",
                side_effect=RuntimeError("collection blew up"),
            ):
                await refresher._refresh_once()

            # The good data survives rather than being replaced by nothing.
            assert refresher.block["details"][0]["lag"] == 3

    async def test_a_collector_error_is_reported_not_hidden(self):
        """A backend that errors is surfaced, not papered over with old data."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = _SubscriptionBlockRefresher(engine)

            with patch(
                "protean.server.health.collect_subscription_statuses",
                side_effect=RuntimeError("redis is down"),
            ):
                await refresher._refresh_once()

            assert refresher.block["collection_error"] is True
            assert refresher.block["details"] == []

    async def test_block_reports_its_age_once_refreshes_stop_landing(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        clock = [1000.0]
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = _SubscriptionBlockRefresher(
                engine, interval=2.0, clock=lambda: clock[0]
            )

            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[_status("orders-handler")],
            ):
                await refresher._refresh_once()

            # Within a few intervals, still considered current.
            clock[0] += 5.0
            assert "stale" not in refresher.block

            # Well past them, and the age is reported rather than implied.
            clock[0] += 40.0
            stale = refresher.block
            assert stale["stale"] is True
            assert stale["age_seconds"] == 45.0

    async def test_the_loop_keeps_refreshing(self):
        """The background loop must iterate, not collect once and stop.

        Waits on the collector's own call count rather than on elapsed time, so
        the test is deterministic under load instead of racing a sleep.
        """
        domain = Domain(name="Test")
        domain.init(traverse=False)
        calls = []

        def _collect(_domain):
            calls.append(1)
            return []

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = _SubscriptionBlockRefresher(engine, interval=0.01)

            with patch(
                "protean.server.health.collect_subscription_statuses",
                side_effect=_collect,
            ):
                await refresher.start()
                try:
                    for _ in range(500):
                        if len(calls) >= 2:
                            break
                        await asyncio.sleep(0.01)
                finally:
                    await refresher.stop()

            assert len(calls) >= 2, (
                f"refresher ran {len(calls)} collection(s); the loop is not repeating"
            )
            # A completed refresh is adopted, so the block is real by now.
            assert "collection_pending" not in refresher.block

    async def test_start_is_idempotent_and_stop_cancels(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = _SubscriptionBlockRefresher(engine, interval=0.01)

            await refresher.start()
            task = refresher._task
            await refresher.start()
            assert refresher._task is task

            # Let the loop actually run before cancelling it, otherwise
            # whether the loop body executed at all is a race.
            for _ in range(500):
                if refresher._block is not None:
                    break
                await asyncio.sleep(0.01)
            assert refresher._block is not None

            await refresher.stop()
            assert task.cancelled() or task.done()
            # Stopping twice must not raise.
            await refresher.stop()

    async def test_refresh_runs_off_the_event_loop(self):
        """The blocking read must not execute on the loop thread."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        seen = {}

        def _collect(_domain):
            seen["thread"] = threading.current_thread()
            return []

        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = _SubscriptionBlockRefresher(engine)
            with patch(
                "protean.server.health.collect_subscription_statuses",
                side_effect=_collect,
            ):
                await refresher._refresh_once()

        assert seen["thread"] is not threading.current_thread()

    async def test_a_broken_engine_does_not_break_the_block(self):
        """Even the cheap in-memory reads are guarded: the probe answers."""
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            # Something the engine should never be, but if it ever is, the
            # readiness probe is not where we want to find out.
            engine._subscriptions = None

            refresher = _SubscriptionBlockRefresher(engine)
            assert refresher.block["total"] == 0

            await refresher._refresh_once()
            assert refresher.block["collection_error"] is True

    async def test_unreadable_breaker_state_does_not_break_the_block(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = _SubscriptionBlockRefresher(engine)

            with patch(
                "protean.server.health._circuit_states",
                side_effect=RuntimeError("subscription registry is a mess"),
            ):
                await refresher._refresh_once()

            block = refresher.block
            assert block["collection_error"] is True
            assert block["details"] == []

    def test_rejects_a_nonsensical_interval(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            with pytest.raises(ValueError, match="interval"):
                _SubscriptionBlockRefresher(engine, interval=0)


@pytest.mark.no_test_domain
class TestLagDrainRate:
    """Per-subscription lag-drain rate rides on the readiness block.

    The rate is the change in ``lag_seconds`` per second, computed by the
    refresher because it is the only place that holds a window.  Negative means
    draining; positive means falling behind; ``null`` until two windows land.
    """

    def _domain(self):
        domain = Domain(name="Test")
        domain.init(traverse=False)
        return domain

    def _refresher(self, engine, clock):
        # Injected clock so the sample times are exact and the slope is a known
        # number, not something that depends on wall-clock jitter.
        return _SubscriptionBlockRefresher(engine, interval=2.0, clock=lambda: clock[0])

    def _series_collector(self, name, lag_seconds_series):
        """A collector that returns *name* with the next ``lag_seconds`` value."""
        values = iter(lag_seconds_series)

        def _collect(_domain):
            return [_status(name, lag=5, lag_seconds=next(values), status="lagging")]

        return _collect

    async def test_draining_lag_yields_a_negative_rate(self):
        """AC1: lag falling across windows gives a negative rate."""
        domain = self._domain()
        clock = [1000.0]
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = self._refresher(engine, clock)

            with patch(
                "protean.server.health.collect_subscription_statuses",
                side_effect=self._series_collector(
                    "orders-handler", [20.0, 16.0, 12.0]
                ),
            ):
                # One sample: a rate is meaningless, so it stays null.
                await refresher._refresh_once()
                assert refresher.block["details"][0]["lag_drain_rate"] is None

                # Two samples 2s apart, 20 → 16: slope is -2.0 lag-seconds/second.
                clock[0] += 2.0
                await refresher._refresh_once()
                assert refresher.block["details"][0]["lag_drain_rate"] == pytest.approx(
                    -2.0
                )

                # A third on the same line holds the slope at -2.0.
                clock[0] += 2.0
                await refresher._refresh_once()
                assert refresher.block["details"][0]["lag_drain_rate"] == pytest.approx(
                    -2.0
                )

    async def test_steady_caught_up_lag_yields_a_zero_rate(self):
        """AC2 (negative test): a caught-up subscription reports 0, never a
        spurious non-zero drift."""
        domain = self._domain()
        clock = [1000.0]
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = self._refresher(engine, clock)

            with patch(
                "protean.server.health.collect_subscription_statuses",
                side_effect=self._series_collector(
                    "orders-handler", [0.0, 0.0, 0.0, 0.0]
                ),
            ):
                rates = []
                for _ in range(4):
                    await refresher._refresh_once()
                    rates.append(refresher.block["details"][0]["lag_drain_rate"])
                    clock[0] += 2.0

            # First is null (one sample); the rest are exactly zero, never a
            # fabricated non-zero rate.
            assert rates[0] is None
            for rate in rates[1:]:
                assert rate == pytest.approx(0.0, abs=1e-9)

    async def test_rising_backlog_yields_a_positive_rate(self):
        """Lag climbing across windows gives a positive rate."""
        domain = self._domain()
        clock = [1000.0]
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = self._refresher(engine, clock)

            with patch(
                "protean.server.health.collect_subscription_statuses",
                side_effect=self._series_collector("orders-handler", [4.0, 8.0, 12.0]),
            ):
                await refresher._refresh_once()
                clock[0] += 2.0
                await refresher._refresh_once()
                clock[0] += 2.0
                await refresher._refresh_once()

            # 4 → 8 → 12 over 2s steps: +2.0 lag-seconds/second.
            assert refresher.block["details"][0]["lag_drain_rate"] == pytest.approx(2.0)

    async def test_state_is_bounded_by_the_sample_window(self):
        """AC3: state cannot grow with runtime; the window is a bounded deque."""
        domain = self._domain()
        clock = [1000.0]
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = self._refresher(engine, clock)

            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[
                    _status("orders-handler", lag=5, lag_seconds=9.0, status="lagging")
                ],
            ):
                # Far more refreshes than the window can hold.
                for _ in range(100):
                    await refresher._refresh_once()
                    clock[0] += 2.0

            window = refresher._samples["orders-handler"]
            assert window.maxlen == 30
            assert len(window) == 30

    async def test_unknown_lag_stays_null_and_records_no_sample(self):
        """A row whose ``lag_seconds`` is unknown gets a null rate and no
        sample: a 0 sample would later read as a real drained rate."""
        domain = self._domain()
        clock = [1000.0]
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = self._refresher(engine, clock)

            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[
                    _status(
                        "orders-handler",
                        lag=None,
                        lag_seconds=None,
                        status="unknown",
                    )
                ],
            ):
                await refresher._refresh_once()
                clock[0] += 2.0
                await refresher._refresh_once()

            assert refresher.block["details"][0]["lag_drain_rate"] is None
            # No sample was recorded, so the name never enters the window map.
            assert "orders-handler" not in refresher._samples

    async def test_zero_time_variance_yields_null_not_a_crash(self):
        """Two samples at the same instant must return null, not divide by zero."""
        domain = self._domain()
        clock = [1000.0]  # never advanced: a fixed clock
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = self._refresher(engine, clock)

            with patch(
                "protean.server.health.collect_subscription_statuses",
                side_effect=self._series_collector("orders-handler", [20.0, 16.0]),
            ):
                await refresher._refresh_once()
                await refresher._refresh_once()

            # Two samples share one instant, so the slope is undefined, not 0.
            assert refresher.block["details"][0]["lag_drain_rate"] is None

    async def test_a_dropped_subscription_is_pruned_from_the_window(self):
        """A subscription that vanishes from the collector output no longer
        holds a window, so the key set cannot grow with churn."""
        domain = self._domain()
        clock = [1000.0]
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = self._refresher(engine, clock)

            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[
                    _status("orders-handler", lag=5, lag_seconds=9.0, status="lagging"),
                    _status("audit-handler", lag=1, lag_seconds=3.0, status="lagging"),
                ],
            ):
                await refresher._refresh_once()
            assert "audit-handler" in refresher._samples

            clock[0] += 2.0
            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[
                    _status("orders-handler", lag=5, lag_seconds=7.0, status="lagging")
                ],
            ):
                await refresher._refresh_once()

            assert "orders-handler" in refresher._samples
            assert "audit-handler" not in refresher._samples

    async def test_a_non_dict_row_is_skipped_instead_of_crashing(self):
        """Annotation runs outside the collector's guard, so a row that is not
        a writable dict must be skipped, not raise and end the refresher."""
        domain = self._domain()
        clock = [1000.0]
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            refresher = self._refresher(engine, clock)

            block = {
                "total": 2,
                "details": [
                    "not-a-row",
                    MappingProxyType({"name": "frozen", "lag_seconds": 4.0}),
                    {"name": "orders-handler", "lag_seconds": 9.0},
                ],
            }
            refresher._annotate_lag_drain_rates(block)

            assert block["details"][0] == "not-a-row"
            assert "lag_drain_rate" not in block["details"][1]
            # The good row is still annotated, and only it holds a window.
            assert block["details"][2]["lag_drain_rate"] is None
            assert set(refresher._samples) == {"orders-handler"}

    async def test_rate_field_is_present_on_the_readiness_block(self):
        """The field rides on the real readiness output, null after one window."""
        domain = self._domain()
        with domain.domain_context():
            engine = Engine(domain, test_mode=True)
            with patch(
                "protean.server.health.collect_subscription_statuses",
                return_value=[
                    _status("orders-handler", lag=5, lag_seconds=9.0, status="lagging")
                ],
            ):
                result = await _readiness(engine)

            detail = result["checks"]["subscriptions"]["details"][0]
            assert "lag_drain_rate" in detail
            assert detail["lag_drain_rate"] is None

    async def test_rate_is_not_a_subscription_status_field(self):
        """AC4: the rate is a health-block annotation, not a SubscriptionStatus
        field (and not an OTEL gauge): it never leaks into the shared status
        surface the CLI and Observatory read."""
        assert "lag_drain_rate" not in _status("orders-handler").to_dict()


# ---------------------------------------------------------------------------
# Connection error handling in _handle_connection
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestHandleConnectionErrors:
    def _make_mock_writer(self, **overrides):
        """Create a mock StreamWriter with async methods."""
        writer = MagicMock()
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()
        for k, v in overrides.items():
            setattr(writer, k, v)
        return writer

    def test_timeout_on_read_is_handled(self, health_server):
        """asyncio.TimeoutError during read is silently handled."""
        _, hs, loop, _ = health_server

        async def _test():
            mock_reader = MagicMock()
            mock_reader.read = AsyncMock(side_effect=asyncio.TimeoutError)
            await hs._handle_connection(mock_reader, self._make_mock_writer())

        loop.run_until_complete(_test())

    def test_connection_reset_is_handled(self, health_server):
        """ConnectionResetError during read is silently handled."""
        _, hs, loop, _ = health_server

        async def _test():
            mock_reader = MagicMock()
            mock_reader.read = AsyncMock(side_effect=ConnectionResetError)
            await hs._handle_connection(mock_reader, self._make_mock_writer())

        loop.run_until_complete(_test())

    def test_writer_close_exception_is_suppressed(self, health_server):
        """Exception during writer.close() in finally block is suppressed."""
        _, hs, loop, _ = health_server

        async def _test():
            mock_reader = MagicMock()
            mock_reader.read = AsyncMock(return_value=b"GET /healthz HTTP/1.1\r\n\r\n")
            writer = self._make_mock_writer(
                close=MagicMock(side_effect=OSError("already closed")),
            )
            await hs._handle_connection(mock_reader, writer)

        loop.run_until_complete(_test())

    def test_generic_exception_is_logged(self, health_server, caplog):
        """Non-network exceptions are logged at debug level."""
        _, hs, loop, _ = health_server

        import logging

        async def _test():
            mock_reader = MagicMock()
            mock_reader.read = AsyncMock(side_effect=ValueError("unexpected"))
            await hs._handle_connection(mock_reader, self._make_mock_writer())

        with caplog.at_level(logging.DEBUG, logger="protean.server.health"):
            loop.run_until_complete(_test())

        assert any(
            "Health server connection error" in r.message for r in caplog.records
        )

    def test_generic_exception_still_answers_with_503(self, health_server):
        """An empty reply is indistinguishable from a dead process, so the
        handler must answer even when response assembly blows up."""
        _, hs, loop, _ = health_server
        writer = self._make_mock_writer()

        async def _test():
            mock_reader = MagicMock()
            mock_reader.read = AsyncMock(side_effect=ValueError("unexpected"))
            await hs._handle_connection(mock_reader, writer)

        loop.run_until_complete(_test())

        written = b"".join(call.args[0] for call in writer.write.call_args_list)
        assert written, "handler closed the socket without writing a response"
        assert b"503 Service Unavailable" in written
        # `degraded`, not `unavailable`: the latter is the shutdown signal, and
        # a client must not read a handler bug as "this pod is draining".
        assert b'"degraded"' in written
        assert b'"unavailable"' not in written
