"""Tests for Observatory Prometheus metrics endpoint.

Integration tests require a running Redis instance and are gated behind @pytest.mark.redis.
Tests for error paths use the real test domain with a fake raw Redis client,
so they need no infrastructure.
"""

import contextlib
from unittest.mock import MagicMock, patch

import pytest
import redis
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory
from protean.server.observatory.metrics import _scrape_cache, _ScrapeCache
from protean.server.observatory.routes import domain as domain_routes


@pytest.fixture(autouse=True)
def _clear_scrape_cache():
    """The metrics module caches collected data for a short time between scrapes."""
    _scrape_cache.clear()
    yield
    _scrape_cache.clear()


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
        """Output contains protean_outbox_pending_count lines."""
        response = client.get("/metrics")
        body = response.text
        assert "protean_outbox_pending_count" in body

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


# --- Error paths, with a fake raw Redis client (no Redis server needed) ---


def _fake_redis(groups=(), consumers_by_group=None, used_memory=1024):
    """A fake raw Redis client holding one stream, ``test::stream``.

    The core test lane has no Redis server, so only the raw client under the
    real Redis broker is faked.
    """
    consumers_by_group = consumers_by_group or {}
    fake = MagicMock()
    fake.ping.return_value = True
    fake.info.return_value = {"used_memory": used_memory, "connected_clients": 2}
    fake.scan.return_value = (0, [b"test::stream"])
    fake.xinfo_groups.return_value = list(groups)
    fake.xinfo_consumers.side_effect = lambda stream, group: consumers_by_group.get(
        group, []
    )
    # A real pool object; it opens no connection until a command runs.
    fake.connection_pool = redis.ConnectionPool()
    return fake


def _use_fake_redis(domain, monkeypatch, fake):
    monkeypatch.setattr(domain.brokers["default"], "redis_instance", fake)


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
        with contextlib.suppress(Exception):
            redis_conn.xgroup_create(stream, group, id="0", mkstream=True)
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
        with contextlib.suppress(Exception):
            redis_conn.xgroup_create(stream, group, id="0", mkstream=True)
        redis_conn.xreadgroup(group, consumer, {stream: ">"}, count=1)

        observatory = Observatory(domains=[test_domain])
        client = TestClient(observatory.app)
        response = client.get("/metrics")
        body = response.text

        assert "# HELP protean_consumer_pending" in body
        assert "# TYPE protean_consumer_pending gauge" in body
        assert "# HELP protean_consumer_idle_ms" in body
        assert "# TYPE protean_consumer_idle_ms gauge" in body


class TestConsumerMetricsWithFakeRedis:
    """Per-consumer metrics read from a fake raw Redis client."""

    def _make_client(self, test_domain, monkeypatch, groups, consumers_by_group=None):
        _use_fake_redis(
            test_domain, monkeypatch, _fake_redis(groups, consumers_by_group)
        )
        observatory = Observatory(domains=[test_domain])
        return TestClient(observatory.app)

    def test_consumer_metrics_with_string_keys(self, test_domain, monkeypatch):
        """Consumer metrics correctly parse groups/consumers with string keys."""
        groups = [{"name": "TestGroup", "pending": 5, "lag": 10}]
        consumers = {
            "TestGroup": [{"name": "TestConsumer", "pending": 3, "idle": 1000}]
        }
        client = self._make_client(test_domain, monkeypatch, groups, consumers)

        response = client.get("/metrics")
        body = response.text
        assert response.status_code == 200
        assert 'consumer="TestConsumer"' in body
        assert 'group="TestGroup"' in body
        assert "protean_consumer_pending" in body
        assert "protean_consumer_idle_ms" in body
        labels = 'consumer="TestConsumer",group="TestGroup",stream="test::stream"'
        assert f"protean_consumer_pending{{{labels}}} 3" in body
        assert f"protean_consumer_idle_ms{{{labels}}} 1000" in body

    def test_consumer_metrics_with_bytes_keys(self, test_domain, monkeypatch):
        """Consumer metrics correctly decode bytes keys from Redis."""
        groups = [{b"name": b"ByteGroup", b"pending": 2, b"lag": 5}]
        consumers = {
            "ByteGroup": [{b"name": b"ByteConsumer", b"pending": 1, b"idle": 500}]
        }
        client = self._make_client(test_domain, monkeypatch, groups, consumers)

        response = client.get("/metrics")
        body = response.text
        assert response.status_code == 200
        assert 'consumer="ByteConsumer"' in body
        assert 'group="ByteGroup"' in body

    def test_non_dict_group_skipped(self, test_domain, monkeypatch):
        """Non-dict group entries are silently skipped."""
        groups = ["not-a-dict", {"name": "ValidGroup", "pending": 0, "lag": 0}]
        consumers = {"ValidGroup": [{"name": "Consumer1", "pending": 0, "idle": 0}]}
        client = self._make_client(test_domain, monkeypatch, groups, consumers)

        response = client.get("/metrics")
        body = response.text
        assert response.status_code == 200
        assert 'group="ValidGroup"' in body

    def test_empty_group_name_skipped(self, test_domain, monkeypatch):
        """Groups with empty/None name are skipped."""
        groups = [
            {"name": None, "pending": 0, "lag": 0},
            {"name": "GoodGroup", "pending": 0, "lag": 0},
        ]
        consumers = {"GoodGroup": [{"name": "Consumer1", "pending": 0, "idle": 0}]}
        client = self._make_client(test_domain, monkeypatch, groups, consumers)

        response = client.get("/metrics")
        body = response.text
        assert response.status_code == 200
        assert 'group="GoodGroup"' in body

    def test_non_dict_consumer_skipped(self, test_domain, monkeypatch):
        """Non-dict consumer entries are silently skipped."""
        groups = [{"name": "Group1", "pending": 0, "lag": 0}]
        consumers = {
            "Group1": ["not-a-dict", {"name": "ValidConsumer", "pending": 0, "idle": 0}]
        }
        client = self._make_client(test_domain, monkeypatch, groups, consumers)

        response = client.get("/metrics")
        body = response.text
        assert response.status_code == 200
        assert 'consumer="ValidConsumer"' in body

    def test_xinfo_consumers_exception_handled(self, test_domain, monkeypatch):
        """Exception in xinfo_consumers does not crash the metrics endpoint."""
        fake = _fake_redis(groups=[{"name": "FailGroup", "pending": 0, "lag": 0}])
        fake.xinfo_consumers.side_effect = RuntimeError("connection reset")
        _use_fake_redis(test_domain, monkeypatch, fake)
        client = TestClient(Observatory(domains=[test_domain]).app)

        response = client.get("/metrics")
        assert response.status_code == 200
        assert 'group="FailGroup"' not in response.text
        assert "protean_broker_up 1" in response.text

    def test_xinfo_groups_exception_handled(self, test_domain, monkeypatch):
        """Exception in xinfo_groups does not crash the metrics endpoint."""
        fake = _fake_redis()
        fake.xinfo_groups.side_effect = RuntimeError("timeout")
        _use_fake_redis(test_domain, monkeypatch, fake)
        client = TestClient(Observatory(domains=[test_domain]).app)

        response = client.get("/metrics")
        assert response.status_code == 200
        # Should still have broker/outbox metrics
        assert "protean_broker_up" in response.text

    def test_stream_discovery_failure_handled(self, test_domain, monkeypatch):
        """A Redis error while listing streams yields no consumer metrics."""
        fake = _fake_redis(groups=[{"name": "TestGroup", "pending": 0, "lag": 0}])
        fake.scan.side_effect = redis.ConnectionError("connection lost")
        _use_fake_redis(test_domain, monkeypatch, fake)
        client = TestClient(Observatory(domains=[test_domain]).app)

        response = client.get("/metrics")
        assert response.status_code == 200
        assert "# HELP protean_consumer_pending" in response.text
        assert 'group="TestGroup"' not in response.text


class TestScrapeCache:
    def test_reuses_value_within_ttl(self):
        cache = _ScrapeCache(ttl_seconds=60)
        calls = []

        def collector():
            calls.append(1)
            return len(calls)

        assert cache.get("key", collector) == 1
        assert cache.get("key", collector) == 1
        assert len(calls) == 1

    def test_collects_again_after_ttl(self):
        cache = _ScrapeCache(ttl_seconds=0)
        calls = []

        def collector():
            calls.append(1)
            return len(calls)

        assert cache.get("key", collector) == 1
        assert cache.get("key", collector) == 2

    def test_clear_discards_cached_values(self):
        cache = _ScrapeCache(ttl_seconds=60)
        cache.get("key", lambda: "old")
        cache.clear()
        assert cache.get("key", lambda: "new") == "new"


class TestConsumerMetricsOuterException:
    """A failure to reach Redis for consumer metrics leaves the other metrics."""

    def test_consumer_metrics_handles_get_redis_exception(
        self, test_domain, monkeypatch
    ):
        """Metrics endpoint handles _get_redis exception in consumer section."""
        _use_fake_redis(test_domain, monkeypatch, _fake_redis())
        client = TestClient(Observatory(domains=[test_domain]).app)

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
        assert "# HELP protean_consumer_pending" not in body


class TestMetricsErrorPaths:
    def test_metrics_when_outbox_query_fails(self, test_domain, monkeypatch):
        """Metrics endpoint handles outbox query exceptions gracefully."""
        # Broker works fine
        _use_fake_redis(test_domain, monkeypatch, _fake_redis())
        client = TestClient(Observatory(domains=[test_domain]).app)

        with patch.object(
            test_domain, "_get_outbox_repo", side_effect=RuntimeError("outbox error")
        ):
            response = client.get("/metrics")

        assert response.status_code == 200
        body = response.text
        # Should still have broker metrics even though outbox failed
        assert "protean_broker_up" in body
        assert "protean_outbox_pending_count{" not in body

    def test_metrics_when_broker_query_fails(self, test_domain):
        """Metrics endpoint handles broker query exceptions gracefully."""
        client = TestClient(Observatory(domains=[test_domain]).app)

        # Broker raises; the real memory outbox still answers
        with patch.object(
            test_domain.brokers, "get", side_effect=RuntimeError("broker down")
        ):
            response = client.get("/metrics")

        assert response.status_code == 200
        body = response.text
        # Outbox metrics should still be present
        assert "protean_outbox_pending_count" in body
        assert f'protean_outbox_pending_count{{domain="{test_domain.name}"}} 0' in body
        assert "protean_broker_up" not in body

    def test_metrics_when_broker_is_none(self, test_domain):
        """Metrics endpoint handles missing broker gracefully."""
        del test_domain.brokers["default"]
        client = TestClient(Observatory(domains=[test_domain]).app)

        response = client.get("/metrics")

        assert response.status_code == 200
        body = response.text
        # Should have outbox HELP/TYPE headers but no broker metrics
        assert "protean_outbox_pending_count" in body
        assert "protean_broker_up" not in body

    def test_metrics_served_when_domain_ir_cannot_be_built(
        self, test_domain, monkeypatch
    ):
        """The Observatory still serves metrics when the domain IR fails to build."""

        def _raise(self):
            raise RuntimeError("boom")

        monkeypatch.setattr(domain_routes.IRBuilder, "build", _raise)
        client = TestClient(Observatory(domains=[test_domain]).app)

        response = client.get("/metrics")
        assert response.status_code == 200
        assert client.get("/api/domain/ir").status_code == 503
        assert f'protean_outbox_pending_count{{domain="{test_domain.name}"}} 0' in (
            response.text
        )
