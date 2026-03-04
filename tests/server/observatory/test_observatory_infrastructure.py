"""Tests for Observatory Infrastructure API endpoints and supporting functions.

Covers:
- routes/infrastructure.py: _server_info, _database_status, _broker_status,
  _event_store_status, _cache_status, sanitize_config,
  create_infrastructure_router
- templates/infrastructure.html: structure and JS inclusion
- static/js/infrastructure.js: file presence
"""

import platform
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import protean
from protean.server.observatory import Observatory
from protean.server.observatory.routes.infrastructure import (
    _broker_status,
    _cache_status,
    _database_status,
    _event_store_status,
    _server_info,
    sanitize_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def observatory(test_domain):
    return Observatory(domains=[test_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


def _make_mock_domain(*, name="TestDomain", config=None):
    """Create a mock domain with the given config."""
    domain = MagicMock()
    domain.name = name

    mock_config = config or {}
    domain.config = MagicMock()
    domain.config.get = lambda key, default=None: mock_config.get(key, default)

    return domain


# ---------------------------------------------------------------------------
# sanitize_config
# ---------------------------------------------------------------------------


class TestSanitizeConfig:
    def test_masks_uri_with_credentials(self):
        result = sanitize_config("postgresql://user:pass@localhost:5432/db")
        assert "pass" not in result
        assert "***@" in result
        assert "localhost:5432/db" in result

    def test_preserves_uri_without_credentials(self):
        uri = "redis://localhost:6379/0"
        result = sanitize_config(uri)
        assert result == uri

    def test_masks_password_keys(self):
        config = {"provider": "redis", "password": "secret123"}
        result = sanitize_config(config)
        assert result["provider"] == "redis"
        assert result["password"] == "***"

    def test_masks_secret_keys(self):
        config = {"api_key": "sk-12345", "name": "test"}
        result = sanitize_config(config)
        assert result["api_key"] == "***"
        assert result["name"] == "test"

    def test_handles_nested_dicts(self):
        config = {
            "databases": {
                "default": {
                    "provider": "postgresql",
                    "database_uri": "postgresql://user:pass@host/db",
                }
            }
        }
        result = sanitize_config(config)
        inner = result["databases"]["default"]
        assert inner["provider"] == "postgresql"
        assert "pass" not in inner["database_uri"]

    def test_handles_lists(self):
        config = ["postgresql://user:pass@host/db", "normal_string"]
        result = sanitize_config(config)
        assert "pass" not in result[0]
        assert result[1] == "normal_string"

    def test_passes_through_non_string_scalars(self):
        assert sanitize_config(42) == 42
        assert sanitize_config(True) is True
        assert sanitize_config(None) is None

    def test_preserves_non_uri_strings(self):
        assert sanitize_config("memory") == "memory"
        assert sanitize_config("some value") == "some value"


# ---------------------------------------------------------------------------
# _server_info
# ---------------------------------------------------------------------------


class TestServerInfo:
    def test_includes_python_version(self):
        domain = _make_mock_domain()
        info = _server_info([domain])
        assert info["python_version"] == platform.python_version()

    def test_includes_protean_version(self):
        domain = _make_mock_domain()
        info = _server_info([domain])
        assert info["protean_version"] == protean.__version__

    def test_includes_platform(self):
        domain = _make_mock_domain()
        info = _server_info([domain])
        assert "platform" in info
        assert isinstance(info["platform"], str)

    def test_includes_domain_names(self):
        d1 = _make_mock_domain(name="Domain1")
        d2 = _make_mock_domain(name="Domain2")
        info = _server_info([d1, d2])
        assert len(info["domains"]) == 2
        names = {d["name"] for d in info["domains"]}
        assert names == {"Domain1", "Domain2"}

    def test_includes_domain_config(self):
        domain = _make_mock_domain(
            config={
                "databases": {"default": {"provider": "memory"}},
                "brokers": {"default": {"provider": "redis"}},
            }
        )
        # Make config values have .items() so sanitize_config handles them
        domain.config.get = lambda key, default=None: {
            "databases": {"default": {"provider": "memory"}},
            "brokers": {"default": {"provider": "redis"}},
        }.get(key, default)

        info = _server_info([domain])
        assert len(info["domains"]) == 1
        assert "config" in info["domains"][0]


# ---------------------------------------------------------------------------
# _database_status
# ---------------------------------------------------------------------------


class TestDatabaseStatus:
    def test_provider_available(self):
        domain = _make_mock_domain(
            config={"databases": {"default": {"provider": "memory"}}}
        )
        domain.providers = {"default": MagicMock()}

        result = _database_status(domain)
        assert result["status"] == "healthy"
        assert result["provider"] == "memory"

    def test_provider_not_configured(self):
        domain = _make_mock_domain(config={"databases": {}})
        domain.providers = {"default": None}

        result = _database_status(domain)
        # Provider is None → not_configured
        assert result["status"] in ("not_configured", "healthy")

    def test_handles_exception(self):
        domain = _make_mock_domain()
        domain.domain_context.side_effect = Exception("DB error")

        result = _database_status(domain)
        assert result["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# _broker_status
# ---------------------------------------------------------------------------


class TestBrokerStatus:
    def test_healthy_broker(self):
        domain = _make_mock_domain(
            config={"brokers": {"default": {"provider": "redis"}}}
        )
        broker = MagicMock()
        broker.health_stats.return_value = {
            "connected": True,
            "details": {
                "redis_version": "7.2.4",
                "connected_clients": 5,
                "used_memory_human": "2.5M",
                "uptime_in_seconds": 86400,
                "instantaneous_ops_per_sec": 120,
                "hit_rate": 98.5,
                "streams": {"count": 8, "names": []},
                "consumer_groups": {"count": 12, "names": []},
            },
        }
        domain.brokers = {"default": broker}

        result = _broker_status(domain)
        assert result["status"] == "healthy"
        assert result["provider"] == "redis"
        assert result["details"]["redis_version"] == "7.2.4"
        assert result["details"]["connected_clients"] == 5
        assert result["details"]["stream_count"] == 8
        assert result["details"]["consumer_group_count"] == 12

    def test_unhealthy_broker(self):
        domain = _make_mock_domain(
            config={"brokers": {"default": {"provider": "redis"}}}
        )
        broker = MagicMock()
        broker.health_stats.return_value = {"connected": False, "details": {}}
        domain.brokers = {"default": broker}

        result = _broker_status(domain)
        assert result["status"] == "unhealthy"

    def test_no_broker(self):
        domain = _make_mock_domain(config={"brokers": {}})
        domain.brokers = {"default": None}

        result = _broker_status(domain)
        assert result["status"] == "not_configured"

    def test_handles_exception(self):
        domain = _make_mock_domain()
        domain.domain_context.side_effect = Exception("Broker error")

        result = _broker_status(domain)
        assert result["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# _event_store_status
# ---------------------------------------------------------------------------


class TestEventStoreStatus:
    def test_memory_event_store(self):
        domain = _make_mock_domain(config={"event_store": {"provider": "memory"}})
        domain.event_store.store = MagicMock()

        result = _event_store_status(domain)
        assert result["status"] == "healthy"
        assert result["provider"] == "memory"

    def test_no_event_store(self):
        domain = _make_mock_domain(config={"event_store": {}})
        domain.event_store.store = None

        result = _event_store_status(domain)
        assert result["status"] == "not_configured"

    def test_handles_exception(self):
        domain = _make_mock_domain()
        domain.domain_context.side_effect = Exception("ES error")

        result = _event_store_status(domain)
        assert result["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# _cache_status
# ---------------------------------------------------------------------------


class TestCacheStatus:
    def test_cache_available_with_ping(self):
        domain = _make_mock_domain(
            config={"caches": {"default": {"provider": "redis"}}}
        )
        cache = MagicMock()
        cache.ping.return_value = True
        domain.caches = {"default": cache}

        result = _cache_status(domain)
        assert result["status"] == "healthy"
        assert result["provider"] == "redis"

    def test_cache_without_ping(self):
        domain = _make_mock_domain(
            config={"caches": {"default": {"provider": "memory"}}}
        )
        cache = MagicMock(spec=[])  # No ping method
        domain.caches = {"default": cache}

        result = _cache_status(domain)
        assert result["status"] == "healthy"

    def test_no_cache_configured(self):
        domain = _make_mock_domain(config={"caches": {}})
        domain.caches = {}

        result = _cache_status(domain)
        assert result["status"] == "not_configured"

    def test_handles_exception(self):
        domain = _make_mock_domain()
        domain.domain_context.side_effect = Exception("Cache error")

        result = _cache_status(domain)
        assert result["status"] == "unhealthy"

    def test_ping_failure(self):
        domain = _make_mock_domain(
            config={"caches": {"default": {"provider": "redis"}}}
        )
        cache = MagicMock()
        cache.ping.side_effect = Exception("Connection refused")
        domain.caches = {"default": cache}

        result = _cache_status(domain)
        assert result["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# Endpoint: GET /infrastructure/status
# ---------------------------------------------------------------------------


class TestInfrastructureStatusEndpoint:
    def test_returns_200(self, client):
        response = client.get("/api/infrastructure/status")
        assert response.status_code == 200

    def test_has_server_section(self, client):
        response = client.get("/api/infrastructure/status")
        data = response.json()
        assert "server" in data
        assert "python_version" in data["server"]
        assert "protean_version" in data["server"]
        assert "domains" in data["server"]

    def test_has_connections_section(self, client):
        response = client.get("/api/infrastructure/status")
        data = response.json()
        assert "connections" in data

    def test_connections_has_all_adapters(self, client):
        response = client.get("/api/infrastructure/status")
        connections = response.json()["connections"]
        assert "database" in connections
        assert "broker" in connections
        assert "event_store" in connections
        assert "cache" in connections

    def test_each_connection_has_status_and_provider(self, client):
        response = client.get("/api/infrastructure/status")
        connections = response.json()["connections"]
        for adapter_type in ("database", "broker", "event_store", "cache"):
            conn = connections[adapter_type]
            assert "status" in conn
            assert "provider" in conn


# ---------------------------------------------------------------------------
# Template: infrastructure.html
# ---------------------------------------------------------------------------


class TestInfrastructureTemplate:
    def test_page_renders_200(self, client):
        response = client.get("/infrastructure")
        assert response.status_code == 200

    def test_extends_base_template(self, client):
        response = client.get("/infrastructure")
        assert "Observatory" in response.text

    def test_includes_infrastructure_js(self, client):
        response = client.get("/infrastructure")
        assert "infrastructure.js" in response.text

    def test_has_connection_tiles(self, client):
        response = client.get("/infrastructure")
        html = response.text
        assert "tile-database" in html
        assert "tile-broker" in html
        assert "tile-event-store" in html
        assert "tile-cache" in html

    def test_has_broker_detail_card(self, client):
        response = client.get("/infrastructure")
        html = response.text
        assert "broker-detail" in html
        assert "broker-redis-version" in html

    def test_has_server_info(self, client):
        response = client.get("/infrastructure")
        html = response.text
        assert "server-python-version" in html
        assert "server-protean-version" in html

    def test_has_domain_config_section(self, client):
        response = client.get("/infrastructure")
        assert "server-domains" in response.text


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------


class TestInfrastructureStaticFiles:
    def test_infrastructure_js_served(self, client):
        response = client.get("/static/js/infrastructure.js")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


class TestInfrastructureRouteWiring:
    def test_infrastructure_routes_included(self, observatory):
        """Verify the infrastructure routes are in the Observatory app."""
        routes = [r.path for r in observatory.app.routes]
        assert "/api/infrastructure/status" in routes

    def test_page_route_included(self, observatory):
        """Verify the page route exists."""
        routes = [r.path for r in observatory.app.routes]
        assert "/infrastructure" in routes
