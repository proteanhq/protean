"""Tests for Observatory Prometheus metrics endpoint.

These tests require a running Redis instance and are gated behind @pytest.mark.redis.
"""

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory
from tests.shared import initialize_domain


@pytest.fixture
def redis_domain():
    """Domain configured with Redis broker and outbox enabled."""
    domain = initialize_domain(name="Observatory Metrics Tests", root_path=__file__)
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain


@pytest.fixture
def client(redis_domain):
    observatory = Observatory(domains=[redis_domain])
    return TestClient(observatory.app)


@pytest.mark.redis
class TestPrometheusMetrics:
    def test_metrics_content_type(self, client):
        """GET /metrics returns Prometheus text content type."""
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        assert "version=0.0.4" in response.headers["content-type"]

    def test_metrics_contains_outbox_gauges(self, client):
        """Output contains protean_outbox_messages lines."""
        response = client.get("/metrics")
        body = response.text
        assert "protean_outbox_messages" in body or "protean_outbox_pending" in body

    def test_metrics_contains_broker_up(self, client):
        """Output contains protean_broker_up metric."""
        response = client.get("/metrics")
        body = response.text
        assert "protean_broker_up" in body

    def test_metrics_contains_stream_totals(self, client):
        """Output contains protean_stream_messages_total metric."""
        response = client.get("/metrics")
        body = response.text
        assert "protean_stream_messages_total" in body

    def test_metrics_help_and_type_annotations(self, client):
        """Each metric has # HELP and # TYPE lines."""
        response = client.get("/metrics")
        body = response.text
        # Check a few key metrics have HELP and TYPE
        assert "# HELP protean_broker_up" in body
        assert "# TYPE protean_broker_up gauge" in body
        assert "# HELP protean_stream_messages_total" in body
        assert "# TYPE protean_stream_messages_total gauge" in body

    def test_metrics_trailing_newline(self, client):
        """Output ends with newline (Prometheus requirement)."""
        response = client.get("/metrics")
        assert response.text.endswith("\n")

    def test_metrics_contains_broker_memory(self, client):
        """Output contains protean_broker_memory_bytes metric."""
        response = client.get("/metrics")
        body = response.text
        assert "protean_broker_memory_bytes" in body

    def test_metrics_contains_broker_clients(self, client):
        """Output contains protean_broker_connected_clients metric."""
        response = client.get("/metrics")
        body = response.text
        assert "protean_broker_connected_clients" in body

    def test_metrics_contains_broker_ops(self, client):
        """Output contains protean_broker_ops_per_sec metric."""
        response = client.get("/metrics")
        body = response.text
        assert "protean_broker_ops_per_sec" in body

    def test_metrics_contains_streams_count(self, client):
        """Output contains protean_streams_count metric."""
        response = client.get("/metrics")
        body = response.text
        assert "protean_streams_count" in body

    def test_metrics_contains_consumer_groups_count(self, client):
        """Output contains protean_consumer_groups_count metric."""
        response = client.get("/metrics")
        body = response.text
        assert "protean_consumer_groups_count" in body
