"""Tests for connection pool and backpressure OTEL metrics.

Verifies that:
- ``BaseProvider.pool_stats()`` returns ``{}`` by default.
- ``SAProvider.pool_stats()`` reads live pool counters from the engine.
- Observable gauges for DB pool metrics produce correct measurements.
- Observable gauges for broker pool metrics produce correct measurements.
- Backpressure gauges (outbox, subscription lag/pending) use the correct
  OTEL-style names and share the collection helper.
- The hand-rolled metrics fallback includes pool and backpressure metrics.
- Everything is no-op when OTEL is not configured.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.port.provider import BaseProvider
from protean.server.observatory.metrics import (
    _collect_broker_pool_stats,
    _collect_pool_stats,
    _collect_subscription_statuses,
    _hand_rolled_metrics,
    _register_infrastructure_gauges,
    _scrape_cache,
)
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.mixins import handle
from protean.utils.outbox import Outbox

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_telemetry_in_memory(domain):
    """Set up in-memory OTEL metric reader on the domain for testing."""
    resource = Resource.create({"service.name": domain.normalized_name})
    metric_reader = InMemoryMetricReader()
    meter_provider = SDKMeterProvider(resource=resource, metric_readers=[metric_reader])

    domain._otel_meter_provider = meter_provider
    domain._otel_init_attempted = True

    return metric_reader


def _get_metric(metric_reader, name: str):
    """Find a metric by name from the InMemoryMetricReader."""
    data = metric_reader.get_metrics_data()
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == name:
                    return metric
    return None


def _get_metric_data_points(metric_reader, name: str) -> list:
    """Get all data points for a metric by name."""
    metric = _get_metric(metric_reader, name)
    if metric is None:
        return []
    return list(metric.data.data_points)


_GAUGES_KEY = "_otel_infra_gauges_registered"


def _clean_gauges(domain):
    """Remove gauge registration sentinel from domain."""
    if hasattr(domain, _GAUGES_KEY):
        delattr(domain, _GAUGES_KEY)


@pytest.fixture(autouse=True)
def _clear_scrape_cache():
    _scrape_cache.clear()
    yield
    _scrape_cache.clear()


@pytest.fixture
def sqlite_domain(tmp_path):
    """A domain whose default database is a file-backed SQLite provider.

    SQLAlchemy gives a file database a ``QueuePool``, so the provider reports
    real pool counters.
    """
    pytest.importorskip("sqlalchemy")
    domain = Domain(name="Pool")
    domain.config["databases"]["default"] = {
        "provider": "sqlite",
        "database_uri": f"sqlite:///{tmp_path / 'pool.db'}",
    }
    domain.init(traverse=False)
    yield domain
    with domain.domain_context():
        domain.providers["default"]._engine.dispose()


class RedisPool:
    """Stands in for a Redis client's connection pool."""

    def __init__(self, created: int, available: int, max_connections: int):
        self._created_connections = created
        self._available_connections = [object() for _ in range(available)]
        self.max_connections = max_connections


class RedisClient:
    """Stands in for the Redis client a Redis broker holds."""

    def __init__(self, pool: RedisPool):
        self.connection_pool = pool


class UnreachableRedisClient:
    """Stands in for a Redis client whose pool cannot be read."""

    @property
    def connection_pool(self):
        raise ConnectionError("redis unreachable")


def _attach_redis(monkeypatch, domain, client) -> None:
    """Give the domain's default broker a Redis client stand-in."""
    with domain.domain_context():
        broker = domain.brokers.get("default")
    monkeypatch.setattr(broker, "redis_instance", client, raising=False)


class Order(BaseAggregate):
    name = String()


class OrderPlaced(BaseEvent):
    id = Identifier()


class OrderEventHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        pass


def _outbox_domain(rows: dict[str, int]) -> Domain:
    """A domain with the outbox enabled and ``rows`` outbox rows per status."""
    domain = Domain(name="Backpressure")
    domain.config["enable_outbox"] = True
    domain.config["server"] = {"default_subscription_type": "stream"}
    domain.register(Order)
    domain.register(OrderPlaced, part_of=Order)
    domain.init(traverse=False)

    metadata = Metadata(
        headers=MessageHeaders(
            id="bp-test", type="OrderPlaced", time=datetime.now(UTC), stream="s"
        ),
        domain=DomainMeta(
            fqn="tests.OrderPlaced",
            kind="event",
            origin_stream="order-1",
            version="1.0",
            sequence_id="1",
        ),
    )
    with domain.domain_context():
        repo = domain._get_outbox_repo("default")
        n = 0
        for row_status, count in rows.items():
            for _ in range(count):
                row = Outbox.create_message(
                    message_id=f"row-{n}",
                    stream_name="order-1",
                    message_type="OrderPlaced",
                    data={},
                    metadata=metadata,
                )
                row.status = row_status
                repo.add(row)
                n += 1
    return domain


# ---------------------------------------------------------------------------
# BaseProvider.pool_stats() tests
# ---------------------------------------------------------------------------


class TestBaseProviderPoolStats:
    """BaseProvider.pool_stats() returns empty dict by default."""

    def test_memory_provider_inherits_empty_pool_stats(self, test_domain):
        provider = test_domain.providers["default"]

        assert type(provider).pool_stats is BaseProvider.pool_stats
        assert provider.pool_stats() == {}

    def test_pool_stats_is_not_abstract(self):
        """pool_stats is a concrete method, not abstract."""
        assert not getattr(BaseProvider.pool_stats, "__isabstractmethod__", False)


# ---------------------------------------------------------------------------
# SAProvider.pool_stats() tests
# ---------------------------------------------------------------------------


class TestSAProviderPoolStats:
    """SAProvider.pool_stats() reads pool counters from the SQLAlchemy engine."""

    def test_returns_pool_counters(self, sqlite_domain):
        """pool_stats returns size, checked_out, overflow, checked_in."""
        with sqlite_domain.domain_context():
            provider = sqlite_domain.providers["default"]
            pool = provider._engine.pool

            with provider._engine.connect():
                result = provider.pool_stats()
                expected = {
                    "size": pool.size(),
                    "checked_out": 1,
                    "overflow": pool.overflow(),
                    "checked_in": pool.checkedin(),
                }

        assert result == expected
        assert result["size"] == 5

    @pytest.mark.parametrize("remove", [False, True], ids=["none", "missing"])
    def test_returns_empty_without_engine(self, sqlite_domain, remove):
        """pool_stats returns {} when _engine is None or does not exist."""
        with sqlite_domain.domain_context():
            provider = sqlite_domain.providers["default"]
        engine = provider._engine
        if remove:
            del provider._engine
        else:
            provider._engine = None

        assert provider.pool_stats() == {}

        provider._engine = engine

    def test_returns_empty_for_pool_without_counters(self, sqlite_domain):
        """pool_stats returns {} for a pool that exposes no counters."""
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool

        with sqlite_domain.domain_context():
            provider = sqlite_domain.providers["default"]
        engine = provider._engine
        provider._engine = create_engine("sqlite://", poolclass=NullPool)

        assert provider.pool_stats() == {}

        provider._engine.dispose()
        provider._engine = engine


# ---------------------------------------------------------------------------
# Shared collection helper tests
# ---------------------------------------------------------------------------


class TestCollectPoolStats:
    """_collect_pool_stats extracts pool data from all domain providers."""

    def test_collects_from_provider_with_stats(self, sqlite_domain):
        result = _collect_pool_stats([sqlite_domain])

        assert len(result) == 1
        name, db_type, stats = result[0]
        assert name == "default"
        assert db_type == "sqlite"
        assert stats["size"] == 5
        assert stats["checked_out"] == 0

    def test_skips_provider_with_empty_stats(self, test_domain):
        assert _collect_pool_stats([test_domain]) == []

    def test_handles_domain_exception(self, sqlite_domain, monkeypatch):
        with sqlite_domain.domain_context():
            provider = sqlite_domain.providers["default"]

        def _fail():
            raise RuntimeError("boom")

        monkeypatch.setattr(provider, "pool_stats", _fail)

        assert _collect_pool_stats([sqlite_domain]) == []

    def test_handles_none_providers(self):
        domain = Domain(name="Uninitialized")
        assert domain.providers._providers is None

        assert _collect_pool_stats([domain]) == []


class TestCollectBrokerPoolStats:
    """_collect_broker_pool_stats reads Redis connection pool state."""

    def test_collects_active_connections(self, test_domain, monkeypatch):
        _attach_redis(
            monkeypatch,
            test_domain,
            RedisClient(RedisPool(created=5, available=2, max_connections=10)),
        )

        result = _collect_broker_pool_stats([test_domain])
        assert len(result) == 1
        name, active, available, max_conn = result[0]
        assert name == "default"
        assert active == 3  # 5 created - 2 available
        assert available == 2
        assert max_conn == 10

    def test_skips_broker_without_redis_instance(self, test_domain):
        assert _collect_broker_pool_stats([test_domain]) == []

    def test_handles_exception(self, test_domain, monkeypatch):
        _attach_redis(monkeypatch, test_domain, UnreachableRedisClient())

        assert _collect_broker_pool_stats([test_domain]) == []


class TestCollectSubscriptionStatuses:
    """_collect_subscription_statuses gathers subscription data from all domains."""

    def test_collects_statuses(self):
        domain = _outbox_domain({"pending": 3, "failed": 1})

        result = _collect_subscription_statuses([domain])

        assert len(result) == 1
        d, s = result[0]
        assert d is domain
        assert s.handler_name == "OutboxProcessor"
        assert s.lag == 3
        assert s.pending == 3
        assert s.dlq_depth == 1

    def test_handles_exception(self, test_domain):
        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            side_effect=RuntimeError("boom"),
        ):
            result = _collect_subscription_statuses([test_domain])

        assert result == []


# ---------------------------------------------------------------------------
# OTEL observable gauge tests
# ---------------------------------------------------------------------------


class TestDBPoolOTELGauges:
    """DB pool observable gauges produce measurements with correct attributes."""

    def test_pool_gauges_produce_measurements(self, sqlite_domain):
        metric_reader = _init_telemetry_in_memory(sqlite_domain)
        _register_infrastructure_gauges([sqlite_domain])

        with sqlite_domain.domain_context():
            provider = sqlite_domain.providers["default"]
            with provider._engine.connect():
                data = metric_reader.get_metrics_data()
                # Read the pool after the scrape: other gauges may open and
                # return connections while it runs.
                expected = provider.pool_stats()

        points = {
            metric.name: list(metric.data.data_points)
            for rm in data.resource_metrics
            for sm in rm.scope_metrics
            for metric in sm.metrics
        }
        size = points["protean.db.pool_size"]
        assert len(size) >= 1
        assert size[0].value == 5
        attrs = dict(size[0].attributes)
        assert attrs["provider_name"] == "default"
        assert attrs["database_type"] == "sqlite"
        assert points["protean.db.pool_checked_out"][0].value == 1
        assert points["protean.db.pool_overflow"][0].value == expected["overflow"]
        assert points["protean.db.pool_checked_in"][0].value == expected["checked_in"]

        _clean_gauges(sqlite_domain)

    def test_pool_gauges_empty_when_no_stats(self, test_domain):
        metric_reader = _init_telemetry_in_memory(test_domain)
        _clean_gauges(test_domain)

        _register_infrastructure_gauges([test_domain])

        # The memory provider has no pool, so the gauge has no data points.
        points = _get_metric_data_points(metric_reader, "protean.db.pool_size")
        assert len(points) == 0

        _clean_gauges(test_domain)


class TestBrokerPoolOTELGauges:
    """Broker pool observable gauge produces active connection measurements."""

    def test_broker_pool_gauge_produces_measurement(self, test_domain, monkeypatch):
        metric_reader = _init_telemetry_in_memory(test_domain)
        _clean_gauges(test_domain)
        _attach_redis(
            monkeypatch,
            test_domain,
            RedisClient(RedisPool(created=10, available=6, max_connections=10)),
        )

        _register_infrastructure_gauges([test_domain])

        points = _get_metric_data_points(
            metric_reader, "protean.broker.pool_active_connections"
        )
        assert len(points) >= 1
        assert points[0].value == 4
        assert dict(points[0].attributes)["broker_name"] == "default"

        _clean_gauges(test_domain)


class TestBackpressureOTELGauges:
    """Backpressure gauges use OTEL-style names."""

    def test_outbox_gauge_produces_pending_total(self, test_domain):
        metric_reader = _init_telemetry_in_memory(test_domain)
        _clean_gauges(test_domain)

        _register_infrastructure_gauges([test_domain])

        points = _get_metric_data_points(metric_reader, "protean.outbox.pending_count")
        # test_domain with memory adapters: count_by_status returns {}
        # pending_total = 0
        assert len(points) >= 1
        assert points[0].value == 0
        assert dict(points[0].attributes)["domain"] == "Test"

        _clean_gauges(test_domain)

    def test_subscription_lag_pending_dlq_and_status_gauges(self):
        domain = _outbox_domain(
            {"pending": 5, "processing": 2, "failed": 3, "abandoned": 4}
        )
        metric_reader = _init_telemetry_in_memory(domain)

        _register_infrastructure_gauges([domain])

        def _value(name):
            points = _get_metric_data_points(metric_reader, name)
            assert len(points) == 1
            return points[0]

        lag = _value("protean.subscription.consumer_lag")
        assert lag.value == 7  # pending + processing
        attrs = dict(lag.attributes)
        assert attrs["handler"] == "OutboxProcessor"
        assert attrs["stream"] == "default → default"

        assert _value("protean.subscription.pending_messages").value == 5
        assert _value("protean_subscription_dlq_depth").value == 7  # failed + abandoned
        # The status is "lagging", which is not "ok".
        assert _value("protean_subscription_status").value == 0

        _clean_gauges(domain)


class TestGaugeRegistrationGuard:
    """Infrastructure gauges are only registered once per domain."""

    def test_double_registration_is_idempotent(self, test_domain):
        _init_telemetry_in_memory(test_domain)
        _clean_gauges(test_domain)

        _register_infrastructure_gauges([test_domain])
        assert getattr(test_domain, _GAUGES_KEY, False) is True

        # Second call should be a no-op (doesn't raise)
        _register_infrastructure_gauges([test_domain])
        assert getattr(test_domain, _GAUGES_KEY, False) is True

        _clean_gauges(test_domain)

    def test_skips_when_no_telemetry_init(self, test_domain):
        # Domain without telemetry init
        _register_infrastructure_gauges([test_domain])
        assert getattr(test_domain, _GAUGES_KEY, False) is False

    def test_skips_empty_domains_list(self):
        _register_infrastructure_gauges([])


# ---------------------------------------------------------------------------
# Hand-rolled metrics fallback tests
# ---------------------------------------------------------------------------


class TestHandRolledPoolMetrics:
    """Hand-rolled fallback includes pool and broker pool metrics."""

    def test_includes_db_pool_metrics(self, sqlite_domain):
        output = _hand_rolled_metrics([sqlite_domain])

        assert "protean_db_pool_size" in output
        assert "protean_db_pool_checked_out" in output
        assert "protean_db_pool_overflow" in output
        assert "protean_db_pool_checked_in" in output
        assert 'provider_name="default"' in output
        assert 'database_type="sqlite"' in output

    def test_includes_broker_pool_metrics(self, test_domain, monkeypatch):
        _attach_redis(
            monkeypatch,
            test_domain,
            RedisClient(RedisPool(created=10, available=6, max_connections=10)),
        )

        output = _hand_rolled_metrics([test_domain])

        assert "protean_broker_pool_active_connections" in output
        assert 'protean_broker_pool_active_connections{broker_name="default"} 4' in (
            output
        )

    def test_outbox_uses_pending_count_name_and_omits_empty_pools(self):
        domain = _outbox_domain({"pending": 5, "published": 2})

        output = _hand_rolled_metrics([domain])

        assert "protean_outbox_pending_count" in output
        # pending_count reflects only the "pending" status, not all statuses
        assert 'protean_outbox_pending_count{domain="Backpressure"} 5' in output
        # The memory provider and inline broker have no pools to report.
        assert "protean_db_pool_size" not in output
        assert "protean_broker_pool_active_connections" not in output

    def test_subscription_uses_otel_names(self):
        domain = _outbox_domain({"pending": 1, "failed": 1})

        output = _hand_rolled_metrics([domain])

        assert "protean_subscription_consumer_lag" in output
        assert "protean_subscription_pending_messages" in output
        assert "protean_subscription_dlq_depth" in output
        assert "protean_subscription_status" in output

    def test_pool_stats_exception_handled(self, test_domain):
        with patch(
            "protean.server.observatory.metrics._collect_pool_stats",
            side_effect=RuntimeError("pool query failed"),
        ):
            output = _hand_rolled_metrics([test_domain])

        # Should still have outbox metrics
        assert "protean_outbox_pending_count" in output

    def test_subscription_lag_none_omits_lag_line(self, test_domain):
        """When lag is None, the consumer_lag line is omitted.

        An event handler whose stream category has no events yet has no head
        position, so its lag is unknown.
        """
        test_domain.register(Order)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(OrderEventHandler, part_of=Order)
        test_domain.init(traverse=False)

        [(_, status)] = _collect_subscription_statuses([test_domain])
        assert status.lag is None
        _scrape_cache.clear()

        output = _hand_rolled_metrics([test_domain])

        # pending_messages is present but consumer_lag value line is absent
        assert "protean_subscription_pending_messages" in output
        lines = output.split("\n")
        lag_data_lines = [
            line
            for line in lines
            if line.startswith("protean_subscription_consumer_lag{")
        ]
        assert len(lag_data_lines) == 0
