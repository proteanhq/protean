"""Tests for correlation ID enrichment in error response bodies.

Verifies that:
- Error responses from Protean FastAPI endpoints include ``correlation_id``
  in the JSON body when a domain context is active.
- The body ``correlation_id`` matches the ``X-Correlation-ID`` response header.
- Works for ``ValidationError``, ``ObjectNotFoundError``, ``InvalidStateError``,
  ``InvalidOperationError``, ``InvalidDataError``, and plain ``ValueError``.
- No ``correlation_id`` appears in the body for routes outside domain context.
- Correlation ID from ``domain.process()`` (``g.used_correlation_id``) is
  preferred over the request-level ID when both are available.
"""

from uuid import uuid4

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import (
    InvalidDataError,
    InvalidOperationError,
    InvalidStateError,
    ObjectNotFoundError,
    ValidationError,
)
from protean.fields import Identifier, String
from protean.integrations.fastapi import DomainContextMiddleware, register_exception_handlers
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


# ---------------------------------------------------------------------------
# Domain elements (used only for command-processing error tests)
# ---------------------------------------------------------------------------


class Widget(BaseAggregate):
    widget_id = Identifier(identifier=True)
    name = String(required=True)


class CreateWidget(BaseCommand):
    widget_id = Identifier(identifier=True)
    name = String(required=True)


class WidgetCommandHandler(BaseCommandHandler):
    @handle(CreateWidget)
    def create(self, command: CreateWidget) -> None:
        Widget(widget_id=command.widget_id, name=command.name)
        # Raise after command processing has enriched correlation context
        raise ObjectNotFoundError("Widget supplier not found")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _make_app(domain) -> FastAPI:
    """Create a FastAPI app with middleware and exception handlers."""
    app = FastAPI()
    app.add_middleware(
        DomainContextMiddleware,
        route_domain_map={"/api": domain},
    )
    register_exception_handlers(app)

    @app.get("/api/validation-error")
    def raise_validation_error():
        raise ValidationError({"name": ["is required"]})

    @app.get("/api/invalid-data-error")
    def raise_invalid_data_error():
        raise InvalidDataError({"email": ["invalid format"]})

    @app.get("/api/value-error")
    def raise_value_error():
        raise ValueError("bad value")

    @app.get("/api/not-found")
    def raise_not_found():
        raise ObjectNotFoundError("User not found")

    @app.get("/api/invalid-state")
    def raise_invalid_state():
        raise InvalidStateError("Order already shipped")

    @app.get("/api/invalid-operation")
    def raise_invalid_operation():
        raise InvalidOperationError("Cannot cancel a completed order")

    @app.post("/api/widgets")
    def create_widget():
        """Endpoint that processes a command which raises during handling."""
        current_domain.process(
            CreateWidget(widget_id=str(uuid4()), name="Sprocket"),
            asynchronous=False,
        )

    # Route outside any domain context
    @app.get("/health")
    def health():
        raise ObjectNotFoundError("Health resource not found")

    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Widget)
    test_domain.register(CreateWidget, part_of=Widget)
    test_domain.register(WidgetCommandHandler, part_of=Widget)
    test_domain.init(traverse=False)


@pytest.fixture()
def app(test_domain) -> FastAPI:
    return _make_app(test_domain)


@pytest.fixture()
def client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests: correlation_id present in error body for domain-mapped routes
# ---------------------------------------------------------------------------


class TestErrorBodyContainsCorrelationId:
    """Error responses include ``correlation_id`` in body when domain context is active."""

    def test_validation_error_has_correlation_id(self, client):
        response = client.get(
            "/api/validation-error",
            headers={"X-Correlation-ID": "corr-val-err"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["correlation_id"] == "corr-val-err"
        assert body["error"] == {"name": ["is required"]}

    def test_invalid_data_error_has_correlation_id(self, client):
        response = client.get(
            "/api/invalid-data-error",
            headers={"X-Correlation-ID": "corr-inv-data"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["correlation_id"] == "corr-inv-data"
        assert body["error"] == {"email": ["invalid format"]}

    def test_value_error_has_correlation_id(self, client):
        response = client.get(
            "/api/value-error",
            headers={"X-Correlation-ID": "corr-val"},
        )
        assert response.status_code == 400
        body = response.json()
        assert body["correlation_id"] == "corr-val"
        assert body["error"] == "bad value"

    def test_not_found_error_has_correlation_id(self, client):
        response = client.get(
            "/api/not-found",
            headers={"X-Correlation-ID": "corr-404"},
        )
        assert response.status_code == 404
        body = response.json()
        assert body["correlation_id"] == "corr-404"
        assert body["error"] == "User not found"

    def test_invalid_state_error_has_correlation_id(self, client):
        response = client.get(
            "/api/invalid-state",
            headers={"X-Correlation-ID": "corr-409"},
        )
        assert response.status_code == 409
        body = response.json()
        assert body["correlation_id"] == "corr-409"
        assert body["error"] == "Order already shipped"

    def test_invalid_operation_error_has_correlation_id(self, client):
        response = client.get(
            "/api/invalid-operation",
            headers={"X-Correlation-ID": "corr-422"},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["correlation_id"] == "corr-422"
        assert body["error"] == "Cannot cancel a completed order"


# ---------------------------------------------------------------------------
# Tests: body correlation_id matches response header
# ---------------------------------------------------------------------------


class TestBodyMatchesHeader:
    """The ``correlation_id`` in the body matches the ``X-Correlation-ID`` header."""

    def test_body_matches_header_with_supplied_id(self, client):
        response = client.get(
            "/api/not-found",
            headers={"X-Correlation-ID": "match-me"},
        )
        body = response.json()
        assert body["correlation_id"] == response.headers["X-Correlation-ID"]
        assert body["correlation_id"] == "match-me"

    def test_body_matches_header_with_auto_generated_id(self, client):
        response = client.get("/api/not-found")
        body = response.json()
        assert "correlation_id" in body
        assert body["correlation_id"] == response.headers["X-Correlation-ID"]
        # Auto-generated UUID4 hex is 32 chars
        assert len(body["correlation_id"]) == 32

    def test_body_matches_header_with_request_id_fallback(self, client):
        response = client.get(
            "/api/not-found",
            headers={"X-Request-ID": "req-fallback"},
        )
        body = response.json()
        assert body["correlation_id"] == "req-fallback"
        assert body["correlation_id"] == response.headers["X-Correlation-ID"]


# ---------------------------------------------------------------------------
# Tests: no correlation_id for routes outside domain context
# ---------------------------------------------------------------------------


class TestNoCorrelationWithoutDomainContext:
    """Error responses outside domain context do not include ``correlation_id``."""

    def test_no_correlation_id_on_unmapped_route(self, client):
        response = client.get("/health")
        assert response.status_code == 404
        body = response.json()
        assert body["error"] == "Health resource not found"
        assert "correlation_id" not in body


# ---------------------------------------------------------------------------
# Tests: command processing error includes used_correlation_id
# ---------------------------------------------------------------------------


class TestCommandProcessingErrorCorrelation:
    """When a command handler raises, the error body carries the correlation ID
    that command processing resolved (``g.used_correlation_id``)."""

    def test_command_handler_error_has_correlation_id(self, client):
        response = client.post(
            "/api/widgets",
            headers={"X-Correlation-ID": "cmd-err-corr"},
        )
        assert response.status_code == 404
        body = response.json()
        assert body["correlation_id"] == "cmd-err-corr"
        assert "Widget supplier not found" in body["error"]

    def test_command_handler_error_auto_generated_id(self, client):
        response = client.post("/api/widgets")
        assert response.status_code == 404
        body = response.json()
        assert "correlation_id" in body
        assert len(body["correlation_id"]) == 32
        assert body["correlation_id"] == response.headers["X-Correlation-ID"]
