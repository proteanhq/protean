"""Tests for the FastAPI health check router factory."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean.domain import Domain
from protean.integrations.fastapi.health import create_health_router


@pytest.fixture
def domain():
    d = Domain(name="HealthTest")
    d.init(traverse=False)
    return d


@pytest.fixture
def app(domain):
    app = FastAPI()
    app.include_router(create_health_router(domain))
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------


class TestLiveness:
    @pytest.mark.no_test_domain
    def test_healthz_returns_200(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["checks"]["application"] == "running"

    @pytest.mark.no_test_domain
    def test_livez_returns_200(self, client):
        response = client.get("/livez")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


class TestReadiness:
    @pytest.mark.no_test_domain
    def test_readyz_returns_200_with_memory_adapters(self, client):
        response = client.get("/readyz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "providers" in body["checks"]
        assert "brokers" in body["checks"]
        assert "event_store" in body["checks"]
        assert "caches" in body["checks"]

    @pytest.mark.no_test_domain
    def test_readyz_checks_providers(self, client):
        response = client.get("/readyz")
        body = response.json()
        # Memory provider is always alive
        for status in body["checks"]["providers"].values():
            assert status == "ok"

    @pytest.mark.no_test_domain
    def test_readyz_checks_event_store(self, client):
        response = client.get("/readyz")
        body = response.json()
        assert body["checks"]["event_store"] == "ok"


# ---------------------------------------------------------------------------
# Router options
# ---------------------------------------------------------------------------


class TestRouterOptions:
    @pytest.mark.no_test_domain
    def test_custom_prefix(self, domain):
        app = FastAPI()
        app.include_router(create_health_router(domain, prefix="/api"))
        client = TestClient(app)

        response = client.get("/api/healthz")
        assert response.status_code == 200

    @pytest.mark.no_test_domain
    def test_custom_tags(self, domain):
        router = create_health_router(domain, tags=["monitoring"])
        assert "monitoring" in router.tags


# ---------------------------------------------------------------------------
# Degraded state
# ---------------------------------------------------------------------------


class TestDegradedState:
    @pytest.mark.no_test_domain
    def test_readyz_returns_503_when_provider_unavailable(self, domain):
        app = FastAPI()
        app.include_router(create_health_router(domain))
        client = TestClient(app)

        for provider in domain.providers.values():
            provider.is_alive = lambda: False

        response = client.get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"

    @pytest.mark.no_test_domain
    def test_readyz_returns_503_when_broker_unavailable(self, domain):
        app = FastAPI()
        app.include_router(create_health_router(domain))
        client = TestClient(app)

        for broker in domain.brokers.values():
            broker.ping = lambda: False

        response = client.get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"

    @pytest.mark.no_test_domain
    def test_readyz_returns_503_when_event_store_unavailable(self, domain):
        app = FastAPI()
        app.include_router(create_health_router(domain))
        client = TestClient(app)

        def _raise(*args, **kwargs):
            raise ConnectionError("unreachable")

        domain.event_store.store._read_last_message = _raise

        response = client.get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["event_store"] == "unavailable"

    @pytest.mark.no_test_domain
    def test_readyz_returns_503_when_provider_raises(self, domain):
        """Provider raising an exception (not just returning False) is handled."""
        app = FastAPI()
        app.include_router(create_health_router(domain))
        client = TestClient(app)

        def _explode():
            raise ConnectionError("db down")

        for provider in domain.providers.values():
            provider.is_alive = _explode

        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"

    @pytest.mark.no_test_domain
    def test_readyz_returns_503_when_broker_raises(self, domain):
        """Broker raising an exception is handled."""
        app = FastAPI()
        app.include_router(create_health_router(domain))
        client = TestClient(app)

        def _explode():
            raise ConnectionError("broker down")

        for broker in domain.brokers.values():
            broker.ping = _explode

        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"

    @pytest.mark.no_test_domain
    def test_readyz_returns_503_when_cache_raises(self, domain):
        """Cache raising an exception is handled."""
        app = FastAPI()
        app.include_router(create_health_router(domain))
        client = TestClient(app)

        def _explode():
            raise ConnectionError("cache down")

        for cache in domain.caches.values():
            cache.ping = _explode

        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
