"""Tests for FastAPI exception handler mappings."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean.exceptions import (
    InvalidDataError,
    InvalidOperationError,
    InvalidStateError,
    ObjectNotFoundError,
    ValidationError,
)
from protean.integrations.fastapi import register_exception_handlers


@pytest.fixture
def app():
    """Create a FastAPI app with Protean exception handlers registered."""
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/validation-error")
    def raise_validation_error():
        raise ValidationError({"name": ["is required"]})

    @app.get("/invalid-data-error")
    def raise_invalid_data_error():
        raise InvalidDataError({"email": ["invalid format"]})

    @app.get("/value-error")
    def raise_value_error():
        raise ValueError("bad value")

    @app.get("/not-found")
    def raise_not_found():
        raise ObjectNotFoundError("User not found")

    @app.get("/invalid-state")
    def raise_invalid_state():
        raise InvalidStateError("Order already shipped")

    @app.get("/invalid-operation")
    def raise_invalid_operation():
        raise InvalidOperationError("Cannot cancel a completed order")

    @app.get("/generic-error")
    def raise_generic():
        raise RuntimeError("unexpected")

    return app


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


class TestExceptionHandlerMappings:
    def test_validation_error_returns_400(self, client):
        response = client.get("/validation-error")
        assert response.status_code == 400

    def test_invalid_data_error_returns_400(self, client):
        response = client.get("/invalid-data-error")
        assert response.status_code == 400

    def test_value_error_returns_400(self, client):
        response = client.get("/value-error")
        assert response.status_code == 400

    def test_object_not_found_returns_404(self, client):
        response = client.get("/not-found")
        assert response.status_code == 404

    def test_invalid_state_returns_409(self, client):
        response = client.get("/invalid-state")
        assert response.status_code == 409

    def test_invalid_operation_returns_422(self, client):
        response = client.get("/invalid-operation")
        assert response.status_code == 422

    def test_error_response_body_format(self, client):
        """All error responses have a JSON body with an 'error' key."""
        response = client.get("/not-found")
        data = response.json()
        assert "error" in data

    def test_validation_error_body_contains_messages(self, client):
        """ValidationError response body contains the error messages dict."""
        response = client.get("/validation-error")
        data = response.json()
        assert data["error"] == {"name": ["is required"]}

    def test_value_error_body_contains_string(self, client):
        """ValueError response body contains the error string."""
        response = client.get("/value-error")
        data = response.json()
        assert data["error"] == "bad value"

    def test_unhandled_exception_returns_500(self, client):
        """Unregistered exceptions get default FastAPI 500 handling."""
        response = client.get("/generic-error")
        assert response.status_code == 500
