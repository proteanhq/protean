"""Tests for Observatory Infrastructure API endpoints and supporting functions.

Tests for:
- routes/infrastructure.py: _server_info, _database_status, _broker_status,
  _event_store_status, _cache_status, sanitize_config,
  create_infrastructure_router
- templates/infrastructure.html: structure and JS inclusion
- static/js/infrastructure.js: file presence
"""

import platform
from unittest.mock import MagicMock, patch

import pytest
import redis
from fastapi.testclient import TestClient

import protean
from protean import Domain
from protean.server.observatory import Observatory
from protean.server.observatory.routes.infrastructure import (
    _broker_status,
    _cache_status,
    _database_status,
    _event_store_status,
    _server_info,
    sanitize_config,
)
from tests.server.observatory.conftest import route_paths

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def observatory(test_domain):
    return Observatory(domains=[test_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


@pytest.fixture
def uninitialized_domain():
    """A domain that has not run init(), so it has no adapters yet."""
    return Domain(name="Uninitialized")


def _initialized_domain(name="TestDomain", config=None):
    domain = Domain(name=name, config=config)
    domain.init(traverse=False)
    return domain


class _CacheWithoutPing:
    """Stands in for a cache adapter that has no ping() method.

    BaseCache declares ping() abstract, so every real cache defines it and
    the no-ping case needs a stand-in object.
    """


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

    @pytest.mark.parametrize(
        "config, secret_key, plain_key, plain_value",
        [
            (
                {"provider": "redis", "password": "secret123"},
                "password",
                "provider",
                "redis",
            ),
            ({"api_key": "sk-12345", "name": "test"}, "api_key", "name", "test"),
        ],
        ids=["password", "api_key"],
    )
    def test_masks_sensitive_keys(self, config, secret_key, plain_key, plain_value):
        result = sanitize_config(config)
        assert result[secret_key] == "***"
        assert result[plain_key] == plain_value

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
    def test_includes_versions_and_platform(self, test_domain):
        info = _server_info([test_domain])
        assert info["python_version"] == platform.python_version()
        assert info["protean_version"] == protean.__version__
        assert "platform" in info
        assert isinstance(info["platform"], str)

    @pytest.mark.no_test_domain
    def test_includes_domain_names(self):
        info = _server_info([Domain(name="Domain1"), Domain(name="Domain2")])
        assert len(info["domains"]) == 2
        names = {d["name"] for d in info["domains"]}
        assert names == {"Domain1", "Domain2"}

    def test_includes_domain_config(self, test_domain):
        info = _server_info([test_domain])
        assert len(info["domains"]) == 1
        config = info["domains"][0]["config"]
        assert config["databases"]["default"]["provider"] == "memory"
        assert config["brokers"]["default"]["provider"] == "redis"
        assert config["has_outbox"] is True

    @pytest.mark.no_test_domain
    def test_omits_missing_config_sections(self, uninitialized_domain):
        del uninitialized_domain.config["server"]

        info = _server_info([uninitialized_domain])
        config = info["domains"][0]["config"]
        assert "server" not in config
        assert "databases" in config


# ---------------------------------------------------------------------------
# _database_status
# ---------------------------------------------------------------------------


class TestDatabaseStatus:
    def test_provider_available(self, test_domain):
        result = _database_status(test_domain)
        assert result["status"] == "healthy"
        assert result["provider"] == "memory"

    @pytest.mark.no_test_domain
    def test_provider_not_configured(self, uninitialized_domain):
        result = _database_status(uninitialized_domain)
        assert result["status"] == "not_configured"

    def test_handles_exception(self, test_domain):
        with patch.object(
            test_domain, "domain_context", side_effect=Exception("DB error")
        ):
            result = _database_status(test_domain)
        assert result["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# _broker_status
# ---------------------------------------------------------------------------


class TestBrokerStatus:
    def test_healthy_broker(self, test_domain, monkeypatch):
        broker = test_domain.brokers["default"]
        # The core lane has no Redis server, so the raw Redis client is faked.
        fake_redis = MagicMock()
        fake_redis.ping.return_value = True
        fake_redis.info.return_value = {
            "redis_version": "7.2.4",
            "connected_clients": 5,
            "used_memory_human": "2.5M",
            "uptime_in_seconds": 86400,
            "instantaneous_ops_per_sec": 120,
            "keyspace_hits": 985,
            "keyspace_misses": 15,
        }
        fake_redis.type.return_value = b"stream"
        fake_redis.xlen.return_value = 0
        fake_redis.xinfo_groups.return_value = []
        monkeypatch.setattr(broker, "redis_instance", fake_redis)
        monkeypatch.setattr(
            broker, "_created_groups_set", {"order:g1", "order:g2", "payment:g3"}
        )

        result = _broker_status(test_domain)
        assert result["status"] == "healthy"
        assert result["provider"] == "redis"
        assert result["details"]["redis_version"] == "7.2.4"
        assert result["details"]["connected_clients"] == 5
        assert result["details"]["used_memory_human"] == "2.5M"
        assert result["details"]["uptime_in_seconds"] == 86400
        assert result["details"]["instantaneous_ops_per_sec"] == 120
        assert result["details"]["hit_rate"] == pytest.approx(0.985)
        assert result["details"]["stream_count"] == 2
        assert result["details"]["consumer_group_count"] == 3

    def test_unhealthy_broker(self, test_domain, monkeypatch):
        broker = test_domain.brokers["default"]
        # Nothing listens on port 1, so every Redis call is refused. The
        # client's default retries would back off for seconds before failing.
        monkeypatch.setattr(
            broker,
            "redis_instance",
            redis.Redis(
                host="127.0.0.1", port=1, socket_connect_timeout=0.5, retry=None
            ),
        )

        result = _broker_status(test_domain)
        assert result["status"] == "unhealthy"

    @pytest.mark.no_test_domain
    def test_no_broker(self, uninitialized_domain):
        result = _broker_status(uninitialized_domain)
        assert result["status"] == "not_configured"

    def test_handles_exception(self, test_domain):
        with patch.object(
            test_domain, "domain_context", side_effect=Exception("Broker error")
        ):
            result = _broker_status(test_domain)
        assert result["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# _event_store_status
# ---------------------------------------------------------------------------


class TestEventStoreStatus:
    def test_memory_event_store(self, test_domain):
        result = _event_store_status(test_domain)
        assert result["status"] == "healthy"
        assert result["provider"] == "memory"

    @pytest.mark.no_test_domain
    def test_no_event_store(self, uninitialized_domain):
        result = _event_store_status(uninitialized_domain)
        assert result["status"] == "not_configured"

    def test_handles_exception(self, test_domain):
        with patch.object(
            test_domain, "domain_context", side_effect=Exception("ES error")
        ):
            result = _event_store_status(test_domain)
        assert result["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# _cache_status
# ---------------------------------------------------------------------------


class TestCacheStatus:
    def test_cache_available_with_ping(self, test_domain):
        result = _cache_status(test_domain)
        assert result["status"] == "healthy"
        assert result["provider"] == "memory"

    @pytest.mark.no_test_domain
    def test_cache_without_ping(self):
        domain = _initialized_domain()
        domain.caches["default"] = _CacheWithoutPing()

        result = _cache_status(domain)
        assert result["status"] == "healthy"

    @pytest.mark.no_test_domain
    def test_no_cache_configured(self, uninitialized_domain):
        result = _cache_status(uninitialized_domain)
        assert result["status"] == "not_configured"

    def test_handles_exception(self, test_domain):
        with patch.object(
            test_domain, "domain_context", side_effect=Exception("Cache error")
        ):
            result = _cache_status(test_domain)
        assert result["status"] == "unhealthy"

    def test_ping_failure(self, test_domain):
        with patch.object(
            test_domain.caches["default"],
            "ping",
            side_effect=ConnectionError("Connection refused"),
        ):
            result = _cache_status(test_domain)
        assert result["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# Endpoint: GET /infrastructure/status
# ---------------------------------------------------------------------------


class TestInfrastructureStatusEndpoint:
    def test_has_server_section(self, client):
        response = client.get("/api/infrastructure/status")
        data = response.json()
        assert "server" in data
        assert "python_version" in data["server"]
        assert "protean_version" in data["server"]
        assert "domains" in data["server"]

    def test_connections_has_all_adapters(self, client):
        response = client.get("/api/infrastructure/status")
        assert response.status_code == 200
        data = response.json()
        assert "connections" in data
        connections = data["connections"]
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
    def test_extends_base_template(self, client):
        response = client.get("/infrastructure")
        assert response.status_code == 200
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
        routes = route_paths(observatory.app.routes)
        assert "/api/infrastructure/status" in routes

    def test_page_route_included(self, observatory):
        """Verify the page route exists."""
        routes = route_paths(observatory.app.routes)
        assert "/infrastructure" in routes


# ---------------------------------------------------------------------------
# Config sections that are not mappings
# ---------------------------------------------------------------------------


class TestDatabaseStatusConfigWithoutGet:
    def test_database_config_without_get_method(self, test_domain):
        """A databases section that is not a mapping leaves provider at 'none'."""
        test_domain.config["databases"] = "some_string_value"

        result = _database_status(test_domain)
        assert result["provider"] == "none"
        assert result["status"] == "healthy"

    def test_database_default_config_without_get_method(self, test_domain):
        """A default database entry that is not a mapping leaves provider at 'none'."""
        test_domain.config["databases"] = {"default": "not-a-dict"}

        result = _database_status(test_domain)
        assert result["provider"] == "none"
        assert result["status"] == "healthy"


@pytest.mark.no_test_domain
class TestBrokerStatusConfigWithoutGet:
    def test_broker_config_without_get_method(self, uninitialized_domain):
        """A brokers section that is not a mapping leaves provider at 'none'."""
        uninitialized_domain.config["brokers"] = "string_config"

        result = _broker_status(uninitialized_domain)
        assert result["provider"] == "none"

    def test_broker_default_config_without_get_method(self, uninitialized_domain):
        """A default broker entry that is not a mapping leaves provider at 'none'."""
        uninitialized_domain.config["brokers"] = {"default": 42}

        result = _broker_status(uninitialized_domain)
        assert result["provider"] == "none"


class TestEventStoreStatusConfigWithoutGet:
    def test_event_store_config_without_get_method(self, test_domain):
        """An event_store section that is not a mapping leaves provider at 'none'."""
        test_domain.config["event_store"] = "not-a-dict"

        result = _event_store_status(test_domain)
        assert result["provider"] == "none"
        assert result["status"] == "healthy"


class TestCacheStatusConfigWithoutGet:
    def test_cache_config_without_get_method(self, test_domain):
        """A caches section that is not a mapping leaves provider at 'none'."""
        test_domain.config["caches"] = "not-a-dict"

        result = _cache_status(test_domain)
        assert result["provider"] == "none"
        assert result["status"] == "healthy"

    def test_cache_default_config_without_get_method(self, test_domain):
        """A default cache entry that is not a mapping leaves provider at 'none'."""
        test_domain.config["caches"] = {"default": True}

        result = _cache_status(test_domain)
        assert result["provider"] == "none"

    @pytest.mark.no_test_domain
    def test_cache_is_none(self):
        """Caches are configured, but none of them is named 'default'."""
        domain = _initialized_domain(
            config={"caches": {"secondary": {"provider": "memory"}}}
        )
        del domain.caches["default"]

        result = _cache_status(domain)
        assert result["status"] == "not_configured"
