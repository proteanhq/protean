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

from unittest.mock import MagicMock, patch

import pytest

from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource

from protean.port.provider import BaseProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_telemetry_in_memory(domain):
    """Set up in-memory OTEL metric reader on the domain for testing."""
    resource = Resource.create({"service.name": domain.normalized_name})
    metric_reader = InMemoryMetricReader()
    meter_provider = SDKMeterProvider(
        resource=resource, metric_readers=[metric_reader]
    )

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


def _make_mock_domain(name: str = "test") -> MagicMock:
    """Create a mock Domain for unit tests."""
    mock = MagicMock()
    mock.name = name
    mock.normalized_name = name.lower().replace(" ", "_")
    mock.domain_context.return_value.__enter__ = MagicMock(return_value=None)
    mock.domain_context.return_value.__exit__ = MagicMock(return_value=False)
    return mock


def _make_mock_provider(
    name: str = "default",
    database: str = "postgresql",
    pool_stats_data: dict | None = None,
) -> MagicMock:
    """Create a mock Provider with pool_stats."""
    provider = MagicMock()
    provider.name = name
    provider.__database__ = database
    provider.pool_stats.return_value = pool_stats_data or {}
    return provider


_GAUGES_KEY = "_otel_infra_gauges_registered"


def _clean_gauges(domain):
    """Remove gauge registration sentinel from domain."""
    if hasattr(domain, _GAUGES_KEY):
        delattr(domain, _GAUGES_KEY)


# ---------------------------------------------------------------------------
# BaseProvider.pool_stats() tests
# ---------------------------------------------------------------------------


class TestBaseProviderPoolStats:
    """BaseProvider.pool_stats() returns empty dict by default."""

    def test_default_returns_empty_dict(self):
        assert BaseProvider.pool_stats(MagicMock()) == {}

    def test_pool_stats_is_not_abstract(self):
        """pool_stats is a concrete method, not abstract."""
        assert not getattr(BaseProvider.pool_stats, "__isabstractmethod__", False)


# ---------------------------------------------------------------------------
# SAProvider.pool_stats() tests
# ---------------------------------------------------------------------------


class TestSAProviderPoolStats:
    """SAProvider.pool_stats() reads pool counters from the SQLAlchemy engine."""

    @pytest.fixture(autouse=True)
    def _require_sqlalchemy(self):
        pytest.importorskip("sqlalchemy")

    def test_returns_pool_counters(self):
        """pool_stats returns size, checked_out, overflow, checked_in."""
        from protean.adapters.repository.sqlalchemy import SAProvider

        mock_pool = MagicMock()
        mock_pool.size.return_value = 5
        mock_pool.checkedout.return_value = 2
        mock_pool.overflow.return_value = 1
        mock_pool.checkedin.return_value = 3

        provider = MagicMock(spec=SAProvider)
        provider._engine = MagicMock()
        provider._engine.pool = mock_pool

        result = SAProvider.pool_stats(provider)

        assert result == {
            "size": 5,
            "checked_out": 2,
            "overflow": 1,
            "checked_in": 3,
        }

    def test_returns_empty_when_no_engine(self):
        """pool_stats returns {} when _engine is None."""
        from protean.adapters.repository.sqlalchemy import SAProvider

        provider = MagicMock(spec=SAProvider)
        provider._engine = None

        result = SAProvider.pool_stats(provider)
        assert result == {}

    def test_returns_empty_for_sqlite_pool(self):
        """pool_stats returns {} for SingletonThreadPool (SQLite)."""
        from protean.adapters.repository.sqlalchemy import SAProvider

        mock_pool = MagicMock()
        # SingletonThreadPool doesn't have size/checkedout methods
        del mock_pool.size
        del mock_pool.checkedout
        del mock_pool.overflow
        del mock_pool.checkedin

        provider = MagicMock(spec=SAProvider)
        provider._engine = MagicMock()
        provider._engine.pool = mock_pool

        result = SAProvider.pool_stats(provider)
        assert result == {}

    def test_returns_empty_when_engine_missing_attr(self):
        """pool_stats returns {} when _engine attr doesn't exist."""
        from protean.adapters.repository.sqlalchemy import SAProvider

        provider = MagicMock(spec=SAProvider)
        del provider._engine

        result = SAProvider.pool_stats(provider)
        assert result == {}


# ---------------------------------------------------------------------------
# MemoryProvider.pool_stats() tests
# ---------------------------------------------------------------------------


class TestMemoryProviderPoolStats:
    """Memory provider inherits the default empty pool_stats."""

    def test_returns_empty_dict(self):
        from protean.adapters.repository.memory import MemoryProvider

        provider = MagicMock(spec=MemoryProvider)
        result = BaseProvider.pool_stats(provider)
        assert result == {}


# ---------------------------------------------------------------------------
# Shared collection helper tests
# ---------------------------------------------------------------------------


class TestCollectPoolStats:
    """_collect_pool_stats extracts pool data from all domain providers."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from protean.server.observatory.metrics import _scrape_cache

        _scrape_cache.clear()

    def test_collects_from_provider_with_stats(self):
        from protean.server.observatory.metrics import _collect_pool_stats

        provider = _make_mock_provider(
            pool_stats_data={
                "size": 5,
                "checked_out": 2,
                "overflow": 0,
                "checked_in": 3,
            }
        )
        domain = _make_mock_domain()
        domain.providers = MagicMock()
        domain.providers._providers = {"default": provider}

        result = _collect_pool_stats([domain])
        assert len(result) == 1
        name, db_type, stats = result[0]
        assert name == "default"
        assert db_type == "postgresql"
        assert stats["size"] == 5
        assert stats["checked_out"] == 2

    def test_skips_provider_with_empty_stats(self):
        from protean.server.observatory.metrics import _collect_pool_stats

        provider = _make_mock_provider(pool_stats_data={})
        domain = _make_mock_domain()
        domain.providers = MagicMock()
        domain.providers._providers = {"default": provider}

        result = _collect_pool_stats([domain])
        assert len(result) == 0

    def test_handles_domain_exception(self):
        from protean.server.observatory.metrics import _collect_pool_stats

        domain = _make_mock_domain()
        domain.domain_context.side_effect = RuntimeError("boom")

        result = _collect_pool_stats([domain])
        assert result == []

    def test_handles_none_providers(self):
        from protean.server.observatory.metrics import _collect_pool_stats

        domain = _make_mock_domain()
        domain.providers = MagicMock()
        domain.providers._providers = None

        result = _collect_pool_stats([domain])
        assert result == []


class TestCollectBrokerPoolStats:
    """_collect_broker_pool_stats reads Redis connection pool state."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from protean.server.observatory.metrics import _scrape_cache

        _scrape_cache.clear()

    def test_collects_active_connections(self):
        from protean.server.observatory.metrics import _collect_broker_pool_stats

        pool = MagicMock()
        pool._created_connections = 5
        pool._available_connections = [MagicMock(), MagicMock()]
        pool.max_connections = 10

        redis_inst = MagicMock()
        redis_inst.connection_pool = pool

        broker = MagicMock()
        broker.redis_instance = redis_inst

        domain = _make_mock_domain()
        domain.brokers = MagicMock()
        domain.brokers._brokers = {"default": broker}

        result = _collect_broker_pool_stats([domain])
        assert len(result) == 1
        name, active, available, max_conn = result[0]
        assert name == "default"
        assert active == 3  # 5 created - 2 available
        assert available == 2
        assert max_conn == 10

    def test_skips_broker_without_redis_instance(self):
        from protean.server.observatory.metrics import _collect_broker_pool_stats

        broker = MagicMock(spec=[])  # no redis_instance attr

        domain = _make_mock_domain()
        domain.brokers = MagicMock()
        domain.brokers._brokers = {"default": broker}

        result = _collect_broker_pool_stats([domain])
        assert result == []

    def test_handles_exception(self):
        from protean.server.observatory.metrics import _collect_broker_pool_stats

        domain = _make_mock_domain()
        domain.domain_context.side_effect = RuntimeError("fail")

        result = _collect_broker_pool_stats([domain])
        assert result == []


class TestCollectSubscriptionStatuses:
    """_collect_subscription_statuses gathers subscription data from all domains."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from protean.server.observatory.metrics import _scrape_cache

        _scrape_cache.clear()

    def test_collects_statuses(self):
        from protean.server.observatory.metrics import _collect_subscription_statuses

        mock_status = MagicMock()
        mock_status.handler_name = "TestHandler"
        mock_status.stream_category = "test::events"
        mock_status.subscription_type = "stream"
        mock_status.lag = 10
        mock_status.pending = 3
        mock_status.dlq_depth = 1
        mock_status.status = "ok"

        domain = _make_mock_domain()

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=[mock_status],
        ):
            result = _collect_subscription_statuses([domain])

        assert len(result) == 1
        d, s = result[0]
        assert d.name == "test"
        assert s.lag == 10
        assert s.pending == 3

    def test_handles_exception(self):
        from protean.server.observatory.metrics import _collect_subscription_statuses

        domain = _make_mock_domain()

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            side_effect=RuntimeError("boom"),
        ):
            result = _collect_subscription_statuses([domain])

        assert result == []


# ---------------------------------------------------------------------------
# OTEL observable gauge tests
# ---------------------------------------------------------------------------


class TestDBPoolOTELGauges:
    """DB pool observable gauges produce measurements with correct attributes."""

    def test_pool_gauges_produce_measurements(self, test_domain):
        metric_reader = _init_telemetry_in_memory(test_domain)
        _clean_gauges(test_domain)

        from protean.server.observatory.metrics import _register_infrastructure_gauges

        fake_stats = [
            (
                "default",
                "postgresql",
                {"size": 5, "checked_out": 2, "overflow": 1, "checked_in": 3},
            )
        ]

        with patch(
            "protean.server.observatory.metrics._collect_pool_stats",
            return_value=fake_stats,
        ):
            _register_infrastructure_gauges([test_domain])

            points = _get_metric_data_points(metric_reader, "protean.db.pool_size")
            assert len(points) >= 1
            assert points[0].value == 5
            attrs = dict(points[0].attributes)
            assert attrs["provider_name"] == "default"
            assert attrs["database_type"] == "postgresql"

            points = _get_metric_data_points(
                metric_reader, "protean.db.pool_checked_out"
            )
            assert len(points) >= 1
            assert points[0].value == 2

            points = _get_metric_data_points(
                metric_reader, "protean.db.pool_overflow"
            )
            assert len(points) >= 1
            assert points[0].value == 1

            points = _get_metric_data_points(
                metric_reader, "protean.db.pool_checked_in"
            )
            assert len(points) >= 1
            assert points[0].value == 3

        _clean_gauges(test_domain)

    def test_pool_gauges_empty_when_no_stats(self, test_domain):
        metric_reader = _init_telemetry_in_memory(test_domain)
        _clean_gauges(test_domain)

        from protean.server.observatory.metrics import _register_infrastructure_gauges

        with patch(
            "protean.server.observatory.metrics._collect_pool_stats",
            return_value=[],
        ):
            _register_infrastructure_gauges([test_domain])

            # With empty results, the gauge still exists but has no data points
            points = _get_metric_data_points(metric_reader, "protean.db.pool_size")
            assert len(points) == 0

        _clean_gauges(test_domain)


class TestBrokerPoolOTELGauges:
    """Broker pool observable gauge produces active connection measurements."""

    def test_broker_pool_gauge_produces_measurement(self, test_domain):
        metric_reader = _init_telemetry_in_memory(test_domain)
        _clean_gauges(test_domain)

        from protean.server.observatory.metrics import _register_infrastructure_gauges

        fake_data = [("default", 4, 6, 10)]

        with patch(
            "protean.server.observatory.metrics._collect_broker_pool_stats",
            return_value=fake_data,
        ):
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

        from protean.server.observatory.metrics import _register_infrastructure_gauges

        _register_infrastructure_gauges([test_domain])

        points = _get_metric_data_points(
            metric_reader, "protean.outbox.pending_count"
        )
        # test_domain with memory adapters: count_by_status returns {}
        # pending_total = 0
        assert len(points) >= 1
        assert points[0].value == 0
        assert dict(points[0].attributes)["domain"] == "Test"

        _clean_gauges(test_domain)

    def test_subscription_lag_gauge_produces_measurement(self, test_domain):
        metric_reader = _init_telemetry_in_memory(test_domain)
        _clean_gauges(test_domain)

        from protean.server.observatory.metrics import _register_infrastructure_gauges

        mock_status = MagicMock()
        mock_status.handler_name = "UserHandler"
        mock_status.stream_category = "test::user"
        mock_status.subscription_type = "stream"
        mock_status.lag = 15
        mock_status.pending = 5
        mock_status.dlq_depth = 2
        mock_status.status = "ok"

        fake_collected = [(test_domain, mock_status)]

        with patch(
            "protean.server.observatory.metrics._collect_subscription_statuses",
            return_value=fake_collected,
        ):
            _register_infrastructure_gauges([test_domain])

            points = _get_metric_data_points(
                metric_reader, "protean.subscription.consumer_lag"
            )
            assert len(points) >= 1
            assert points[0].value == 15
            attrs = dict(points[0].attributes)
            assert attrs["handler"] == "UserHandler"
            assert attrs["stream"] == "test::user"

            points = _get_metric_data_points(
                metric_reader, "protean.subscription.pending_messages"
            )
            assert len(points) >= 1
            assert points[0].value == 5

        _clean_gauges(test_domain)

    def test_subscription_dlq_and_status_gauges(self, test_domain):
        metric_reader = _init_telemetry_in_memory(test_domain)
        _clean_gauges(test_domain)

        from protean.server.observatory.metrics import _register_infrastructure_gauges

        mock_status = MagicMock()
        mock_status.handler_name = "FailHandler"
        mock_status.stream_category = "test::orders"
        mock_status.subscription_type = "stream"
        mock_status.lag = 0
        mock_status.pending = 3
        mock_status.dlq_depth = 7
        mock_status.status = "degraded"

        with patch(
            "protean.server.observatory.metrics._collect_subscription_statuses",
            return_value=[(test_domain, mock_status)],
        ):
            _register_infrastructure_gauges([test_domain])

            points = _get_metric_data_points(
                metric_reader, "protean_subscription_dlq_depth"
            )
            assert len(points) >= 1
            assert points[0].value == 7

            points = _get_metric_data_points(
                metric_reader, "protean_subscription_status"
            )
            assert len(points) >= 1
            assert points[0].value == 0  # "degraded" != "ok"

        _clean_gauges(test_domain)


class TestGaugeRegistrationGuard:
    """Infrastructure gauges are only registered once per domain."""

    def test_double_registration_is_idempotent(self, test_domain):
        _init_telemetry_in_memory(test_domain)
        _clean_gauges(test_domain)

        from protean.server.observatory.metrics import _register_infrastructure_gauges

        _register_infrastructure_gauges([test_domain])
        assert getattr(test_domain, _GAUGES_KEY, False) is True

        # Second call should be a no-op (doesn't raise)
        _register_infrastructure_gauges([test_domain])

        _clean_gauges(test_domain)

    def test_skips_when_no_telemetry_init(self, test_domain):
        from protean.server.observatory.metrics import _register_infrastructure_gauges

        # Domain without telemetry init
        _register_infrastructure_gauges([test_domain])
        assert getattr(test_domain, _GAUGES_KEY, False) is False

    def test_skips_empty_domains_list(self):
        from protean.server.observatory.metrics import _register_infrastructure_gauges

        _register_infrastructure_gauges([])


# ---------------------------------------------------------------------------
# Hand-rolled metrics fallback tests
# ---------------------------------------------------------------------------


class TestHandRolledPoolMetrics:
    """Hand-rolled fallback includes pool and broker pool metrics."""

    def test_includes_db_pool_metrics(self):
        from protean.server.observatory.metrics import _hand_rolled_metrics

        domain = _make_mock_domain()
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {}
        domain._get_outbox_repo.return_value = mock_outbox
        domain.brokers.get.return_value = None

        fake_stats = [
            (
                "default",
                "postgresql",
                {"size": 10, "checked_out": 3, "overflow": 0, "checked_in": 7},
            )
        ]

        with patch(
            "protean.server.observatory.metrics._collect_pool_stats",
            return_value=fake_stats,
        ):
            output = _hand_rolled_metrics([domain])

        assert "protean_db_pool_size" in output
        assert "protean_db_pool_checked_out" in output
        assert "protean_db_pool_overflow" in output
        assert "protean_db_pool_checked_in" in output
        assert 'provider_name="default"' in output
        assert 'database_type="postgresql"' in output

    def test_includes_broker_pool_metrics(self):
        from protean.server.observatory.metrics import _hand_rolled_metrics

        domain = _make_mock_domain()
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {}
        domain._get_outbox_repo.return_value = mock_outbox
        domain.brokers.get.return_value = None

        fake_data = [("default", 4, 6, 10)]

        with patch(
            "protean.server.observatory.metrics._collect_broker_pool_stats",
            return_value=fake_data,
        ):
            output = _hand_rolled_metrics([domain])

        assert "protean_broker_pool_active_connections" in output
        assert 'broker_name="default"' in output

    def test_outbox_uses_pending_count_name(self):
        from protean.server.observatory.metrics import _hand_rolled_metrics

        domain = _make_mock_domain()
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {"pending": 5, "published": 2}
        domain._get_outbox_repo.return_value = mock_outbox
        domain.brokers.get.return_value = None

        output = _hand_rolled_metrics([domain])
        assert "protean_outbox_pending_count" in output
        # pending_count reflects only the "pending" status, not all statuses
        assert 'protean_outbox_pending_count{domain="test"} 5' in output

    def test_subscription_uses_otel_names(self):
        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_status = MagicMock()
        mock_status.handler_name = "TestHandler"
        mock_status.stream_category = "test::events"
        mock_status.subscription_type = "stream"
        mock_status.lag = 10
        mock_status.pending = 3
        mock_status.dlq_depth = 1
        mock_status.status = "ok"

        domain = _make_mock_domain()
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {}
        domain._get_outbox_repo.return_value = mock_outbox
        domain.brokers.get.return_value = None

        with patch(
            "protean.server.observatory.metrics._collect_subscription_statuses",
            return_value=[(domain, mock_status)],
        ):
            output = _hand_rolled_metrics([domain])

        assert "protean_subscription_consumer_lag" in output
        assert "protean_subscription_pending_messages" in output
        assert "protean_subscription_dlq_depth" in output
        assert "protean_subscription_status" in output

    def test_empty_pool_stats_omits_section(self):
        from protean.server.observatory.metrics import _hand_rolled_metrics

        domain = _make_mock_domain()
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {}
        domain._get_outbox_repo.return_value = mock_outbox
        domain.brokers.get.return_value = None

        with patch(
            "protean.server.observatory.metrics._collect_pool_stats",
            return_value=[],
        ), patch(
            "protean.server.observatory.metrics._collect_broker_pool_stats",
            return_value=[],
        ):
            output = _hand_rolled_metrics([domain])

        assert "protean_db_pool_size" not in output
        assert "protean_broker_pool_active_connections" not in output

    def test_pool_stats_exception_handled(self):
        from protean.server.observatory.metrics import _hand_rolled_metrics

        domain = _make_mock_domain()
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {}
        domain._get_outbox_repo.return_value = mock_outbox
        domain.brokers.get.return_value = None

        with patch(
            "protean.server.observatory.metrics._collect_pool_stats",
            side_effect=RuntimeError("pool query failed"),
        ):
            output = _hand_rolled_metrics([domain])

        # Should still have outbox metrics
        assert "protean_outbox_pending_count" in output

    def test_subscription_lag_none_omits_lag_line(self):
        """When lag is None, the consumer_lag line is omitted."""
        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_status = MagicMock()
        mock_status.handler_name = "Handler"
        mock_status.stream_category = "test::events"
        mock_status.subscription_type = "stream"
        mock_status.lag = None
        mock_status.pending = 2
        mock_status.dlq_depth = 0
        mock_status.status = "ok"

        domain = _make_mock_domain()
        mock_outbox = MagicMock()
        mock_outbox.count_by_status.return_value = {}
        domain._get_outbox_repo.return_value = mock_outbox
        domain.brokers.get.return_value = None

        with patch(
            "protean.server.observatory.metrics._collect_subscription_statuses",
            return_value=[(domain, mock_status)],
        ):
            output = _hand_rolled_metrics([domain])

        # pending_messages is present but consumer_lag value line is absent
        assert "protean_subscription_pending_messages" in output
        lines = output.split("\n")
        lag_data_lines = [
            l
            for l in lines
            if l.startswith("protean_subscription_consumer_lag{")
        ]
        assert len(lag_data_lines) == 0
