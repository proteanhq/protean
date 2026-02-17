"""Tests for Observatory Prometheus metrics endpoint.

Integration tests require a running Redis instance and are gated behind @pytest.mark.redis.
Unit tests for error paths use mock domains and need no infrastructure.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory


@pytest.fixture
def client(test_domain):
    observatory = Observatory(domains=[test_domain])
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


# --- Unit tests for error paths (no Redis needed) ---


def _make_mock_domain(name: str = "mock-domain") -> MagicMock:
    """Create a mock Domain for metrics error-path tests."""
    mock = MagicMock()
    mock.name = name
    mock.domain_context.return_value.__enter__ = MagicMock(return_value=None)
    mock.domain_context.return_value.__exit__ = MagicMock(return_value=False)
    return mock


class TestMetricsErrorPaths:
    def test_metrics_when_outbox_query_fails(self):
        """Metrics endpoint handles outbox query exceptions gracefully."""
        mock_domain = _make_mock_domain("failing-domain")
        mock_domain._get_outbox_repo.side_effect = RuntimeError("outbox error")
        # Broker works fine
        mock_broker = MagicMock()
        mock_broker.health_stats.return_value = {
            "connected": True,
            "details": {"healthy": True, "used_memory": 1024, "connected_clients": 2},
        }
        mock_domain.brokers.get.return_value = mock_broker

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)
        response = client.get("/metrics")

        assert response.status_code == 200
        body = response.text
        # Should still have broker metrics even though outbox failed
        assert "protean_broker_up" in body

    def test_metrics_when_broker_query_fails(self):
        """Metrics endpoint handles broker query exceptions gracefully."""
        mock_domain = _make_mock_domain("failing-domain")
        # Outbox works fine
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {"PENDING": 5}
        mock_domain._get_outbox_repo.return_value = mock_outbox
        # Broker raises
        mock_domain.brokers.get.side_effect = RuntimeError("broker down")

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)
        response = client.get("/metrics")

        assert response.status_code == 200
        body = response.text
        # Outbox metrics should still be present
        assert "protean_outbox_messages" in body

    def test_metrics_when_broker_is_none(self):
        """Metrics endpoint handles missing broker gracefully."""
        mock_domain = _make_mock_domain("no-broker")
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {}
        mock_domain._get_outbox_repo.return_value = mock_outbox
        mock_domain.brokers.get.return_value = None

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)
        response = client.get("/metrics")

        assert response.status_code == 200
        body = response.text
        # Should have outbox HELP/TYPE headers but no broker metrics
        assert "protean_outbox_pending" in body
        assert "protean_broker_up" not in body
