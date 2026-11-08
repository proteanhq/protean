"""Tests for Observatory Prometheus metrics endpoint.

Integration tests require a running Redis instance and are gated behind @pytest.mark.redis.
Tests for error paths use the real test domain with a fake raw Redis client,
so they need no infrastructure.
"""

import contextlib
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import redis
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory, metrics
from protean.server.observatory.metrics import _scrape_cache, _ScrapeCache


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

    def test_xinfo_consumers_exception_handled(self, test_domain, monkeypatch, caplog):
        """An error reading one group's consumers is logged and the scrape goes on."""
        fake = _fake_redis(groups=[{"name": "FailGroup", "pending": 0, "lag": 0}])
        fake.xinfo_consumers.side_effect = RuntimeError("connection reset")
        _use_fake_redis(test_domain, monkeypatch, fake)
        client = TestClient(Observatory(domains=[test_domain]).app)

        with caplog.at_level(logging.DEBUG, logger="protean.server.observatory"):
            response = client.get("/metrics")
        assert response.status_code == 200
        assert "protean_broker_up 1" in response.text
        messages = [r.getMessage() for r in caplog.records]
        assert (
            "Metrics: could not read consumers of group FailGroup "
            "on stream test::stream" in messages
        )

    def test_xinfo_groups_exception_handled(self, test_domain, monkeypatch, caplog):
        """An error reading a stream's groups is logged and the scrape goes on."""
        fake = _fake_redis()
        fake.xinfo_groups.side_effect = RuntimeError("timeout")
        _use_fake_redis(test_domain, monkeypatch, fake)
        client = TestClient(Observatory(domains=[test_domain]).app)

        with caplog.at_level(logging.DEBUG, logger="protean.server.observatory"):
            response = client.get("/metrics")
        assert response.status_code == 200
        assert "protean_broker_up 1" in response.text
        messages = [r.getMessage() for r in caplog.records]
        assert "Metrics: could not read groups of stream test::stream" in messages

    def test_stream_discovery_failure_handled(self, test_domain, monkeypatch, caplog):
        """A Redis error while listing streams is logged and yields no consumer metrics."""
        fake = _fake_redis(
            groups=[{"name": "TestGroup", "pending": 0, "lag": 0}],
            consumers_by_group={
                "TestGroup": [{"name": "TestConsumer", "pending": 1, "idle": 5}]
            },
        )
        fake.scan.side_effect = redis.ConnectionError("connection lost")
        _use_fake_redis(test_domain, monkeypatch, fake)
        client = TestClient(Observatory(domains=[test_domain]).app)

        with caplog.at_level(logging.DEBUG, logger="protean.server.observatory"):
            response = client.get("/metrics")
        assert response.status_code == 200
        assert "# HELP protean_consumer_pending" in response.text
        assert 'group="TestGroup"' not in response.text
        messages = [r.getMessage() for r in caplog.records]
        assert "Error discovering streams from Redis: connection lost" in messages


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

    def test_metrics_when_subscription_collection_fails(
        self, test_domain, monkeypatch, caplog
    ):
        """A failing subscription collection drops only the subscription section."""
        _use_fake_redis(test_domain, monkeypatch, _fake_redis())
        monkeypatch.setattr(metrics, "_collect_subscription_statuses", _fail)
        client = TestClient(Observatory(domains=[test_domain]).app)

        with caplog.at_level(logging.DEBUG, logger=metrics.__name__):
            response = client.get("/metrics")

        assert response.status_code == 200
        assert "protean_outbox_pending_count{" in response.text
        assert "protean_subscription_" not in response.text
        assert "Metrics: subscription status failed: collection failed" in (
            caplog.messages
        )

    def test_metrics_when_broker_pool_collection_fails(
        self, test_domain, monkeypatch, caplog
    ):
        """A failing broker pool collection drops only the broker pool section."""
        _use_fake_redis(test_domain, monkeypatch, _fake_redis())
        monkeypatch.setattr(metrics, "_collect_broker_pool_stats", _fail)
        client = TestClient(Observatory(domains=[test_domain]).app)

        with caplog.at_level(logging.DEBUG, logger=metrics.__name__):
            response = client.get("/metrics")

        assert response.status_code == 200
        assert "protean_outbox_pending_count{" in response.text
        assert "protean_broker_pool_active_connections" not in response.text
        assert "Metrics: broker pool stats failed: collection failed" in (
            caplog.messages
        )


def _fail(domains):
    raise RuntimeError("collection failed")


# --- The full hand-rolled text, with every section holding rows ---
#
# The test domain runs without OpenTelemetry, so /metrics serves the
# hand-rolled text. The fixture fakes the raw Redis client, the broker's
# health details and the shared collectors so that every section has rows
# with known, distinct values, and the test compares the whole body, line
# order included.


FULL_TEXT_LINES = [
    "# HELP protean_outbox_pending_count Current pending outbox messages",
    "# TYPE protean_outbox_pending_count gauge",
    'protean_outbox_pending_count{domain="Observatory Tests"} 0',
    "",
    "# HELP protean_broker_up Broker health (1=up, 0=down)",
    "# TYPE protean_broker_up gauge",
    "protean_broker_up 1",
    "",
    "# HELP protean_broker_memory_bytes Broker memory usage in bytes",
    "# TYPE protean_broker_memory_bytes gauge",
    "protean_broker_memory_bytes 2048",
    "",
    "# HELP protean_broker_connected_clients Number of connected broker clients",
    "# TYPE protean_broker_connected_clients gauge",
    "protean_broker_connected_clients 3",
    "",
    "# HELP protean_broker_ops_per_sec Broker operations per second",
    "# TYPE protean_broker_ops_per_sec gauge",
    "protean_broker_ops_per_sec 9",
    "",
    "# HELP protean_stream_messages_total Total messages in streams",
    "# TYPE protean_stream_messages_total gauge",
    "protean_stream_messages_total 11",
    "",
    "# HELP protean_stream_pending Pending (in-flight) messages",
    "# TYPE protean_stream_pending gauge",
    "protean_stream_pending 6",
    "",
    "# HELP protean_streams_count Number of active streams",
    "# TYPE protean_streams_count gauge",
    "protean_streams_count 1",
    "",
    "# HELP protean_consumer_groups_count Number of consumer groups",
    "# TYPE protean_consumer_groups_count gauge",
    "protean_consumer_groups_count 2",
    "",
    "# HELP protean_subscription_consumer_lag Messages behind stream head",
    "# TYPE protean_subscription_consumer_lag gauge",
    "",
    "# HELP protean_subscription_pending_messages Unacknowledged messages",
    "# TYPE protean_subscription_pending_messages gauge",
    "",
    "# HELP protean_subscription_dlq_depth Dead letter queue depth",
    "# TYPE protean_subscription_dlq_depth gauge",
    "",
    "# HELP protean_subscription_status Subscription health (1=ok, 0=not ok)",
    "# TYPE protean_subscription_status gauge",
    "",
    "# HELP protean_subscription_lag_seconds Seconds since a subscription's last processed position",
    "# TYPE protean_subscription_lag_seconds gauge",
    'protean_subscription_consumer_lag{domain="Observatory Tests",handler="OrderHandler",stream="orders::order",type="stream"} 7',
    'protean_subscription_lag_seconds{domain="Observatory Tests",handler="OrderHandler",stream="orders::order",type="stream"} 1.5',
    'protean_subscription_pending_messages{domain="Observatory Tests",handler="OrderHandler",stream="orders::order",type="stream"} 2',
    'protean_subscription_dlq_depth{domain="Observatory Tests",handler="OrderHandler",stream="orders::order",type="stream"} 1',
    'protean_subscription_status{domain="Observatory Tests",handler="OrderHandler",stream="orders::order",type="stream"} 1',
    'protean_subscription_pending_messages{domain="Observatory Tests",handler="ShipHandler",stream="ships::ship",type="event_store"} 0',
    'protean_subscription_dlq_depth{domain="Observatory Tests",handler="ShipHandler",stream="ships::ship",type="event_store"} 0',
    'protean_subscription_status{domain="Observatory Tests",handler="ShipHandler",stream="ships::ship",type="event_store"} 0',
    "",
    "# HELP protean_projection_staleness_seconds Seconds a projection is behind its source events",
    "# TYPE protean_projection_staleness_seconds gauge",
    'protean_projection_staleness_seconds{domain="Observatory Tests",projection="OrderSummary"} 12.5',
    "",
    "# HELP protean_consumer_pending Per-consumer unacknowledged messages",
    "# TYPE protean_consumer_pending gauge",
    "",
    "# HELP protean_consumer_idle_ms Per-consumer idle time in milliseconds",
    "# TYPE protean_consumer_idle_ms gauge",
    'protean_consumer_pending{consumer="worker-1",group="OrderHandler",stream="orders::order"} 4',
    'protean_consumer_idle_ms{consumer="worker-1",group="OrderHandler",stream="orders::order"} 1500',
    'protean_consumer_pending{consumer="worker-2",group="OrderHandler",stream="orders::order"} 0',
    'protean_consumer_idle_ms{consumer="worker-2",group="OrderHandler",stream="orders::order"} 0',
    "",
    "# HELP protean_db_pool_size Database connection pool size",
    "# TYPE protean_db_pool_size gauge",
    "",
    "# HELP protean_db_pool_checked_out Checked out database connections",
    "# TYPE protean_db_pool_checked_out gauge",
    "",
    "# HELP protean_db_pool_overflow Overflow database connections",
    "# TYPE protean_db_pool_overflow gauge",
    "",
    "# HELP protean_db_pool_checked_in Available database connections",
    "# TYPE protean_db_pool_checked_in gauge",
    'protean_db_pool_size{provider_name="default",database_type="POSTGRESQL"} 5',
    'protean_db_pool_checked_out{provider_name="default",database_type="POSTGRESQL"} 2',
    'protean_db_pool_overflow{provider_name="default",database_type="POSTGRESQL"} 1',
    'protean_db_pool_checked_in{provider_name="default",database_type="POSTGRESQL"} 4',
    "",
    "# HELP protean_broker_pool_active_connections Active broker pool connections",
    "# TYPE protean_broker_pool_active_connections gauge",
    'protean_broker_pool_active_connections{broker_name="default"} 3',
]


HEALTH_DETAILS = {
    "healthy": True,
    "used_memory": 2048,
    "connected_clients": 3,
    "instantaneous_ops_per_sec": 9,
    "message_counts": {"total_messages": 11, "in_flight": 6},
    "streams": {"count": 1},
    "consumer_groups": {"count": 2},
}


def _fake_redis_with_consumers():
    fake = MagicMock()
    fake.ping.return_value = True
    fake.scan.return_value = (0, [b"orders::order"])
    fake.xinfo_groups.return_value = [
        {"name": "OrderHandler", "pending": 4, "lag": 2},
        "not-a-dict",
        {"name": ""},
    ]
    consumers = {
        ("orders::order", "OrderHandler"): [
            {"name": "worker-1", "pending": 4, "idle": 1500},
            {b"name": b"worker-2", b"pending": None, b"idle": 0},
            "not-a-dict",
        ]
    }
    fake.xinfo_consumers.side_effect = lambda name, group: consumers.get(
        (name, group), []
    )
    fake.connection_pool = redis.ConnectionPool()
    return fake


@pytest.fixture
def full_text_client(test_domain, monkeypatch):
    broker = test_domain.brokers["default"]
    monkeypatch.setattr(broker, "redis_instance", _fake_redis_with_consumers())
    monkeypatch.setattr(broker, "_health_stats", lambda: dict(HEALTH_DETAILS))
    subscriptions = [
        SimpleNamespace(
            handler_name="OrderHandler",
            stream_category="orders::order",
            subscription_type="stream",
            lag=7,
            lag_seconds=1.5,
            pending=2,
            dlq_depth=1,
            status="ok",
        ),
        SimpleNamespace(
            handler_name="ShipHandler",
            stream_category="ships::ship",
            subscription_type="event_store",
            lag=None,
            lag_seconds=None,
            pending=0,
            dlq_depth=0,
            status="lagging",
        ),
    ]
    projections = [
        SimpleNamespace(projection_name="OrderSummary", staleness_seconds=12.5),
        SimpleNamespace(projection_name="ShipSummary", staleness_seconds=None),
    ]
    pools = [
        (
            "default",
            "POSTGRESQL",
            {"size": 5, "checked_out": 2, "overflow": 1, "checked_in": 4},
        ),
    ]
    broker_pools = [("default", 3, 2, 10)]
    # The subscription and projection fakes return rows only for the domains
    # the Observatory serves. The pool fakes return fixed rows for any
    # non-empty domain list.
    monkeypatch.setattr(
        metrics,
        "_collect_subscription_statuses",
        lambda domains: [(d, s) for d in domains for s in subscriptions],
    )
    monkeypatch.setattr(
        metrics,
        "_collect_projection_statuses",
        lambda domains: [(d, p) for d in domains for p in projections],
    )
    monkeypatch.setattr(
        metrics, "_collect_pool_stats", lambda domains: pools if domains else []
    )
    monkeypatch.setattr(
        metrics,
        "_collect_broker_pool_stats",
        lambda domains: broker_pools if domains else [],
    )
    return TestClient(Observatory(domains=[test_domain]).app)


def test_hand_rolled_metrics_full_text(full_text_client):
    response = full_text_client.get("/metrics")

    assert response.status_code == 200
    assert response.text.split("\n") == [*FULL_TEXT_LINES, ""]


@pytest.mark.parametrize(
    "connected, healthy, expected",
    [(True, True, 1), (True, False, 0), (False, True, 0), (False, False, 0)],
)
def test_broker_up_needs_a_connected_and_healthy_broker(connected, healthy, expected):
    lines: list[str] = []

    metrics._append_broker_health_lines(
        lines, {"connected": connected, "details": {"healthy": healthy}}
    )

    assert f"protean_broker_up {expected}" in lines


# --- The shared pool collectors read the domain's own adapters ---


def test_pool_stats_list_each_provider_that_reports_a_pool(test_domain, monkeypatch):
    provider = test_domain.providers["default"]
    monkeypatch.setattr(provider, "pool_stats", lambda: {"size": 5, "checked_out": 2})

    assert metrics._collect_pool_stats([test_domain]) == [
        ("default", provider.__database__, {"size": 5, "checked_out": 2})
    ]


def test_pool_stats_skip_a_provider_without_a_pool(test_domain):
    assert metrics._collect_pool_stats([test_domain]) == []


def test_broker_pool_stats_read_the_redis_connection_pool(test_domain, monkeypatch):
    pool = redis.ConnectionPool(max_connections=10)
    pool._created_connections = 3
    pool._available_connections = [object()]
    fake = MagicMock()
    fake.connection_pool = pool
    monkeypatch.setattr(test_domain.brokers["default"], "redis_instance", fake)

    assert metrics._collect_broker_pool_stats([test_domain]) == [("default", 2, 1, 10)]
