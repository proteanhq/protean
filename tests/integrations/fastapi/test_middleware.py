"""Tests for DomainContextMiddleware."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean.domain import Domain
from protean.integrations.fastapi import DomainContextMiddleware
from protean.utils.globals import current_domain


@pytest.fixture
def domain_a():
    """Create a test domain named 'alpha'."""
    return Domain(name="alpha")


@pytest.fixture
def domain_b():
    """Create a test domain named 'beta'."""
    return Domain(name="beta")


@pytest.fixture
def app(domain_a, domain_b):
    """Create a FastAPI app with DomainContextMiddleware."""
    app = FastAPI()

    app.add_middleware(
        DomainContextMiddleware,
        route_domain_map={
            "/alpha": domain_a,
            "/beta": domain_b,
        },
    )

    @app.get("/alpha/test")
    def alpha_endpoint():
        return {"domain": current_domain.name}

    @app.get("/beta/test")
    def beta_endpoint():
        return {"domain": current_domain.name}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestDomainContextMiddleware:
    """Tests for route-to-domain context mapping."""

    def test_alpha_route_gets_alpha_context(self, client):
        """Requests to /alpha/* get the alpha domain context."""
        response = client.get("/alpha/test")
        assert response.status_code == 200
        assert response.json()["domain"] == "alpha"

    def test_beta_route_gets_beta_context(self, client):
        """Requests to /beta/* get the beta domain context."""
        response = client.get("/beta/test")
        assert response.status_code == 200
        assert response.json()["domain"] == "beta"

    def test_unmapped_route_passes_through(self, client):
        """Requests to unmapped routes work without domain context."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_unknown_route_returns_404(self, client):
        """Unknown routes still return 404 as normal."""
        response = client.get("/nonexistent")
        assert response.status_code == 404


class TestLongestPrefixMatching:
    """Tests for longest-prefix-first matching behavior."""

    def test_longer_prefix_wins(self, domain_a, domain_b):
        """When /api and /api/v2 are both mapped, /api/v2/x matches /api/v2."""
        app = FastAPI()
        app.add_middleware(
            DomainContextMiddleware,
            route_domain_map={
                "/api": domain_a,
                "/api/v2": domain_b,
            },
        )

        @app.get("/api/v2/items")
        def v2_items():
            return {"domain": current_domain.name}

        @app.get("/api/v1/items")
        def v1_items():
            return {"domain": current_domain.name}

        client = TestClient(app)

        # /api/v2/items should match /api/v2 (longer prefix) → beta
        response = client.get("/api/v2/items")
        assert response.json()["domain"] == "beta"

        # /api/v1/items should match /api (shorter prefix) → alpha
        response = client.get("/api/v1/items")
        assert response.json()["domain"] == "alpha"


class TestCustomResolver:
    """Tests for the custom resolver callback."""

    def test_resolver_overrides_route_map(self, domain_a, domain_b):
        """Custom resolver is used instead of route_domain_map."""
        app = FastAPI()

        def my_resolver(path: str):
            if "/special" in path:
                return domain_b
            return domain_a

        app.add_middleware(
            DomainContextMiddleware,
            resolver=my_resolver,
        )

        @app.get("/anything")
        def anything():
            return {"domain": current_domain.name}

        @app.get("/special/route")
        def special():
            return {"domain": current_domain.name}

        client = TestClient(app)

        response = client.get("/anything")
        assert response.json()["domain"] == "alpha"

        response = client.get("/special/route")
        assert response.json()["domain"] == "beta"

    def test_resolver_returning_none_skips_context(self, domain_a):
        """When resolver returns None, no domain context is pushed."""
        app = FastAPI()

        def selective_resolver(path: str):
            if path.startswith("/domain"):
                return domain_a
            return None

        app.add_middleware(
            DomainContextMiddleware,
            resolver=selective_resolver,
        )

        @app.get("/health")
        def health():
            return {"status": "ok"}

        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestValidation:
    """Tests for middleware configuration validation."""

    def test_requires_route_map_or_resolver(self):
        """Raises ValueError if neither route_domain_map nor resolver is provided."""
        app = FastAPI()

        with pytest.raises(ValueError, match="requires either"):
            app.add_middleware(DomainContextMiddleware)
            # Force middleware instantiation by making a request
            TestClient(app).get("/")
