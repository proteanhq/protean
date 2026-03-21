"""Tests for X-Correlation-ID header extraction, propagation, and injection.

Verifies that:
- ``X-Correlation-ID`` from the request is stored in ``g.request_correlation_id``
  and used as the default correlation ID during command processing.
- ``X-Request-ID`` is used as a fallback when ``X-Correlation-ID`` is absent.
- ``domain.process(cmd, correlation_id=...)`` beats the header value.
- Requests without either header auto-generate a correlation ID (for domain-mapped routes).
- The response always includes ``X-Correlation-ID`` for domain-mapped routes.
"""

from uuid import uuid4

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.integrations.fastapi import DomainContextMiddleware
from protean.utils.globals import current_domain, g
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


class OrderCommandHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def place(self, command: PlaceOrder) -> dict:
        order = Order(order_id=command.order_id, customer_name=command.customer_name)
        current_domain.repository_for(Order).add(order)
        return {"placed": command.order_id}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(domain) -> FastAPI:
    """Create a FastAPI app with DomainContextMiddleware."""
    app = FastAPI()
    app.add_middleware(
        DomainContextMiddleware,
        route_domain_map={"/orders": domain},
    )

    @app.post("/orders")
    def create_order():
        order_id = str(uuid4())
        current_domain.process(
            PlaceOrder(order_id=order_id, customer_name="Alice"),
            asynchronous=False,
        )
        return {"order_id": order_id}

    @app.post("/orders/explicit-correlation")
    def create_order_explicit():
        """Endpoint that passes an explicit correlation_id to domain.process."""
        order_id = str(uuid4())
        current_domain.process(
            PlaceOrder(order_id=order_id, customer_name="Bob"),
            asynchronous=False,
            correlation_id="explicit-override-id",
        )
        return {"order_id": order_id}

    @app.get("/orders/inspect-g")
    def inspect_g():
        """Return correlation-related g attributes for inspection."""
        return {
            "request_correlation_id": getattr(g, "request_correlation_id", None),
        }

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Order, fact_events=True)
    test_domain.register(PlaceOrder, part_of=Order)
    test_domain.register(OrderCommandHandler, part_of=Order)
    test_domain.init(traverse=False)


@pytest.fixture()
def app(test_domain) -> FastAPI:
    return _make_app(test_domain)


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests: Header extraction and propagation
# ---------------------------------------------------------------------------


class TestCorrelationHeaderExtraction:
    """X-Correlation-ID is extracted from the request and stored in g."""

    def test_correlation_id_stored_in_g(self, client):
        """X-Correlation-ID header value is available as g.request_correlation_id."""
        response = client.get(
            "/orders/inspect-g",
            headers={"X-Correlation-ID": "abc123"},
        )
        assert response.status_code == 200
        assert response.json()["request_correlation_id"] == "abc123"

    def test_request_id_fallback(self, client):
        """X-Request-ID is used when X-Correlation-ID is absent."""
        response = client.get(
            "/orders/inspect-g",
            headers={"X-Request-ID": "req-456"},
        )
        assert response.status_code == 200
        assert response.json()["request_correlation_id"] == "req-456"

    def test_correlation_id_beats_request_id(self, client):
        """X-Correlation-ID takes precedence over X-Request-ID."""
        response = client.get(
            "/orders/inspect-g",
            headers={
                "X-Correlation-ID": "corr-wins",
                "X-Request-ID": "req-loses",
            },
        )
        assert response.status_code == 200
        assert response.json()["request_correlation_id"] == "corr-wins"

    def test_auto_generated_when_no_header(self, client):
        """Without either header, a correlation ID is still auto-generated."""
        response = client.get("/orders/inspect-g")
        assert response.status_code == 200
        auto_id = response.json()["request_correlation_id"]
        assert auto_id is not None
        assert len(auto_id) == 32  # UUID4 hex


# ---------------------------------------------------------------------------
# Tests: Command processing uses header correlation ID
# ---------------------------------------------------------------------------


class TestCommandCorrelationFromHeader:
    """Commands pick up the HTTP header correlation ID when no explicit ID is given."""

    def test_header_correlation_id_propagates_to_command(self, client, test_domain):
        """Command processed during request uses X-Correlation-ID from request."""
        response = client.post(
            "/orders",
            headers={"X-Correlation-ID": "http-corr-123"},
        )
        assert response.status_code == 200

        # Verify the response header reflects the same correlation ID
        assert response.headers["X-Correlation-ID"] == "http-corr-123"

        # Verify the command stored in the event store has the right correlation ID
        messages = test_domain.event_store.store.read("order:command")
        assert len(messages) >= 1
        last_cmd = messages[-1]
        assert last_cmd.metadata.domain.correlation_id == "http-corr-123"

    def test_request_id_fallback_propagates_to_command(self, client, test_domain):
        """Command uses X-Request-ID when X-Correlation-ID is absent."""
        response = client.post(
            "/orders",
            headers={"X-Request-ID": "fallback-req-789"},
        )
        assert response.status_code == 200
        assert response.headers["X-Correlation-ID"] == "fallback-req-789"

        messages = test_domain.event_store.store.read("order:command")
        assert len(messages) >= 1
        last_cmd = messages[-1]
        assert last_cmd.metadata.domain.correlation_id == "fallback-req-789"

    def test_explicit_correlation_id_beats_header(self, client, test_domain):
        """domain.process(cmd, correlation_id=...) overrides the header value."""
        response = client.post(
            "/orders/explicit-correlation",
            headers={"X-Correlation-ID": "header-value"},
        )
        assert response.status_code == 200

        # The explicit override should win
        assert response.headers["X-Correlation-ID"] == "explicit-override-id"

        messages = test_domain.event_store.store.read("order:command")
        assert len(messages) >= 1
        last_cmd = messages[-1]
        assert last_cmd.metadata.domain.correlation_id == "explicit-override-id"

    def test_auto_generated_when_no_header(self, client, test_domain):
        """Without any header, a correlation ID is still auto-generated."""
        response = client.post("/orders")
        assert response.status_code == 200

        # Response should still include X-Correlation-ID (auto-generated)
        assert "X-Correlation-ID" in response.headers
        auto_id = response.headers["X-Correlation-ID"]
        assert len(auto_id) == 32  # UUID4 hex is 32 chars

        messages = test_domain.event_store.store.read("order:command")
        assert len(messages) >= 1
        last_cmd = messages[-1]
        assert last_cmd.metadata.domain.correlation_id == auto_id


# ---------------------------------------------------------------------------
# Tests: Response header injection
# ---------------------------------------------------------------------------


class TestResponseCorrelationHeader:
    """Response always includes X-Correlation-ID reflecting what was used."""

    def test_response_echoes_supplied_id(self, client):
        """Response includes the same X-Correlation-ID that was sent."""
        response = client.post(
            "/orders",
            headers={"X-Correlation-ID": "echo-me"},
        )
        assert response.headers["X-Correlation-ID"] == "echo-me"

    def test_response_includes_auto_generated_id(self, client):
        """Response includes auto-generated X-Correlation-ID when none sent."""
        response = client.post("/orders")
        assert "X-Correlation-ID" in response.headers

    def test_no_header_on_unmapped_routes(self, client):
        """Routes without domain context don't get correlation headers."""
        response = client.get("/health")
        assert response.status_code == 200
        assert "X-Correlation-ID" not in response.headers

    def test_response_header_for_read_endpoint_with_header(self, client):
        """Even non-command endpoints echo X-Correlation-ID within domain context."""
        response = client.get(
            "/orders/inspect-g",
            headers={"X-Correlation-ID": "read-req-id"},
        )
        assert response.status_code == 200
        assert response.headers["X-Correlation-ID"] == "read-req-id"

    def test_response_header_for_read_endpoint_without_header(self, client):
        """Domain-mapped read endpoints get an auto-generated correlation ID."""
        response = client.get("/orders/inspect-g")
        assert response.status_code == 200
        assert "X-Correlation-ID" in response.headers
        assert len(response.headers["X-Correlation-ID"]) == 32


# ---------------------------------------------------------------------------
# Tests: Event propagation (existing mechanism)
# ---------------------------------------------------------------------------


class TestEventCorrelationPropagation:
    """Events raised during command processing inherit the correlation ID."""

    def test_events_inherit_correlation_from_http_header(self, client, test_domain):
        """Events produced by the command handler carry the same correlation ID."""
        response = client.post(
            "/orders",
            headers={"X-Correlation-ID": "trace-through-events"},
        )
        assert response.status_code == 200

        # Read fact events from the event store — they should carry the same correlation
        order_id = response.json()["order_id"]
        events = test_domain.event_store.store.read(
            f"test::order-fact-{order_id}"
        )
        assert len(events) > 0, "Expected at least one fact event"
        for event_msg in events:
            assert event_msg.metadata.domain.correlation_id == "trace-through-events"
