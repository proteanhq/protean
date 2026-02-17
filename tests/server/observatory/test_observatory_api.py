"""Tests for Observatory REST API endpoints.

These tests require a running Redis instance and are gated behind @pytest.mark.redis.
"""

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory
from tests.shared import initialize_domain


@pytest.fixture
def redis_domain():
    """Domain configured with Redis broker and outbox enabled."""
    domain = initialize_domain(name="Observatory API Tests", root_path=__file__)
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain


@pytest.fixture
def observatory(redis_domain):
    """Observatory instance backed by a real Redis domain."""
    return Observatory(domains=[redis_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


@pytest.mark.redis
class TestDashboardEndpoint:
    def test_dashboard_returns_html(self, client):
        """GET / returns 200 with HTML content."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


@pytest.mark.redis
class TestHealthEndpoint:
    def test_health_endpoint_returns_ok(self, client):
        """GET /api/health returns 200 with status."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "domains" in data
        assert "infrastructure" in data

    def test_health_shows_broker_details(self, client):
        """Health response includes broker details."""
        response = client.get("/api/health")
        data = response.json()
        broker_info = data["infrastructure"]["broker"]
        assert "healthy" in broker_info
        assert "version" in broker_info
        assert "connected_clients" in broker_info
        assert "memory" in broker_info
        assert "ops_per_sec" in broker_info

    def test_health_lists_domain_names(self, client, redis_domain):
        """Health response lists monitored domain names."""
        response = client.get("/api/health")
        data = response.json()
        assert redis_domain.name in data["domains"]


@pytest.mark.redis
class TestOutboxEndpoint:
    def test_outbox_returns_counts(self, client, redis_domain):
        """GET /api/outbox returns outbox counts keyed by domain name."""
        response = client.get("/api/outbox")
        assert response.status_code == 200
        data = response.json()
        assert redis_domain.name in data

    def test_outbox_domain_has_status_field(self, client, redis_domain):
        """Each domain entry in outbox has a status field."""
        response = client.get("/api/outbox")
        data = response.json()
        domain_data = data[redis_domain.name]
        assert "status" in domain_data


@pytest.mark.redis
class TestStreamsEndpoint:
    def test_streams_returns_message_counts(self, client):
        """GET /api/streams returns message_counts and consumer_groups."""
        response = client.get("/api/streams")
        assert response.status_code == 200
        data = response.json()
        assert "message_counts" in data
        assert "streams" in data
        assert "consumer_groups" in data


@pytest.mark.redis
class TestStatsEndpoint:
    def test_stats_combines_outbox_and_stream_data(self, client, redis_domain):
        """GET /api/stats returns outbox + stream data."""
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "outbox" in data
        assert "message_counts" in data
        assert "streams" in data
        assert redis_domain.name in data["outbox"]
