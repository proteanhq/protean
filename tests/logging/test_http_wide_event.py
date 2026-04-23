"""Tests for the FastAPI HTTP-layer wide event middleware.

Verifies that ``DomainContextMiddleware`` emits one wide event per HTTP
request on the ``protean.access.http`` logger with the full request
envelope, correlation metadata, and commands dispatched during the
request — the HTTP-layer counterpart to the ``protean.access`` wide
events produced by ``access_log_handler``.
"""

from __future__ import annotations

import logging
from typing import Iterable
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.integrations.fastapi import DomainContextMiddleware
from protean.utils.globals import current_domain
from protean.utils.logging import bind_event_context, unbind_event_context
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Domain elements
# ---------------------------------------------------------------------------


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    customer_name = String(required=True)


class PlaceOrder(BaseCommand):
    order_id = Identifier(identifier=True)
    customer_name = String(required=True)


class ShipOrder(BaseCommand):
    order_id = Identifier(identifier=True)


class OrderCommandHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> None:
        current_domain.repository_for(Order).add(
            Order(order_id=command.order_id, customer_name=command.customer_name)
        )

    @handle(ShipOrder)
    def ship(self, command: ShipOrder) -> None:
        # Intentionally minimal — we only care that two commands dispatched
        # during a request get tracked.
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order, fact_events=True)
    test_domain.register(PlaceOrder, part_of=Order)
    test_domain.register(ShipOrder, part_of=Order)
    test_domain.register(OrderCommandHandler, part_of=Order)
    test_domain.init(traverse=False)


def _make_app(
    domain,
    *,
    exclude_paths: Iterable[str] | None = None,
    emit: bool | None = None,
) -> FastAPI:
    """Build a FastAPI app wired with DomainContextMiddleware."""
    app = FastAPI()
    app.add_middleware(
        DomainContextMiddleware,
        route_domain_map={"/orders": domain, "/healthz": domain},
        exclude_paths=exclude_paths,
        emit_http_wide_event=emit,
    )

    @app.post("/orders")
    def create_order():
        order_id = str(uuid4())
        current_domain.process(
            PlaceOrder(order_id=order_id, customer_name="Alice"),
            asynchronous=False,
        )
        return {"order_id": order_id}

    @app.post("/orders/two-commands")
    def two_commands():
        order_id = str(uuid4())
        current_domain.process(
            PlaceOrder(order_id=order_id, customer_name="Bob"),
            asynchronous=False,
        )
        current_domain.process(
            ShipOrder(order_id=order_id),
            asynchronous=False,
        )
        return {"order_id": order_id}

    @app.get("/orders/boom")
    def boom():
        raise RuntimeError("deliberate failure")

    @app.get("/orders/teapot")
    def teapot():
        raise HTTPException(status_code=418, detail="I'm a teapot")

    @app.get("/orders/bind")
    def bind_endpoint():
        bind_event_context(user_id="u-123", tier="gold")
        return {"ok": True}

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    return app


@pytest.fixture
def app(test_domain) -> FastAPI:
    return _make_app(test_domain)


@pytest.fixture
def client(app) -> TestClient:
    # Default TestClient raises server errors; we want the 500 response so
    # the wide event's status_code can be asserted end-to-end.
    return TestClient(app, raise_server_exceptions=False)


def _http_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "protean.access.http"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHttpWideEventEmission:
    def test_http_request_emits_wide_event(self, client, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.post("/orders")
        assert response.status_code == 200

        records = _http_records(caplog)
        assert len(records) == 1
        record = records[0]
        assert record.getMessage() == "access.http_completed"
        assert record.levelno == logging.INFO
        assert record.http_method == "POST"
        assert record.http_path == "/orders"
        assert record.http_status == 200
        assert record.http_duration_ms > 0
        assert record.route_pattern == "/orders"
        assert record.route_name == "create_order"

    def test_http_5xx_emits_at_error_level(self, client, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get("/orders/boom")
        assert response.status_code == 500

        records = _http_records(caplog)
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.ERROR
        assert record.getMessage() == "access.http_failed"
        assert record.http_status == 500
        assert record.error_type == "RuntimeError"
        assert record.error_message == "deliberate failure"
        assert record.exc_info is not None

    def test_http_4xx_emits_at_warning_level(self, client, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get("/orders/teapot")
        assert response.status_code == 418

        records = _http_records(caplog)
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.WARNING
        assert record.http_status == 418
        assert record.getMessage() == "access.http_completed"


class TestRequestIdPropagation:
    def test_request_id_header_propagated(self, client, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.post(
                "/orders",
                headers={"X-Request-ID": "test-123"},
            )
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "test-123"

        records = _http_records(caplog)
        assert len(records) == 1
        assert records[0].request_id == "test-123"

    def test_request_id_auto_generated(self, client, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.post("/orders")
        assert response.status_code == 200

        auto_id = response.headers["X-Request-ID"]
        # uuid4().hex is 32 characters
        assert len(auto_id) == 32

        records = _http_records(caplog)
        assert len(records) == 1
        assert records[0].request_id == auto_id

    def test_request_id_echoed_on_unmapped_route(self, test_domain, caplog):
        """Even unmapped routes get an X-Request-ID in the response."""
        app = FastAPI()
        app.add_middleware(
            DomainContextMiddleware,
            route_domain_map={"/orders": test_domain},
        )

        @app.get("/unmapped")
        def unmapped():
            return {"ok": True}

        client = TestClient(app)
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get("/unmapped", headers={"X-Request-ID": "u-42"})

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "u-42"

        records = _http_records(caplog)
        assert len(records) == 1
        assert records[0].request_id == "u-42"
        assert records[0].http_path == "/unmapped"


class TestCorrelationAcrossLayers:
    def test_correlation_links_http_and_domain(self, client, caplog):
        """HTTP and domain wide events share the same correlation_id."""
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            response = client.post(
                "/orders",
                headers={"X-Correlation-ID": "corr-xyz"},
            )
        assert response.status_code == 200

        http_records = _http_records(caplog)
        domain_records = [r for r in caplog.records if r.name == "protean.access"]
        assert len(http_records) == 1
        assert len(domain_records) >= 1

        assert http_records[0].correlation_id == "corr-xyz"
        assert domain_records[0].correlation_id == "corr-xyz"


class TestBindEventContextInEndpoint:
    def test_bind_event_context_in_endpoint(self, client, caplog):
        """Fields bound in the endpoint handler surface on the HTTP wide event."""
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get("/orders/bind")
        assert response.status_code == 200

        records = _http_records(caplog)
        assert len(records) == 1
        record = records[0]
        assert record.http_path == "/orders/bind"
        # bind_event_context fields ride through structlog contextvars
        # and are attached to the stdlib LogRecord via ``extra=``.
        assert record.user_id == "u-123"
        assert record.tier == "gold"

    def test_bind_event_context_cannot_overwrite_framework_fields(
        self, test_domain, caplog
    ):
        """Framework-reserved fields win over caller-supplied ones."""
        app = FastAPI()
        app.add_middleware(
            DomainContextMiddleware, route_domain_map={"/orders": test_domain}
        )

        @app.get("/orders/spoof")
        def spoof():
            bind_event_context(http_status=999, request_id="attacker", tier="gold")
            return {"ok": True}

        client = TestClient(app)
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get("/orders/spoof")
        assert response.status_code == 200

        records = _http_records(caplog)
        assert len(records) == 1
        record = records[0]
        # Framework values preserved, app value passed through
        assert record.http_status == 200
        assert record.request_id != "attacker"
        assert record.tier == "gold"


class TestExcludedPaths:
    def test_excluded_paths_no_wide_event(self, test_domain, caplog):
        app = _make_app(test_domain, exclude_paths=["/healthz"])
        client = TestClient(app)

        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get("/healthz")
        assert response.status_code == 200

        records = _http_records(caplog)
        assert records == []

    def test_non_excluded_paths_still_emit(self, test_domain, caplog):
        app = _make_app(test_domain, exclude_paths=["/healthz"])
        client = TestClient(app)

        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.post("/orders")
        assert response.status_code == 200

        assert len(_http_records(caplog)) == 1

    def test_emission_disabled_globally(self, test_domain, caplog):
        """emit_http_wide_event=False suppresses events for every request."""
        app = _make_app(test_domain, emit=False)
        client = TestClient(app)

        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.post("/orders")
        assert response.status_code == 200

        assert _http_records(caplog) == []

    def test_domain_config_exclude_paths_honoured(self, test_domain, caplog):
        """[logging.http].exclude_paths from domain config is respected."""
        test_domain.config["logging"]["http"]["exclude_paths"] = ["/healthz"]
        app = _make_app(test_domain)  # no middleware override
        client = TestClient(app)

        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get("/healthz")
        assert response.status_code == 200

        assert _http_records(caplog) == []

    def test_domain_config_enabled_flag_honoured(self, test_domain, caplog):
        """[logging.http].enabled=False suppresses events without an override."""
        test_domain.config["logging"]["http"]["enabled"] = False
        app = _make_app(test_domain)
        client = TestClient(app)

        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.post("/orders")
        assert response.status_code == 200

        assert _http_records(caplog) == []


class TestCommandsDispatched:
    def test_commands_dispatched_tracked(self, client, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.post("/orders/two-commands")
        assert response.status_code == 200

        records = _http_records(caplog)
        assert len(records) == 1
        record = records[0]
        assert record.commands_dispatched_count == 2
        assert set(record.commands_dispatched) == {
            PlaceOrder.__type__,
            ShipOrder.__type__,
        }

    def test_no_commands_dispatched_yields_empty_list(self, client, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get("/orders/bind")
        assert response.status_code == 200

        records = _http_records(caplog)
        assert len(records) == 1
        assert records[0].commands_dispatched == []
        assert records[0].commands_dispatched_count == 0


class TestClientMetadata:
    def test_user_agent_truncated(self, client, caplog):
        huge_agent = "a" * 400
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.post(
                "/orders",
                headers={"User-Agent": huge_agent},
            )
        assert response.status_code == 200

        records = _http_records(caplog)
        assert len(records) == 1
        assert len(records[0].user_agent) == 256

    def test_client_ip_prefers_forwarded_for(self, client, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.post(
                "/orders",
                headers={"X-Forwarded-For": "203.0.113.42, 10.0.0.1"},
            )
        assert response.status_code == 200

        records = _http_records(caplog)
        assert len(records) == 1
        # The first hop wins — subsequent hops are trusted proxies.
        assert records[0].client_ip == "203.0.113.42"

    def test_client_ip_empty_when_no_forwarded_and_no_peer(self, test_domain, caplog):
        """Covers the fallthrough when X-Forwarded-For is absent and scope has no client."""
        from starlette.datastructures import Headers
        from starlette.requests import Request

        # Build a bare ASGI scope that mimics a request without a client peer
        # (some deployment scenarios — e.g. lifespan-bound handlers — leave
        # ``client`` as ``None`` in the scope).
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/ping",
            "scheme": "http",
            "headers": Headers({}).raw,
            "client": None,
            "server": ("testserver", 80),
            "query_string": b"",
            "root_path": "",
        }
        bare_request = Request(scope)  # type: ignore[arg-type]

        caplog.set_level(logging.DEBUG, logger="protean.access.http")
        DomainContextMiddleware._emit_http_wide_event(
            request=bare_request,
            response=None,
            status_code=200,
            duration_ms=1.0,
            request_id="rid",
            correlation_id="cid",
            commands_dispatched=[],
            error_info=None,
            app_context={},
            config={
                "log_request_headers": False,
                "log_response_headers": False,
            },
        )

        records = _http_records(caplog)
        assert len(records) == 1
        assert records[0].client_ip == ""


class TestHeaderLogging:
    def test_log_request_headers_opt_in(self, test_domain, caplog):
        app = FastAPI()
        app.add_middleware(
            DomainContextMiddleware,
            route_domain_map={"/orders": test_domain},
            log_request_headers=True,
        )

        @app.get("/orders/echo")
        def echo():
            return {"ok": True}

        client = TestClient(app)
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get(
                "/orders/echo",
                headers={"X-Custom": "abc"},
            )
        assert response.status_code == 200

        records = _http_records(caplog)
        assert len(records) == 1
        assert records[0].http_request_headers.get("x-custom") == "abc"

    def test_log_response_headers_opt_in(self, test_domain, caplog):
        app = FastAPI()
        app.add_middleware(
            DomainContextMiddleware,
            route_domain_map={"/orders": test_domain},
            log_response_headers=True,
        )

        @app.get("/orders/resp")
        def with_header():
            from fastapi.responses import JSONResponse

            return JSONResponse({"ok": True}, headers={"X-Custom-Out": "yes"})

        client = TestClient(app)
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get("/orders/resp")
        assert response.status_code == 200

        records = _http_records(caplog)
        assert len(records) == 1
        assert records[0].http_response_headers.get("x-custom-out") == "yes"


class TestExplicit5xxResponseEmitsAtError:
    def test_5xx_without_exception_emits_error(self, test_domain, caplog):
        """An endpoint returning an explicit 500 Response logs at ERROR."""
        from fastapi.responses import JSONResponse

        app = FastAPI()
        app.add_middleware(
            DomainContextMiddleware, route_domain_map={"/orders": test_domain}
        )

        @app.get("/orders/oops")
        def oops():
            return JSONResponse({"error": "bad"}, status_code=500)

        client = TestClient(app)
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get("/orders/oops")
        assert response.status_code == 500

        records = _http_records(caplog)
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.ERROR
        assert record.getMessage() == "access.http_failed"
        # No exception — error_type is absent
        assert not hasattr(record, "error_type")


class TestEmissionFailureDoesNotCrash:
    def test_emission_failure_swallowed(self, test_domain, caplog):
        """When the access logger itself raises, the response is still returned."""
        from unittest.mock import patch

        app = FastAPI()
        app.add_middleware(
            DomainContextMiddleware, route_domain_map={"/orders": test_domain}
        )

        @app.get("/orders/ok")
        def ok():
            return {"ok": True}

        client = TestClient(app)
        # Force the access logger's .info to raise on the first call — the
        # emission try/except must swallow it.
        with patch(
            "protean.integrations.fastapi.middleware.http_access_logger.info",
            side_effect=RuntimeError("emission broke"),
        ):
            response = client.get("/orders/ok")

        assert response.status_code == 200
        assert response.json() == {"ok": True}


class TestBindOutsideDomainContext:
    def test_bind_event_context_no_middleware_is_safe(self):
        """Calling bind_event_context without middleware/context does not raise."""
        # Simply verify the extras-mirror path handles the absence of g gracefully.
        from protean.utils.logging import _http_wide_event_extras

        assert _http_wide_event_extras() is None

    def test_extras_helper_handles_proxy_failures(self):
        """When ``g.get`` raises AttributeError or RuntimeError, returns None."""
        import protean.utils.globals as globals_mod
        from protean.utils import logging as protean_logging

        class _BadProxy:
            def get(self, name):
                raise RuntimeError("simulated proxy failure")

        original_g = globals_mod.g
        globals_mod.g = _BadProxy()
        try:
            assert protean_logging._http_wide_event_extras() is None
        finally:
            globals_mod.g = original_g


class TestUnbindEventContext:
    def test_unbind_removes_field_from_wide_event(self, test_domain, caplog):
        app = FastAPI()
        app.add_middleware(
            DomainContextMiddleware, route_domain_map={"/orders": test_domain}
        )

        @app.get("/orders/unbind")
        def unbind_endpoint():
            bind_event_context(tier="gold", user_id="u-1")
            unbind_event_context("tier")
            return {"ok": True}

        client = TestClient(app)
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get("/orders/unbind")
        assert response.status_code == 200

        records = _http_records(caplog)
        assert len(records) == 1
        record = records[0]
        assert record.user_id == "u-1"
        assert not hasattr(record, "tier")


class TestResolverPathWideEvent:
    """When a resolver is provided, the wide event still emits."""

    def test_resolver_path_emits_wide_event(self, test_domain, caplog):
        app = FastAPI()

        def resolver(path: str):
            return test_domain if path.startswith("/api") else None

        app.add_middleware(DomainContextMiddleware, resolver=resolver)

        @app.get("/api/ping")
        def ping():
            return {"pong": True}

        client = TestClient(app)
        with caplog.at_level(logging.DEBUG, logger="protean.access.http"):
            response = client.get("/api/ping")
        assert response.status_code == 200

        records = _http_records(caplog)
        assert len(records) == 1
        assert records[0].http_path == "/api/ping"
        # Resolver resolved to test_domain, so correlation_id is auto-generated
        assert records[0].correlation_id != ""
