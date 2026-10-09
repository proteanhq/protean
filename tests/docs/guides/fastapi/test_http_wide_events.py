"""The examples on the HTTP wide events guide behave as the page says."""

import logging

import pytest
import structlog
from fastapi.testclient import TestClient

from tests.docs.support import load_example

pytestmark = [pytest.mark.no_test_domain, pytest.mark.fastapi]


@pytest.fixture
def http_events(caplog):
    caplog.set_level(logging.DEBUG, logger="protean.access.http")

    def events():
        return [
            r
            for r in caplog.records
            if r.name == "protean.access.http"
            and r.getMessage().startswith("access.http_")
        ]

    return events


def test_every_request_emits_one_wide_event_with_the_request_envelope(http_events):
    example = load_example("guides/fastapi/http-wide-events/001.py")
    client = TestClient(example.app)

    response = client.get(
        "/customers/42",
        headers={"X-Request-ID": "req-7a2b4f", "X-Correlation-ID": "req-abc-123"},
    )

    assert response.status_code == 200
    [event] = http_events()
    assert event.getMessage() == "access.http_completed"
    assert event.levelname == "INFO"
    assert event.http_method == "GET"
    assert event.http_path == "/customers/42"
    assert event.http_status == 200
    assert event.http_duration_ms >= 0
    assert event.route_name == "get_customer"
    assert event.route_pattern == "/customers/{customer_id}"
    assert event.request_id == "req-7a2b4f"
    assert event.correlation_id == "req-abc-123"
    assert event.commands_dispatched == []
    assert event.commands_dispatched_count == 0
    assert event.user_agent == "testclient"


def test_the_level_follows_the_status(http_events):
    example = load_example("guides/fastapi/http-wide-events/001.py")
    client = TestClient(example.app, raise_server_exceptions=False)

    client.get("/customers/42")
    client.post("/products/7/retire")
    failed = client.get("/products/7/price")

    assert failed.status_code == 500
    assert "X-Request-ID" in failed.headers
    ok, client_error, server_error = http_events()
    assert (ok.levelname, ok.http_status) == ("INFO", 200)
    assert (client_error.levelname, client_error.http_status) == ("WARNING", 409)
    assert server_error.getMessage() == "access.http_failed"
    assert (server_error.levelname, server_error.http_status) == ("ERROR", 500)
    assert server_error.error_type == "RuntimeError"
    assert server_error.error_message == "price service is down"
    assert server_error.exc_info is not None


def test_constructor_arguments_override_the_logging_http_config(http_events):
    example = load_example("guides/fastapi/http-wide-events/002.py")
    # The domain config turns wide events off; the middleware turns them on.
    assert example.my_domain.config["logging"]["http"]["enabled"] is False
    client = TestClient(example.app)

    client.get("/api/orders", headers={"X-Tenant": "acme"})
    client.get("/api/internal/ping")
    client.get("/api/healthz")

    # The constructor's exclude_paths replaced the config's list, so
    # /api/healthz now emits and /api/internal/ping does not.
    assert [e.http_path for e in http_events()] == ["/api/orders", "/api/healthz"]
    assert http_events()[0].http_request_headers["x-tenant"] == "acme"


def test_without_overrides_the_middleware_follows_the_logging_http_config(
    http_events,
):
    example = load_example("guides/fastapi/http-wide-events/002.py")
    client = TestClient(example.default_app)

    client.get("/api/orders")
    assert http_events() == []

    example.my_domain.config["logging"]["http"]["enabled"] = True
    client.get("/api/orders", headers={"X-Tenant": "acme"})
    client.get("/api/healthz")

    [event] = http_events()
    assert event.http_path == "/api/orders"
    assert not hasattr(event, "http_request_headers")


def test_bound_business_fields_reach_the_http_and_the_handler_wide_events(
    http_events, caplog
):
    example = load_example("guides/fastapi/http-wide-events/003.py")
    example.domain.init(traverse=False)
    caplog.set_level(logging.INFO, logger="protean.access")

    # The log renderer adds the bound event context to each record it writes,
    # so read that context at the moment the handler event is logged.
    handler_context = {}

    class ContextAtEmit(logging.Handler):
        def emit(self, record):
            if record.getMessage() == "access.handler_completed":
                handler_context.update(structlog.contextvars.get_contextvars())

    access_logger = logging.getLogger("protean.access")
    capture = ContextAtEmit()
    access_logger.addHandler(capture)
    try:
        response = TestClient(example.app).post(
            "/orders",
            json={"customer_id": "c1", "book_id": "b1", "device_platform": "ios"},
        )
    finally:
        access_logger.removeHandler(capture)

    assert response.json() == {"ok": True}
    [event] = http_events()
    assert (event.user_id, event.user_tier, event.device_platform) == (
        "user-42",
        "gold",
        "ios",
    )
    assert event.commands_dispatched == ["Ordering.PlaceOrder.v1"]
    assert handler_context["user_id"] == "user-42"
    assert handler_context["user_tier"] == "gold"
    assert handler_context["device_platform"] == "ios"


def test_bound_fields_cannot_overwrite_framework_fields(http_events):
    example = load_example("guides/fastapi/http-wide-events/003.py")
    example.domain.init(traverse=False)

    response = TestClient(example.app).get(
        "/spoof", headers={"X-Request-ID": "req-real"}
    )

    assert response.status_code == 200
    [event] = http_events()
    assert event.http_status == 200
    assert event.request_id == "req-real"
    # A field that is not reserved still goes through.
    assert event.user_id == "user-42"
