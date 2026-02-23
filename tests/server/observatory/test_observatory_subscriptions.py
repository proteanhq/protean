"""Tests for Observatory /api/subscriptions endpoint and Prometheus metrics.

Integration tests require a running Redis instance and are gated behind
@pytest.mark.redis. Unit tests for error paths use mock domains and need
no infrastructure.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory
from protean.server.subscription_status import SubscriptionStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_domain(name: str = "mock-domain") -> MagicMock:
    """Create a mock Domain for unit tests."""
    mock = MagicMock()
    mock.name = name
    mock.domain_context.return_value.__enter__ = MagicMock(return_value=None)
    mock.domain_context.return_value.__exit__ = MagicMock(return_value=False)
    return mock


def _ok_status(
    handler_name: str = "TestHandler",
    subscription_type: str = "stream",
    stream: str = "test",
) -> SubscriptionStatus:
    return SubscriptionStatus(
        name=f"sub-{handler_name.lower()}",
        handler_name=handler_name,
        subscription_type=subscription_type,
        stream_category=stream,
        lag=0,
        pending=0,
        current_position="10",
        head_position="10",
        status="ok",
        consumer_count=1,
        dlq_depth=0,
    )


def _lagging_status(
    handler_name: str = "SlowHandler",
    lag: int = 42,
    pending: int = 3,
    dlq: int = 1,
) -> SubscriptionStatus:
    return SubscriptionStatus(
        name=f"sub-{handler_name.lower()}",
        handler_name=handler_name,
        subscription_type="stream",
        stream_category="order",
        lag=lag,
        pending=pending,
        current_position="100",
        head_position="142",
        status="lagging",
        consumer_count=2,
        dlq_depth=dlq,
    )


# ---------------------------------------------------------------------------
# Integration tests (require Redis)
# ---------------------------------------------------------------------------


@pytest.fixture
def observatory(test_domain):
    """Observatory backed by a real domain."""
    return Observatory(domains=[test_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


@pytest.mark.redis
class TestSubscriptionsEndpoint:
    def test_returns_200(self, client):
        """GET /api/subscriptions returns 200."""
        response = client.get("/api/subscriptions")
        assert response.status_code == 200

    def test_response_keyed_by_domain(self, client, test_domain):
        """Response is keyed by domain name."""
        response = client.get("/api/subscriptions")
        data = response.json()
        assert test_domain.name in data

    def test_domain_entry_has_status(self, client, test_domain):
        """Each domain entry has a status field."""
        response = client.get("/api/subscriptions")
        data = response.json()
        assert "status" in data[test_domain.name]

    def test_domain_entry_has_summary(self, client, test_domain):
        """Each domain entry has a summary with counts."""
        response = client.get("/api/subscriptions")
        data = response.json()
        domain_data = data[test_domain.name]
        if domain_data["status"] == "ok":
            assert "summary" in domain_data
            assert "total" in domain_data["summary"]


# ---------------------------------------------------------------------------
# Unit tests (no infrastructure needed)
# ---------------------------------------------------------------------------


class TestSubscriptionsEndpointUnit:
    def test_returns_subscription_list(self):
        """Endpoint returns subscriptions with lag data."""
        mock_domain = _make_mock_domain("test-domain")

        statuses = [_ok_status(), _lagging_status()]

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=statuses,
        ):
            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)
            response = client.get("/api/subscriptions")

        assert response.status_code == 200
        data = response.json()
        assert "test-domain" in data

        domain_data = data["test-domain"]
        assert domain_data["status"] == "ok"
        assert len(domain_data["subscriptions"]) == 2

        summary = domain_data["summary"]
        assert summary["total"] == 2
        assert summary["ok"] == 1
        assert summary["lagging"] == 1
        assert summary["total_lag"] == 42
        assert summary["total_pending"] == 3
        assert summary["total_dlq"] == 1

    def test_empty_domain_returns_empty_list(self):
        """Domain with no handlers returns empty subscriptions list."""
        mock_domain = _make_mock_domain("empty-domain")

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=[],
        ):
            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)
            response = client.get("/api/subscriptions")

        data = response.json()
        assert data["empty-domain"]["subscriptions"] == []
        assert data["empty-domain"]["summary"]["total"] == 0

    def test_handles_collection_error_gracefully(self):
        """Returns error status when subscription collection fails."""
        mock_domain = _make_mock_domain("broken-domain")

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            side_effect=RuntimeError("collection failed"),
        ):
            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)
            response = client.get("/api/subscriptions")

        data = response.json()
        assert data["broken-domain"]["status"] == "error"


# ---------------------------------------------------------------------------
# Prometheus metrics tests
# ---------------------------------------------------------------------------


class TestSubscriptionsMetrics:
    def test_metrics_contains_subscription_lag_help(self):
        """Prometheus output contains subscription lag HELP/TYPE."""
        mock_domain = _make_mock_domain("metric-domain")

        statuses = [_lagging_status()]

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=statuses,
        ):
            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)
            response = client.get("/metrics")

        body = response.text
        assert "# HELP protean_subscription_lag" in body
        assert "# TYPE protean_subscription_lag gauge" in body

    def test_metrics_contains_subscription_lag_values(self):
        """Prometheus output contains per-subscription lag values."""
        mock_domain = _make_mock_domain("metric-domain")

        statuses = [_lagging_status(handler_name="OrderHandler", lag=42)]

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=statuses,
        ):
            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)
            response = client.get("/metrics")

        body = response.text
        assert "protean_subscription_lag" in body
        assert "42" in body

    def test_metrics_contains_subscription_pending(self):
        """Prometheus output includes protean_subscription_pending."""
        mock_domain = _make_mock_domain("metric-domain")

        statuses = [_lagging_status()]

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=statuses,
        ):
            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)
            response = client.get("/metrics")

        body = response.text
        assert "protean_subscription_pending" in body

    def test_metrics_contains_subscription_dlq_depth(self):
        """Prometheus output includes protean_subscription_dlq_depth."""
        mock_domain = _make_mock_domain("metric-domain")

        statuses = [_lagging_status()]

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=statuses,
        ):
            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)
            response = client.get("/metrics")

        body = response.text
        assert "protean_subscription_dlq_depth" in body

    def test_metrics_contains_subscription_status_gauge(self):
        """Prometheus output includes protean_subscription_status."""
        mock_domain = _make_mock_domain("metric-domain")

        statuses = [_ok_status()]

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=statuses,
        ):
            observatory = Observatory(domains=[mock_domain])
            client = TestClient(observatory.app)
            response = client.get("/metrics")

        body = response.text
        assert "protean_subscription_status" in body
