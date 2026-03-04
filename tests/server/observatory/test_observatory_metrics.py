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


@pytest.mark.redis
class TestPerConsumerMetrics:
    """Integration tests for per-consumer Prometheus metrics."""

    def test_consumer_metrics_appear_after_xreadgroup(self, test_domain):
        """Per-consumer metrics appear once a consumer reads from a stream."""
        broker = test_domain.brokers.get("default")
        redis_conn = broker.redis_instance

        stream = "metrics-test::consumer-gauges"
        group = "MetricsConsumerGroup"
        consumer_name = "MetricsHandler-metricshost-9876-aabbcc"

        redis_conn.xadd(stream, {"data": "metrics-msg"})
        try:
            redis_conn.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception:
            pass
        redis_conn.xreadgroup(group, consumer_name, {stream: ">"}, count=1)

        observatory = Observatory(domains=[test_domain])
        client = TestClient(observatory.app)
        response = client.get("/metrics")
        body = response.text

        assert "protean_consumer_pending" in body
        assert "protean_consumer_idle_ms" in body
        # Check labels contain our consumer/group/stream
        assert consumer_name in body
        assert group in body
        assert stream in body

    def test_consumer_metrics_help_and_type(self, test_domain):
        """Per-consumer metrics have HELP and TYPE annotations."""
        broker = test_domain.brokers.get("default")
        redis_conn = broker.redis_instance

        stream = "metrics-test::consumer-help"
        group = "HelpTestGroup"
        consumer = "HelpHandler-host-1-abc"

        redis_conn.xadd(stream, {"data": "msg"})
        try:
            redis_conn.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception:
            pass
        redis_conn.xreadgroup(group, consumer, {stream: ">"}, count=1)

        observatory = Observatory(domains=[test_domain])
        client = TestClient(observatory.app)
        response = client.get("/metrics")
        body = response.text

        assert "# HELP protean_consumer_pending" in body
        assert "# TYPE protean_consumer_pending gauge" in body
        assert "# HELP protean_consumer_idle_ms" in body
        assert "# TYPE protean_consumer_idle_ms gauge" in body


class TestConsumerMetricsWithMockRedis:
    """Tests for per-consumer metrics with mock Redis (lines 230-272)."""

    def _make_client_with_mock_redis(self, groups, consumers_by_group=None):
        """Create a TestClient with mock Redis returning specified groups/consumers."""
        mock_domain = _make_mock_domain("consumer-test")

        mock_redis = MagicMock()
        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis
        mock_broker.health_stats.return_value = {
            "connected": True,
            "details": {"healthy": True, "used_memory": 1024},
        }
        mock_domain.brokers.get.return_value = mock_broker

        # Stream discovery returns one stream
        mock_redis.scan.return_value = (0, [b"test::stream"])

        # xinfo_groups returns the provided groups
        mock_redis.xinfo_groups.return_value = groups

        # xinfo_consumers returns per-group consumers
        if consumers_by_group:

            def xinfo_consumers_side_effect(stream, group):
                return consumers_by_group.get(group, [])

            mock_redis.xinfo_consumers.side_effect = xinfo_consumers_side_effect
        else:
            mock_redis.xinfo_consumers.return_value = []

        # outbox
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {}
        mock_domain._get_outbox_repo.return_value = mock_outbox

        observatory = Observatory(domains=[mock_domain])
        return TestClient(observatory.app)

    def test_consumer_metrics_with_string_keys(self):
        """Consumer metrics correctly parse groups/consumers with string keys."""
        groups = [{"name": "TestGroup", "pending": 5, "lag": 10}]
        consumers = {
            "TestGroup": [{"name": "TestConsumer", "pending": 3, "idle": 1000}]
        }
        client = self._make_client_with_mock_redis(groups, consumers)

        response = client.get("/metrics")
        body = response.text
        assert response.status_code == 200
        assert 'consumer="TestConsumer"' in body
        assert 'group="TestGroup"' in body
        assert "protean_consumer_pending" in body
        assert "protean_consumer_idle_ms" in body

    def test_consumer_metrics_with_bytes_keys(self):
        """Consumer metrics correctly decode bytes keys from Redis."""
        groups = [{b"name": b"ByteGroup", b"pending": 2, b"lag": 5}]
        consumers = {
            "ByteGroup": [{b"name": b"ByteConsumer", b"pending": 1, b"idle": 500}]
        }
        client = self._make_client_with_mock_redis(groups, consumers)

        response = client.get("/metrics")
        body = response.text
        assert response.status_code == 200
        assert 'consumer="ByteConsumer"' in body
        assert 'group="ByteGroup"' in body

    def test_non_dict_group_skipped(self):
        """Non-dict group entries are silently skipped."""
        groups = ["not-a-dict", {"name": "ValidGroup", "pending": 0, "lag": 0}]
        consumers = {"ValidGroup": [{"name": "Consumer1", "pending": 0, "idle": 0}]}
        client = self._make_client_with_mock_redis(groups, consumers)

        response = client.get("/metrics")
        body = response.text
        assert response.status_code == 200
        assert 'group="ValidGroup"' in body

    def test_empty_group_name_skipped(self):
        """Groups with empty/None name are skipped."""
        groups = [
            {"name": None, "pending": 0, "lag": 0},
            {"name": "GoodGroup", "pending": 0, "lag": 0},
        ]
        consumers = {"GoodGroup": [{"name": "Consumer1", "pending": 0, "idle": 0}]}
        client = self._make_client_with_mock_redis(groups, consumers)

        response = client.get("/metrics")
        body = response.text
        assert response.status_code == 200
        assert 'group="GoodGroup"' in body

    def test_non_dict_consumer_skipped(self):
        """Non-dict consumer entries are silently skipped."""
        groups = [{"name": "Group1", "pending": 0, "lag": 0}]
        consumers = {
            "Group1": ["not-a-dict", {"name": "ValidConsumer", "pending": 0, "idle": 0}]
        }
        client = self._make_client_with_mock_redis(groups, consumers)

        response = client.get("/metrics")
        body = response.text
        assert response.status_code == 200
        assert 'consumer="ValidConsumer"' in body

    def test_xinfo_consumers_exception_handled(self):
        """Exception in xinfo_consumers does not crash the metrics endpoint."""
        groups = [{"name": "FailGroup", "pending": 0, "lag": 0}]
        mock_domain = _make_mock_domain("exc-test")
        mock_redis = MagicMock()
        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis
        mock_broker.health_stats.return_value = {
            "connected": True,
            "details": {"healthy": True, "used_memory": 0},
        }
        mock_domain.brokers.get.return_value = mock_broker
        mock_redis.scan.return_value = (0, [b"test::stream"])
        mock_redis.xinfo_groups.return_value = groups
        mock_redis.xinfo_consumers.side_effect = RuntimeError("connection reset")
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {}
        mock_domain._get_outbox_repo.return_value = mock_outbox

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/metrics")
        assert response.status_code == 200

    def test_xinfo_groups_exception_handled(self):
        """Exception in xinfo_groups does not crash the metrics endpoint."""
        mock_domain = _make_mock_domain("exc-test")
        mock_redis = MagicMock()
        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis
        mock_broker.health_stats.return_value = {
            "connected": True,
            "details": {"healthy": True, "used_memory": 0},
        }
        mock_domain.brokers.get.return_value = mock_broker
        mock_redis.scan.return_value = (0, [b"test::stream"])
        mock_redis.xinfo_groups.side_effect = RuntimeError("timeout")
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {}
        mock_domain._get_outbox_repo.return_value = mock_outbox

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        response = client.get("/metrics")
        assert response.status_code == 200
        # Should still have broker/outbox metrics
        assert "protean_broker_up" in response.text


class TestConsumerMetricsOuterException:
    """Test the outer exception handler for consumer metrics (lines 271-272)."""

    def test_consumer_metrics_handles_get_redis_exception(self):
        """Metrics endpoint handles _get_redis exception in consumer section."""
        from unittest.mock import patch

        mock_domain = _make_mock_domain("redis-fail")
        mock_broker = MagicMock()
        mock_broker.health_stats.return_value = {
            "connected": True,
            "details": {"healthy": True, "used_memory": 1024},
        }
        mock_domain.brokers.get.return_value = mock_broker
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {}
        mock_domain._get_outbox_repo.return_value = mock_outbox

        observatory = Observatory(domains=[mock_domain])
        client = TestClient(observatory.app)

        # Patch _get_redis in the api module (where metrics.py imports it from)
        with patch(
            "protean.server.observatory.api._get_redis",
            side_effect=RuntimeError("import boom"),
        ):
            response = client.get("/metrics")

        assert response.status_code == 200
        body = response.text
        # Broker/outbox metrics should still be present
        assert "protean_broker_up" in body


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
