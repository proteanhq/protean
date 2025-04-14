"""Tests for FastAPI server implementation"""

import importlib
import sys
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String


class Person(BaseAggregate):
    """Person Aggregate for testing"""

    name = String(max_length=50, required=True)
    age = Integer(default=0)


@pytest.fixture
def test_domain():
    """Create a test domain with Person aggregate"""
    domain = Domain("test_domain")
    domain.register(Person)
    return domain


@pytest.mark.skipif("fastapi" not in sys.modules, reason="FastAPI not installed")
def test_fastapi_server_initialization():
    """Test FastAPI server initialization"""
    from protean.server.fastapi_server import FastAPIServer

    with mock.patch(
        "protean.utils.domain_discovery.derive_domain"
    ) as mock_derive_domain:
        mock_derive_domain.return_value = Domain("test_domain")
        server = FastAPIServer(domain_path="test_domain")
        assert server.app is not None
        assert server.domain is not None


@pytest.mark.skipif("fastapi" not in sys.modules, reason="FastAPI not installed")
def test_root_endpoint(test_domain):
    """Test the root endpoint of the FastAPI server"""
    from protean.server.fastapi_server import FastAPIServer

    with mock.patch(
        "protean.utils.domain_discovery.derive_domain"
    ) as mock_derive_domain:
        mock_derive_domain.return_value = test_domain
        server = FastAPIServer(domain_path="test_domain")
        client = TestClient(server.app)
        response = client.get("/")
        assert response.status_code == 200
        assert "message" in response.json()
        assert "domain" in response.json()
        assert "protean_version" in response.json()
        assert response.json()["message"] == "Protean API Server"
        assert response.json()["domain"] == "Domain"
        assert (
            response.json()["protean_version"]
            == importlib.import_module("protean").__version__
        )
