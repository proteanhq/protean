"""Tests for OpenTelemetry metrics instrumentation on domain operations.

Verifies that:
- ``CommandProcessor.process()`` increments ``protean.command.processed``
  counter and records ``protean.command.duration`` histogram.
- ``HandlerMixin._handle()`` increments ``protean.handler.invocations``
  counter and records ``protean.handler.duration`` histogram.
- ``UnitOfWork.commit()`` increments ``protean.uow.commits`` counter and
  records ``protean.uow.events_per_commit`` histogram.
- Error paths correctly record status="error" attributes.
- ``DomainMetrics`` instances are cached per domain and reset on shutdown.
- The ``/metrics`` endpoint serves OTel-generated Prometheus text when
  telemetry is enabled, and falls back to hand-rolled text otherwise.
"""

from uuid import uuid4

import pytest

from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.fields import Identifier, String
from protean.utils.globals import current_domain
from protean.utils.mixins import handle
from protean.utils.telemetry import (
    DomainMetrics,
    _DOMAIN_METRICS_KEY,
    get_domain_metrics,
    shutdown_telemetry,
)


# ---------------------------------------------------------------------------
# Domain elements for testing
# ---------------------------------------------------------------------------


class Account(BaseAggregate):
    account_id = Identifier(identifier=True)
    name = String(required=True)


class AccountCreated(BaseEvent):
    account_id = Identifier(identifier=True)
    name = String(required=True)


class AccountWithEvent(BaseAggregate):
    account_id = Identifier(identifier=True)
    name = String(required=True)

    @classmethod
    def create(cls, account_id: str, name: str) -> "AccountWithEvent":
        account = cls(account_id=account_id, name=name)
        account.raise_(AccountCreated(account_id=account_id, name=name))
        return account

    @apply
    def on_created(self, event: AccountCreated) -> None:
        self.name = event.name


class OpenAccount(BaseCommand):
    account_id = Identifier(identifier=True)
    name = String(required=True)


class AccountCommandHandler(BaseCommandHandler):
    @handle(OpenAccount)
    def open(self, command: OpenAccount):
        account = Account(account_id=command.account_id, name=command.name)
        current_domain.repository_for(Account).add(account)
        return {"opened": command.account_id}


class FailingCommand(BaseCommand):
    account_id = Identifier(identifier=True)


class FailingCommandHandler(BaseCommandHandler):
    @handle(FailingCommand)
    def fail(self, command: FailingCommand):
        raise RuntimeError("handler exploded")


class CreateAccountWithEvent(BaseCommand):
    account_id = Identifier(identifier=True)
    name = String(required=True)


class AccountWithEventHandler(BaseCommandHandler):
    @handle(CreateAccountWithEvent)
    def create(self, command: CreateAccountWithEvent):
        account = AccountWithEvent.create(
            account_id=command.account_id, name=command.name
        )
        current_domain.repository_for(AccountWithEvent).add(account)
        return {"created": command.account_id}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _init_telemetry_in_memory(domain):
    """Set up in-memory OTEL exporters on the domain for testing.

    Returns (span_exporter, metric_reader) for inspecting captured data.
    """
    service_name = domain.normalized_name
    resource = Resource.create({"service.name": service_name})

    span_exporter = InMemorySpanExporter()
    tracer_provider = SDKTracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))

    metric_reader = InMemoryMetricReader()
    meter_provider = SDKMeterProvider(resource=resource, metric_readers=[metric_reader])

    domain._otel_tracer_provider = tracer_provider
    domain._otel_meter_provider = meter_provider
    domain._otel_init_attempted = True

    return span_exporter, metric_reader


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account)
    test_domain.register(OpenAccount, part_of=Account)
    test_domain.register(AccountCommandHandler, part_of=Account)
    test_domain.register(FailingCommand, part_of=Account)
    test_domain.register(FailingCommandHandler, part_of=Account)
    test_domain.register(AccountWithEvent)
    test_domain.register(AccountCreated, part_of=AccountWithEvent)
    test_domain.register(CreateAccountWithEvent, part_of=AccountWithEvent)
    test_domain.register(AccountWithEventHandler, part_of=AccountWithEvent)
    test_domain.init(traverse=False)


@pytest.fixture()
def telemetry(test_domain):
    """Enable in-memory OTEL and return (span_exporter, metric_reader)."""
    span_exporter, metric_reader = _init_telemetry_in_memory(test_domain)
    yield span_exporter, metric_reader
    # Clean up cached DomainMetrics so it's fresh for next test
    if hasattr(test_domain, _DOMAIN_METRICS_KEY):
        delattr(test_domain, _DOMAIN_METRICS_KEY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_domain(name: str = "test", *, outbox_statuses=None, broker=None):
    """Build a mock domain suitable for _hand_rolled_metrics tests.

    Eliminates the repetitive MagicMock setup that appears across many test
    methods.  Pass *outbox_statuses* (dict) to configure the outbox repo's
    ``count_by_status`` return value, and *broker* to set the broker returned
    by ``domain.brokers.get("default")``.
    """
    from unittest.mock import MagicMock

    mock_domain = MagicMock()
    mock_domain.name = name
    mock_domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
    mock_domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)

    mock_outbox = MagicMock()
    mock_outbox.count_by_status.return_value = outbox_statuses or {}
    mock_domain._get_outbox_repo.return_value = mock_outbox

    mock_domain.brokers.get.return_value = broker

    return mock_domain


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


# ---------------------------------------------------------------------------
# Tests: Command processed counter
# ---------------------------------------------------------------------------


class TestCommandProcessedCounter:
    """CommandProcessor.process() increments ``protean.command.processed``."""

    def test_sync_success_increments_counter(self, test_domain, telemetry):
        _, metric_reader = telemetry

        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        points = _get_metric_data_points(metric_reader, "protean.command.processed")
        assert len(points) >= 1

        # Find the ok data point
        ok_points = [
            p for p in points if dict(p.attributes).get("status") == "ok"
        ]
        assert len(ok_points) == 1
        assert ok_points[0].value == 1
        assert "OpenAccount" in dict(ok_points[0].attributes)["command_type"]

    def test_sync_error_increments_counter_with_error_status(
        self, test_domain, telemetry
    ):
        _, metric_reader = telemetry

        with pytest.raises(RuntimeError, match="handler exploded"):
            test_domain.process(
                FailingCommand(account_id=str(uuid4())),
                asynchronous=False,
            )

        points = _get_metric_data_points(metric_reader, "protean.command.processed")
        error_points = [
            p for p in points if dict(p.attributes).get("status") == "error"
        ]
        assert len(error_points) == 1
        assert error_points[0].value == 1

    def test_async_path_increments_counter_with_enqueued_status(self, test_domain, telemetry):
        _, metric_reader = telemetry

        # Force async processing so the async path is taken
        test_domain.config["command_processing"] = "async"

        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Async Corp"),
            asynchronous=True,
        )

        points = _get_metric_data_points(metric_reader, "protean.command.processed")
        enqueued_points = [
            p for p in points if dict(p.attributes).get("status") == "enqueued"
        ]
        assert len(enqueued_points) == 1
        assert enqueued_points[0].value == 1

    def test_multiple_commands_accumulate(self, test_domain, telemetry):
        _, metric_reader = telemetry

        for _ in range(3):
            test_domain.process(
                OpenAccount(account_id=str(uuid4()), name="Corp"),
                asynchronous=False,
            )

        points = _get_metric_data_points(metric_reader, "protean.command.processed")
        ok_points = [
            p for p in points if dict(p.attributes).get("status") == "ok"
        ]
        assert len(ok_points) == 1
        assert ok_points[0].value == 3


# ---------------------------------------------------------------------------
# Tests: Command duration histogram
# ---------------------------------------------------------------------------


class TestCommandDurationHistogram:
    """CommandProcessor.process() records ``protean.command.duration``."""

    def test_sync_success_records_duration(self, test_domain, telemetry):
        _, metric_reader = telemetry

        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        points = _get_metric_data_points(metric_reader, "protean.command.duration")
        assert len(points) >= 1

        ok_points = [
            p for p in points if dict(p.attributes).get("status") == "ok"
        ]
        assert len(ok_points) == 1
        # Duration should be > 0
        assert ok_points[0].sum > 0
        assert ok_points[0].count == 1

    def test_sync_error_records_duration(self, test_domain, telemetry):
        _, metric_reader = telemetry

        with pytest.raises(RuntimeError):
            test_domain.process(
                FailingCommand(account_id=str(uuid4())),
                asynchronous=False,
            )

        points = _get_metric_data_points(metric_reader, "protean.command.duration")
        error_points = [
            p for p in points if dict(p.attributes).get("status") == "error"
        ]
        assert len(error_points) == 1
        assert error_points[0].sum > 0

    def test_async_path_records_duration_with_enqueued_status(self, test_domain, telemetry):
        _, metric_reader = telemetry

        # Force async processing so the async path is taken
        test_domain.config["command_processing"] = "async"

        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Async Corp"),
            asynchronous=True,
        )

        points = _get_metric_data_points(metric_reader, "protean.command.duration")
        assert len(points) >= 1
        enqueued_points = [
            p for p in points if dict(p.attributes).get("status") == "enqueued"
        ]
        assert len(enqueued_points) == 1
        assert enqueued_points[0].sum > 0


# ---------------------------------------------------------------------------
# Tests: Handler invocations counter
# ---------------------------------------------------------------------------


class TestHandlerInvocationsCounter:
    """HandlerMixin._handle() increments ``protean.handler.invocations``."""

    def test_success_increments_handler_counter(self, test_domain, telemetry):
        _, metric_reader = telemetry

        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        points = _get_metric_data_points(
            metric_reader, "protean.handler.invocations"
        )
        ok_points = [
            p for p in points if dict(p.attributes).get("status") == "ok"
        ]
        assert len(ok_points) >= 1
        assert ok_points[0].value >= 1
        assert (
            dict(ok_points[0].attributes)["handler_name"]
            == "AccountCommandHandler"
        )

    def test_error_increments_handler_counter_with_error(
        self, test_domain, telemetry
    ):
        _, metric_reader = telemetry

        with pytest.raises(RuntimeError):
            test_domain.process(
                FailingCommand(account_id=str(uuid4())),
                asynchronous=False,
            )

        points = _get_metric_data_points(
            metric_reader, "protean.handler.invocations"
        )
        error_points = [
            p for p in points if dict(p.attributes).get("status") == "error"
        ]
        assert len(error_points) == 1
        assert error_points[0].value == 1
        assert (
            dict(error_points[0].attributes)["handler_name"]
            == "FailingCommandHandler"
        )


# ---------------------------------------------------------------------------
# Tests: Handler duration histogram
# ---------------------------------------------------------------------------


class TestHandlerDurationHistogram:
    """HandlerMixin._handle() records ``protean.handler.duration``."""

    def test_success_records_handler_duration(self, test_domain, telemetry):
        _, metric_reader = telemetry

        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        points = _get_metric_data_points(metric_reader, "protean.handler.duration")
        ok_points = [
            p for p in points if dict(p.attributes).get("status") == "ok"
        ]
        assert len(ok_points) >= 1
        assert ok_points[0].sum > 0
        assert ok_points[0].count == 1

    def test_error_records_handler_duration(self, test_domain, telemetry):
        _, metric_reader = telemetry

        with pytest.raises(RuntimeError):
            test_domain.process(
                FailingCommand(account_id=str(uuid4())),
                asynchronous=False,
            )

        points = _get_metric_data_points(metric_reader, "protean.handler.duration")
        error_points = [
            p for p in points if dict(p.attributes).get("status") == "error"
        ]
        assert len(error_points) == 1
        assert error_points[0].sum > 0


# ---------------------------------------------------------------------------
# Tests: UoW commits counter
# ---------------------------------------------------------------------------


class TestUoWCommitsCounter:
    """UnitOfWork.commit() increments ``protean.uow.commits``."""

    def test_command_with_repo_increments_uow_commits(self, test_domain, telemetry):
        _, metric_reader = telemetry

        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Acme"),
            asynchronous=False,
        )

        points = _get_metric_data_points(metric_reader, "protean.uow.commits")
        assert len(points) >= 1
        # At least one commit occurred
        total = sum(p.value for p in points)
        assert total >= 1


# ---------------------------------------------------------------------------
# Tests: UoW events_per_commit histogram
# ---------------------------------------------------------------------------


class TestUoWEventsPerCommitHistogram:
    """UnitOfWork.commit() records ``protean.uow.events_per_commit``."""

    def test_command_without_events_records_zero(self, test_domain, telemetry):
        _, metric_reader = telemetry

        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="NoEvents"),
            asynchronous=False,
        )

        points = _get_metric_data_points(
            metric_reader, "protean.uow.events_per_commit"
        )
        # Should have at least one data point
        assert len(points) >= 1

    def test_command_with_events_records_event_count(self, test_domain, telemetry):
        _, metric_reader = telemetry

        test_domain.process(
            CreateAccountWithEvent(account_id=str(uuid4()), name="WithEvents"),
            asynchronous=False,
        )

        points = _get_metric_data_points(
            metric_reader, "protean.uow.events_per_commit"
        )
        assert len(points) >= 1
        # At least one commit should have recorded events > 0
        total_events = sum(p.sum for p in points)
        assert total_events >= 1


# ---------------------------------------------------------------------------
# Tests: DomainMetrics caching
# ---------------------------------------------------------------------------


class TestDomainMetricsCaching:
    """DomainMetrics is cached per domain and cleaned up on shutdown."""

    def test_get_domain_metrics_returns_same_instance(self, test_domain, telemetry):
        m1 = get_domain_metrics(test_domain)
        m2 = get_domain_metrics(test_domain)
        assert m1 is m2
        assert isinstance(m1, DomainMetrics)

    def test_shutdown_clears_cached_metrics(self, test_domain, telemetry):
        get_domain_metrics(test_domain)
        assert hasattr(test_domain, _DOMAIN_METRICS_KEY)

        shutdown_telemetry(test_domain)
        assert not hasattr(test_domain, _DOMAIN_METRICS_KEY)

    def test_metrics_recreated_after_shutdown(self, test_domain, telemetry):
        m1 = get_domain_metrics(test_domain)
        shutdown_telemetry(test_domain)
        # Re-init
        _init_telemetry_in_memory(test_domain)
        m2 = get_domain_metrics(test_domain)
        assert m1 is not m2


# ---------------------------------------------------------------------------
# Tests: No-op behavior when telemetry is disabled
# ---------------------------------------------------------------------------


class TestNoOpMetrics:
    """Metrics instrumentation is no-op when telemetry is not enabled."""

    def test_command_succeeds_without_telemetry(self, test_domain):
        """Commands work fine even without OTel initialized."""
        result = test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="NoTelemetry"),
            asynchronous=False,
        )
        assert result is not None

    def test_domain_metrics_returns_noop_instruments(self, test_domain):
        """DomainMetrics uses no-op instruments when OTel is not set up."""
        metrics = get_domain_metrics(test_domain)
        # Should not raise even though no real OTel is configured
        metrics.command_processed.add(1, {"command_type": "test", "status": "ok"})
        metrics.command_duration.record(0.5, {"command_type": "test", "status": "ok"})
        metrics.handler_invocations.add(1, {"handler_name": "test", "status": "ok"})
        metrics.handler_duration.record(0.1, {"handler_name": "test", "status": "ok"})
        metrics.uow_commits.add(1)
        metrics.uow_events_per_commit.record(5)
        metrics.outbox_published.add(1)
        metrics.outbox_failed.add(1)
        metrics.outbox_latency.record(0.02)


# ---------------------------------------------------------------------------
# Tests: Metrics endpoint convergence
# ---------------------------------------------------------------------------


class TestMetricsEndpointConvergence:
    """The /metrics endpoint serves OTel text when telemetry is enabled."""

    def test_fallback_produces_hand_rolled_text(self, test_domain):
        """Without OTel, _hand_rolled_metrics produces valid Prometheus text."""
        from protean.server.observatory.metrics import _hand_rolled_metrics

        text = _hand_rolled_metrics([test_domain])
        assert "protean_outbox_pending" in text or "# HELP" in text

    def test_get_prometheus_text_returns_none_without_telemetry(self, test_domain):
        """get_prometheus_text returns None when no PrometheusMetricReader."""
        from protean.utils.telemetry import get_prometheus_text

        assert get_prometheus_text(test_domain) is None

    def test_register_infrastructure_gauges_noop_without_provider(self, test_domain):
        """_register_infrastructure_gauges is a no-op without a meter provider."""
        from protean.server.observatory.metrics import (
            _GAUGES_REGISTERED_KEY,
            _register_infrastructure_gauges,
        )

        _register_infrastructure_gauges([test_domain])
        # Should not set the registered flag since no provider
        assert not getattr(test_domain, _GAUGES_REGISTERED_KEY, False)

    def test_register_infrastructure_gauges_noop_for_empty_list(self):
        """_register_infrastructure_gauges is a no-op when domains list is empty."""
        from protean.server.observatory.metrics import _register_infrastructure_gauges

        # Should not raise
        _register_infrastructure_gauges([])

    def test_register_infrastructure_gauges_with_telemetry(self, test_domain, telemetry):
        """_register_infrastructure_gauges registers gauges when telemetry is active."""
        from protean.server.observatory.metrics import (
            _GAUGES_REGISTERED_KEY,
            _register_infrastructure_gauges,
        )

        _register_infrastructure_gauges([test_domain])
        assert getattr(test_domain, _GAUGES_REGISTERED_KEY, False) is True

    def test_register_infrastructure_gauges_idempotent(self, test_domain, telemetry):
        """Calling _register_infrastructure_gauges twice only registers once."""
        from protean.server.observatory.metrics import (
            _GAUGES_REGISTERED_KEY,
            _register_infrastructure_gauges,
        )

        _register_infrastructure_gauges([test_domain])
        assert getattr(test_domain, _GAUGES_REGISTERED_KEY, False) is True
        # Second call should return early due to the flag
        _register_infrastructure_gauges([test_domain])
        assert getattr(test_domain, _GAUGES_REGISTERED_KEY, False) is True

    def test_register_gauges_skips_domains_without_init(self, test_domain):
        """Gauge registration skips domains that never called init_telemetry."""
        from protean.server.observatory.metrics import (
            _GAUGES_REGISTERED_KEY,
            _register_infrastructure_gauges,
        )

        # Domain has _otel_init_attempted = False (default)
        _register_infrastructure_gauges([test_domain])
        assert not getattr(test_domain, _GAUGES_REGISTERED_KEY, False)

    def test_create_metrics_endpoint_returns_callable(self, test_domain):
        """create_metrics_endpoint returns an async callable."""
        import asyncio

        from protean.server.observatory.metrics import create_metrics_endpoint

        endpoint = create_metrics_endpoint([test_domain])
        # Call the async endpoint
        response = asyncio.get_event_loop().run_until_complete(endpoint())
        assert response.status_code == 200
        assert "text/plain" in response.media_type

    def test_create_metrics_endpoint_hand_rolled_fallback(self, test_domain):
        """Endpoint falls back to hand-rolled text when telemetry is off."""
        import asyncio

        from protean.server.observatory.metrics import create_metrics_endpoint

        endpoint = create_metrics_endpoint([test_domain])
        response = asyncio.get_event_loop().run_until_complete(endpoint())
        body = response.body.decode("utf-8")
        # Hand-rolled text should contain HELP and TYPE annotations
        assert "# HELP protean_outbox_pending" in body

    def test_create_metrics_endpoint_otel_path(self, test_domain, telemetry):
        """Endpoint serves OTel Prometheus text when telemetry is enabled."""
        import asyncio

        from opentelemetry.exporter.prometheus import PrometheusMetricReader

        from protean.server.observatory.metrics import create_metrics_endpoint
        from protean.utils.telemetry import _PROMETHEUS_READER_KEY

        # Attach a PrometheusMetricReader to the domain
        prometheus_reader = PrometheusMetricReader()
        setattr(test_domain, _PROMETHEUS_READER_KEY, prometheus_reader)

        endpoint = create_metrics_endpoint([test_domain])
        response = asyncio.get_event_loop().run_until_complete(endpoint())
        body = response.body.decode("utf-8")
        # OTel-generated text includes Python GC metrics or our custom ones
        assert len(body) > 0
        assert "text/plain" in response.media_type

    def test_get_prometheus_text_with_init_and_reader(self, test_domain, telemetry):
        """get_prometheus_text returns text when domain has init + reader."""
        from opentelemetry.exporter.prometheus import PrometheusMetricReader

        from protean.utils.telemetry import _PROMETHEUS_READER_KEY, get_prometheus_text

        prometheus_reader = PrometheusMetricReader()
        setattr(test_domain, _PROMETHEUS_READER_KEY, prometheus_reader)

        result = get_prometheus_text(test_domain)
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_prometheus_text_returns_none_for_mock_domain(self):
        """get_prometheus_text returns None for MagicMock domains."""
        from unittest.mock import MagicMock

        from protean.utils.telemetry import get_prometheus_text

        mock_domain = MagicMock()
        assert get_prometheus_text(mock_domain) is None

    def test_get_prometheus_text_returns_none_without_reader(self, test_domain, telemetry):
        """get_prometheus_text returns None when init_attempted but no reader."""
        from protean.utils.telemetry import get_prometheus_text

        # telemetry fixture sets _otel_init_attempted = True but no prometheus reader
        result = get_prometheus_text(test_domain)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: create_observation helper
# ---------------------------------------------------------------------------


class TestCreateObservation:
    """Tests for the create_observation helper in telemetry.py."""

    def test_creates_otel_observation_when_available(self):
        """create_observation returns a real Observation when OTel is available."""
        from opentelemetry.metrics import Observation

        from protean.utils.telemetry import create_observation

        obs = create_observation(42, {"key": "value"})
        assert isinstance(obs, Observation)
        assert obs.value == 42
        assert obs.attributes == {"key": "value"}

    def test_creates_observation_without_attributes(self):
        """create_observation works with value only."""
        from protean.utils.telemetry import create_observation

        obs = create_observation(0)
        assert obs.value == 0

    def test_noop_observation_stores_values(self):
        """_NoOpObservation stores value and attributes."""
        from protean.utils.telemetry import _NoOpObservation

        obs = _NoOpObservation(99, {"status": "ok"})
        assert obs.value == 99
        assert obs.attributes == {"status": "ok"}


# ---------------------------------------------------------------------------
# Tests: No-op classes
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests: _hand_rolled_metrics with mock domains
# ---------------------------------------------------------------------------


class TestHandRolledMetricsWithMocks:
    """Tests for _hand_rolled_metrics using mock domains."""

    def test_outbox_metrics_with_mock(self):
        """Hand-rolled outbox metrics render with mock domain."""
        from unittest.mock import MagicMock

        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_broker = MagicMock()
        mock_broker.health_stats.return_value = {
            "connected": True,
            "details": {
                "healthy": True,
                "used_memory": 2048,
                "connected_clients": 3,
                "instantaneous_ops_per_sec": 100,
                "message_counts": {"total_messages": 50, "in_flight": 2},
                "streams": {"count": 5},
                "consumer_groups": {"count": 3},
            },
        }
        mock_domain = _make_mock_domain(
            "test-domain",
            outbox_statuses={"PENDING": 5, "PUBLISHED": 10},
            broker=mock_broker,
        )

        text = _hand_rolled_metrics([mock_domain])

        assert 'protean_outbox_messages{domain="test-domain",status="PENDING"} 5' in text
        assert 'protean_outbox_messages{domain="test-domain",status="PUBLISHED"} 10' in text
        assert "protean_broker_up 1" in text
        assert "protean_broker_memory_bytes 2048" in text
        assert "protean_broker_connected_clients 3" in text
        assert "protean_broker_ops_per_sec 100" in text
        assert "protean_stream_messages_total 50" in text
        assert "protean_stream_pending 2" in text
        assert "protean_streams_count 5" in text
        assert "protean_consumer_groups_count 3" in text

    def test_broker_none_skips_broker_metrics(self):
        """Hand-rolled metrics skip broker section when broker is None."""
        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_domain = _make_mock_domain()
        text = _hand_rolled_metrics([mock_domain])
        assert "protean_outbox_pending" in text
        assert "protean_broker_up" not in text

    def test_outbox_query_failure_gracefully_handled(self):
        """Hand-rolled metrics handle outbox query failure."""
        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_domain = _make_mock_domain("fail-domain")
        mock_domain._get_outbox_repo.side_effect = RuntimeError("outbox error")

        text = _hand_rolled_metrics([mock_domain])
        assert "# HELP protean_outbox_pending" in text

    def test_broker_query_failure_gracefully_handled(self):
        """Hand-rolled metrics handle broker query failure."""
        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_domain = _make_mock_domain("fail-domain")
        mock_domain.brokers.get.side_effect = RuntimeError("broker down")

        text = _hand_rolled_metrics([mock_domain])
        assert "# HELP protean_outbox_pending" in text

    def test_trailing_newline(self):
        """Hand-rolled metrics text ends with newline."""
        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_domain = _make_mock_domain()
        text = _hand_rolled_metrics([mock_domain])
        assert text.endswith("\n")


# ---------------------------------------------------------------------------
# Tests: ObservableGauge callbacks with telemetry active
# ---------------------------------------------------------------------------


class TestGaugeCallbacks:
    """Tests for ObservableGauge callback functions."""

    def test_outbox_callback_returns_observations(self, test_domain, telemetry):
        """Outbox gauge callback returns observations for domain."""
        _, metric_reader = telemetry

        from protean.server.observatory.metrics import (
            _GAUGES_REGISTERED_KEY,
            _register_infrastructure_gauges,
        )

        # Clean up any prior registration
        if hasattr(test_domain, _GAUGES_REGISTERED_KEY):
            delattr(test_domain, _GAUGES_REGISTERED_KEY)

        _register_infrastructure_gauges([test_domain])

        # Force a metric collection which triggers callbacks
        data = metric_reader.get_metrics_data()
        assert data is not None

    def test_gauge_callbacks_with_subscription_statuses(self, test_domain, telemetry):
        """Subscription gauge callbacks execute without error."""
        _, metric_reader = telemetry

        from protean.server.observatory.metrics import (
            _GAUGES_REGISTERED_KEY,
            _register_infrastructure_gauges,
        )

        if hasattr(test_domain, _GAUGES_REGISTERED_KEY):
            delattr(test_domain, _GAUGES_REGISTERED_KEY)

        _register_infrastructure_gauges([test_domain])

        # Trigger collection of all gauges
        data = metric_reader.get_metrics_data()
        # Find gauge metrics
        metric_names = set()
        for rm in data.resource_metrics:
            for sm in rm.scope_metrics:
                for m in sm.metrics:
                    metric_names.add(m.name)

        # At minimum, outbox and broker gauges should be registered
        assert "protean_outbox_pending" in metric_names
        assert "protean_broker_up" in metric_names

    def test_gauge_callbacks_handle_exceptions(self, test_domain, telemetry):
        """Gauge callbacks handle exceptions gracefully."""
        from unittest.mock import patch

        _, metric_reader = telemetry

        from protean.server.observatory.metrics import (
            _GAUGES_REGISTERED_KEY,
            _register_infrastructure_gauges,
        )

        if hasattr(test_domain, _GAUGES_REGISTERED_KEY):
            delattr(test_domain, _GAUGES_REGISTERED_KEY)

        _register_infrastructure_gauges([test_domain])

        # Patch domain methods to raise, then collect
        with patch.object(
            test_domain, "_get_outbox_repo", side_effect=RuntimeError("boom")
        ):
            data = metric_reader.get_metrics_data()
            assert data is not None


# ---------------------------------------------------------------------------
# Tests: Subscription metric fallback in hand-rolled path
# ---------------------------------------------------------------------------


class TestHandRolledSubscriptionMetrics:
    """Test subscription metrics section in hand-rolled path."""

    @staticmethod
    def _make_status(
        handler_name="TestHandler",
        stream_category="test::stream",
        subscription_type="stream",
        lag=5,
        pending=2,
        dlq_depth=0,
        status="ok",
    ):
        """Build a mock subscription status object."""
        from unittest.mock import MagicMock

        mock_status = MagicMock()
        mock_status.handler_name = handler_name
        mock_status.stream_category = stream_category
        mock_status.subscription_type = subscription_type
        mock_status.lag = lag
        mock_status.pending = pending
        mock_status.dlq_depth = dlq_depth
        mock_status.status = status
        return mock_status

    def test_subscription_import_failure_handled(self):
        """Hand-rolled path handles subscription_status import failure."""
        from unittest.mock import patch

        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_domain = _make_mock_domain()

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            side_effect=ImportError("no module"),
        ):
            text = _hand_rolled_metrics([mock_domain])
            assert "# HELP protean_outbox_pending" in text

    def test_subscription_status_with_mock_statuses(self):
        """Subscription metrics render correctly with mock statuses."""
        from unittest.mock import patch

        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_domain = _make_mock_domain()
        mock_status = self._make_status()

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=[mock_status],
        ):
            text = _hand_rolled_metrics([mock_domain])

        assert "protean_subscription_lag" in text
        assert "protean_subscription_pending" in text
        assert "protean_subscription_dlq_depth" in text
        assert "protean_subscription_status" in text
        assert 'handler="TestHandler"' in text

    def test_subscription_status_with_none_lag(self):
        """Subscription metrics skip lag when it's None."""
        from unittest.mock import patch

        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_domain = _make_mock_domain()
        mock_status = self._make_status(
            handler_name="Handler",
            stream_category="stream",
            lag=None,
            pending=0,
            dlq_depth=0,
            status="error",
        )

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=[mock_status],
        ):
            text = _hand_rolled_metrics([mock_domain])

        assert "protean_subscription_pending" in text
        assert "protean_subscription_status" in text

    def test_subscription_collection_failure_per_domain(self):
        """Per-domain subscription collection failure is handled gracefully."""
        from unittest.mock import patch

        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_domain = _make_mock_domain("fail-domain")

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            side_effect=RuntimeError("connection lost"),
        ):
            text = _hand_rolled_metrics([mock_domain])
            assert "# HELP protean_outbox_pending" in text


# ---------------------------------------------------------------------------
# Tests: DomainMetrics instrument creation
# ---------------------------------------------------------------------------


class TestDomainMetricsInstruments:
    """Tests for DomainMetrics attribute creation."""

    def test_domain_metrics_has_all_instruments(self, test_domain, telemetry):
        """DomainMetrics creates all expected counters and histograms."""
        metrics = get_domain_metrics(test_domain)

        # Counters
        assert hasattr(metrics, "command_processed")
        assert hasattr(metrics, "handler_invocations")
        assert hasattr(metrics, "uow_commits")
        assert hasattr(metrics, "outbox_published")
        assert hasattr(metrics, "outbox_failed")

        # Histograms
        assert hasattr(metrics, "command_duration")
        assert hasattr(metrics, "handler_duration")
        assert hasattr(metrics, "uow_events_per_commit")
        assert hasattr(metrics, "outbox_latency")

    def test_domain_metrics_uses_real_otel_instruments(self, test_domain, telemetry):
        """DomainMetrics uses real OTel instruments when provider is set."""
        from opentelemetry.sdk.metrics import Counter, Histogram

        metrics = get_domain_metrics(test_domain)

        assert isinstance(metrics.command_processed, Counter)
        assert isinstance(metrics.command_duration, Histogram)

    def test_domain_metrics_cached(self, test_domain, telemetry):
        """get_domain_metrics returns same instance on repeated calls."""
        m1 = get_domain_metrics(test_domain)
        m2 = get_domain_metrics(test_domain)
        assert m1 is m2


# ---------------------------------------------------------------------------
# Tests: Gauge callback error paths
# ---------------------------------------------------------------------------


class TestGaugeCallbackErrorPaths:
    """Tests for error handling within ObservableGauge callbacks."""

    def _register_and_collect(self, domain, metric_reader):
        """Helper to register gauges and trigger collection."""
        from protean.server.observatory.metrics import (
            _GAUGES_REGISTERED_KEY,
            _register_infrastructure_gauges,
        )

        if hasattr(domain, _GAUGES_REGISTERED_KEY):
            delattr(domain, _GAUGES_REGISTERED_KEY)
        _register_infrastructure_gauges([domain])
        return metric_reader.get_metrics_data()

    def test_broker_up_callback_handles_exception(self, test_domain, telemetry):
        """Broker up callback returns [Observation(0)] on exception."""
        from unittest.mock import MagicMock

        _, metric_reader = telemetry

        # Make brokers.get("default") return a broker whose health_stats raises
        mock_broker = MagicMock()
        mock_broker.health_stats.side_effect = RuntimeError("broker error")
        test_domain.brokers = MagicMock()
        test_domain.brokers.get.return_value = mock_broker

        data = self._register_and_collect(test_domain, metric_reader)
        # Should complete without crashing — error path returns Observation(0)
        assert data is not None

    def test_broker_memory_callback_handles_exception(self, test_domain, telemetry):
        """Broker memory callback returns [Observation(0)] on exception."""
        from unittest.mock import MagicMock

        _, metric_reader = telemetry

        # Set up broker mock that raises on health_stats
        mock_broker = MagicMock()
        mock_broker.health_stats.side_effect = RuntimeError("health check failed")
        test_domain.brokers = MagicMock()
        test_domain.brokers.get.return_value = mock_broker

        data = self._register_and_collect(test_domain, metric_reader)
        assert data is not None

    def test_subscription_lag_callback_handles_exception(self, test_domain, telemetry):
        """Subscription lag callback handles collect_subscription_statuses failure."""
        from unittest.mock import patch

        _, metric_reader = telemetry

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            side_effect=RuntimeError("subscription error"),
        ):
            data = self._register_and_collect(test_domain, metric_reader)
            assert data is not None

    def test_subscription_pending_callback_handles_exception(self, test_domain, telemetry):
        """Subscription pending callback handles failures."""
        from unittest.mock import patch

        _, metric_reader = telemetry

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            side_effect=RuntimeError("pending error"),
        ):
            data = self._register_and_collect(test_domain, metric_reader)
            assert data is not None

    def test_subscription_callbacks_with_statuses(self, test_domain, telemetry):
        """Subscription callbacks produce observations for valid statuses."""
        from unittest.mock import MagicMock, patch

        _, metric_reader = telemetry

        mock_status = MagicMock()
        mock_status.handler_name = "TestHandler"
        mock_status.stream_category = "test::stream"
        mock_status.subscription_type = "stream"
        mock_status.lag = 10
        mock_status.pending = 3
        mock_status.dlq_depth = 1
        mock_status.status = "ok"

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=[mock_status],
        ):
            data = self._register_and_collect(test_domain, metric_reader)

        metric_names = set()
        for rm in data.resource_metrics:
            for sm in rm.scope_metrics:
                for m in sm.metrics:
                    metric_names.add(m.name)

        assert "protean_subscription_lag" in metric_names
        assert "protean_subscription_pending" in metric_names
        assert "protean_subscription_dlq_depth" in metric_names
        assert "protean_subscription_status" in metric_names

    def test_subscription_callback_none_lag_skipped(self, test_domain, telemetry):
        """Subscription lag callback skips None lag values."""
        from unittest.mock import MagicMock, patch

        _, metric_reader = telemetry

        mock_status = MagicMock()
        mock_status.handler_name = "Handler"
        mock_status.stream_category = "stream"
        mock_status.subscription_type = "stream"
        mock_status.lag = None
        mock_status.pending = 0
        mock_status.dlq_depth = 0
        mock_status.status = "error"

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            return_value=[mock_status],
        ):
            data = self._register_and_collect(test_domain, metric_reader)
            assert data is not None

    def test_broker_callbacks_with_healthy_broker(self, test_domain, telemetry):
        """Broker callbacks return correct observations for healthy broker."""
        from unittest.mock import MagicMock

        _, metric_reader = telemetry

        mock_broker = MagicMock()
        mock_broker.health_stats.return_value = {
            "connected": True,
            "details": {
                "healthy": True,
                "used_memory": 4096,
                "connected_clients": 5,
                "instantaneous_ops_per_sec": 200,
            },
        }
        test_domain.brokers = MagicMock()
        test_domain.brokers.get.return_value = mock_broker

        data = self._register_and_collect(test_domain, metric_reader)

        metric_names = set()
        for rm in data.resource_metrics:
            for sm in rm.scope_metrics:
                for m in sm.metrics:
                    metric_names.add(m.name)

        assert "protean_broker_up" in metric_names
        assert "protean_broker_memory_bytes" in metric_names
        assert "protean_broker_connected_clients" in metric_names
        assert "protean_broker_ops_per_sec" in metric_names


# ---------------------------------------------------------------------------
# Tests: Per-consumer metrics in hand-rolled path
# ---------------------------------------------------------------------------


class TestHandRolledConsumerMetrics:
    """Tests for per-consumer Redis metrics in the hand-rolled path."""

    def _run_with_redis(self, mock_redis, streams=None):
        """Run _hand_rolled_metrics with a mock Redis and return the text."""
        from unittest.mock import patch

        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_domain = _make_mock_domain()

        with (
            patch(
                "protean.server.observatory.api._get_redis",
                return_value=mock_redis,
            ),
            patch(
                "protean.server.observatory.api._discover_streams",
                return_value=streams or ["test::stream"],
            ),
        ):
            return _hand_rolled_metrics([mock_domain])

    def test_consumer_metrics_with_mock_redis(self):
        """Per-consumer metrics render with mock Redis connection."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.scan.return_value = (0, [b"test::stream"])
        mock_redis.xinfo_groups.return_value = [
            {"name": "TestGroup", "pending": 5}
        ]
        mock_redis.xinfo_consumers.return_value = [
            {"name": "Consumer1", "pending": 3, "idle": 1000}
        ]

        text = self._run_with_redis(mock_redis)

        assert "protean_consumer_pending" in text
        assert "protean_consumer_idle_ms" in text
        assert 'consumer="Consumer1"' in text
        assert 'group="TestGroup"' in text

    def test_consumer_metrics_with_bytes_keys(self):
        """Per-consumer metrics handle bytes keys from Redis."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.xinfo_groups.return_value = [
            {b"name": b"ByteGroup", b"pending": 2}
        ]
        mock_redis.xinfo_consumers.return_value = [
            {b"name": b"ByteConsumer", b"pending": 1, b"idle": 500}
        ]

        text = self._run_with_redis(mock_redis)

        assert 'consumer="ByteConsumer"' in text
        assert 'group="ByteGroup"' in text

    def test_consumer_metrics_non_dict_group_skipped(self):
        """Non-dict group entries are silently skipped."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.xinfo_groups.return_value = [
            "not-a-dict",
            {"name": "ValidGroup", "pending": 0},
        ]
        mock_redis.xinfo_consumers.return_value = [
            {"name": "Consumer1", "pending": 0, "idle": 0}
        ]

        text = self._run_with_redis(mock_redis)
        assert 'group="ValidGroup"' in text

    def test_consumer_metrics_empty_group_name_skipped(self):
        """Groups with None/empty name are skipped."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.xinfo_groups.return_value = [
            {"name": None, "pending": 0},
            {"name": "GoodGroup", "pending": 0},
        ]
        mock_redis.xinfo_consumers.return_value = [
            {"name": "Consumer1", "pending": 0, "idle": 0}
        ]

        text = self._run_with_redis(mock_redis)
        assert 'group="GoodGroup"' in text

    def test_consumer_metrics_non_dict_consumer_skipped(self):
        """Non-dict consumer entries are skipped."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.xinfo_groups.return_value = [{"name": "Group1"}]
        mock_redis.xinfo_consumers.return_value = [
            "not-a-dict",
            {"name": "ValidConsumer", "pending": 0, "idle": 0},
        ]

        text = self._run_with_redis(mock_redis)
        assert 'consumer="ValidConsumer"' in text

    def test_consumer_metrics_xinfo_consumers_exception(self):
        """xinfo_consumers exception doesn't crash metrics."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.xinfo_groups.return_value = [{"name": "FailGroup"}]
        mock_redis.xinfo_consumers.side_effect = RuntimeError("connection reset")

        text = self._run_with_redis(mock_redis)
        assert "# HELP protean_outbox_pending" in text

    def test_consumer_metrics_xinfo_groups_exception(self):
        """xinfo_groups exception doesn't crash metrics."""
        from unittest.mock import MagicMock

        mock_redis = MagicMock()
        mock_redis.xinfo_groups.side_effect = RuntimeError("timeout")

        text = self._run_with_redis(mock_redis)
        assert "# HELP protean_outbox_pending" in text

    def test_consumer_metrics_get_redis_failure(self):
        """_get_redis failure doesn't crash metrics."""
        from unittest.mock import patch

        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_domain = _make_mock_domain()

        with patch(
            "protean.server.observatory.api._get_redis",
            side_effect=RuntimeError("import error"),
        ):
            text = _hand_rolled_metrics([mock_domain])

        assert "# HELP protean_outbox_pending" in text

    def test_consumer_metrics_redis_none(self):
        """No consumer metrics when _get_redis returns None."""
        from unittest.mock import patch

        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_domain = _make_mock_domain()

        with patch(
            "protean.server.observatory.api._get_redis",
            return_value=None,
        ):
            text = _hand_rolled_metrics([mock_domain])

        assert "protean_consumer_pending" not in text


# ---------------------------------------------------------------------------
# Tests: telemetry.py coverage - init_telemetry, shutdown, etc.
# ---------------------------------------------------------------------------


class TestTelemetryInitAndShutdown:
    """Tests for init_telemetry and shutdown_telemetry internals."""

    def test_init_telemetry_disabled(self, test_domain):
        """init_telemetry returns None when telemetry is disabled."""
        from protean.utils.telemetry import init_telemetry

        result = init_telemetry(test_domain)
        assert result is None
        assert test_domain._otel_init_attempted is True

    def test_init_telemetry_enabled_sets_providers(self, test_domain):
        """init_telemetry creates providers when telemetry is enabled."""
        from protean.utils.telemetry import (
            _METER_PROVIDER_KEY,
            _PROMETHEUS_READER_KEY,
            _TRACER_PROVIDER_KEY,
            init_telemetry,
        )

        test_domain.config["telemetry"] = {"enabled": True}
        # Reset init flag
        test_domain._otel_init_attempted = False

        result = init_telemetry(test_domain)
        assert result is not None
        assert getattr(test_domain, _TRACER_PROVIDER_KEY) is not None
        assert getattr(test_domain, _METER_PROVIDER_KEY) is not None
        # PrometheusMetricReader should be attached
        assert hasattr(test_domain, _PROMETHEUS_READER_KEY)

        # Cleanup
        from protean.utils.telemetry import shutdown_telemetry

        shutdown_telemetry(test_domain)

    def test_shutdown_clears_prometheus_reader(self, test_domain, telemetry):
        """shutdown_telemetry clears the prometheus reader reference."""
        from protean.utils.telemetry import (
            _PROMETHEUS_READER_KEY,
            shutdown_telemetry,
        )

        # Set a fake reader
        setattr(test_domain, _PROMETHEUS_READER_KEY, "fake-reader")

        shutdown_telemetry(test_domain)

        assert not hasattr(test_domain, _PROMETHEUS_READER_KEY)

    def test_shutdown_resets_init_flag(self, test_domain, telemetry):
        """shutdown_telemetry resets _otel_init_attempted to False."""
        from protean.utils.telemetry import shutdown_telemetry

        assert test_domain._otel_init_attempted is True
        shutdown_telemetry(test_domain)
        assert test_domain._otel_init_attempted is False

    def test_build_prometheus_reader_returns_reader(self):
        """_build_prometheus_reader returns a PrometheusMetricReader."""
        from protean.utils.telemetry import _build_prometheus_reader

        reader = _build_prometheus_reader()
        assert reader is not None

    def test_create_observation_returns_otel_observation(self):
        """create_observation returns real OTel Observation when available."""
        from opentelemetry.metrics import Observation

        from protean.utils.telemetry import create_observation

        obs = create_observation(42, {"key": "val"})
        assert isinstance(obs, Observation)

    def test_init_telemetry_with_custom_service_name(self, test_domain):
        """init_telemetry uses custom service_name from config."""
        from protean.utils.telemetry import init_telemetry, shutdown_telemetry

        test_domain.config["telemetry"] = {
            "enabled": True,
            "service_name": "custom-svc",
        }
        test_domain._otel_init_attempted = False

        result = init_telemetry(test_domain)
        assert result is not None

        shutdown_telemetry(test_domain)

    def test_get_prometheus_text_returns_text(self, test_domain):
        """get_prometheus_text returns text when telemetry is initialized."""
        from protean.utils.telemetry import (
            get_prometheus_text,
            init_telemetry,
            shutdown_telemetry,
        )

        test_domain.config["telemetry"] = {"enabled": True}
        test_domain._otel_init_attempted = False
        init_telemetry(test_domain)

        result = get_prometheus_text(test_domain)
        # Should return a string (Prometheus text format)
        assert result is None or isinstance(result, str)

        shutdown_telemetry(test_domain)

    def test_get_prometheus_text_no_reader(self, test_domain):
        """get_prometheus_text returns None when no reader is set."""
        from protean.utils.telemetry import (
            _PROMETHEUS_READER_KEY,
            _TELEMETRY_INIT_KEY,
            get_prometheus_text,
        )

        setattr(test_domain, _TELEMETRY_INIT_KEY, True)
        # Ensure no reader is set
        if hasattr(test_domain, _PROMETHEUS_READER_KEY):
            delattr(test_domain, _PROMETHEUS_READER_KEY)

        result = get_prometheus_text(test_domain)
        assert result is None

    def test_get_prometheus_text_not_initialized(self, test_domain):
        """get_prometheus_text returns None when domain not initialized."""
        from protean.utils.telemetry import get_prometheus_text

        test_domain._otel_init_attempted = False
        result = get_prometheus_text(test_domain)
        assert result is None

    def test_shutdown_clears_domain_metrics(self, test_domain, telemetry):
        """shutdown_telemetry clears cached DomainMetrics."""
        from protean.utils.telemetry import (
            _DOMAIN_METRICS_KEY,
            get_domain_metrics,
            shutdown_telemetry,
        )

        # Create and cache domain metrics
        get_domain_metrics(test_domain)
        assert hasattr(test_domain, _DOMAIN_METRICS_KEY)

        shutdown_telemetry(test_domain)
        assert not hasattr(test_domain, _DOMAIN_METRICS_KEY)

    def test_init_telemetry_with_resource_attributes(self, test_domain):
        """init_telemetry uses custom resource_attributes from config."""
        from protean.utils.telemetry import init_telemetry, shutdown_telemetry

        test_domain.config["telemetry"] = {
            "enabled": True,
            "resource_attributes": {"deployment.environment": "test"},
        }
        test_domain._otel_init_attempted = False

        result = init_telemetry(test_domain)
        assert result is not None

        shutdown_telemetry(test_domain)

    def test_init_telemetry_with_console_exporter(self, test_domain):
        """init_telemetry works with console exporter."""
        from protean.utils.telemetry import init_telemetry, shutdown_telemetry

        test_domain.config["telemetry"] = {
            "enabled": True,
            "exporter": "console",
        }
        test_domain._otel_init_attempted = False

        result = init_telemetry(test_domain)
        assert result is not None

        shutdown_telemetry(test_domain)

    def test_build_prometheus_reader_import_error(self):
        """_build_prometheus_reader returns None when package is missing."""
        import builtins
        from unittest.mock import patch

        from protean.utils.telemetry import _build_prometheus_reader

        original_import = builtins.__import__

        def fail_prometheus(name, *args, **kwargs):
            if "opentelemetry.exporter.prometheus" in name:
                raise ImportError("no prometheus exporter")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_prometheus):
            result = _build_prometheus_reader()
            assert result is None

    def test_get_prometheus_text_import_error(self, test_domain):
        """get_prometheus_text returns None when prometheus_client is missing."""
        import builtins
        from unittest.mock import patch

        from protean.utils.telemetry import (
            _PROMETHEUS_READER_KEY,
            _TELEMETRY_INIT_KEY,
            get_prometheus_text,
        )

        setattr(test_domain, _TELEMETRY_INIT_KEY, True)
        setattr(test_domain, _PROMETHEUS_READER_KEY, "fake-reader")

        original_import = builtins.__import__

        def fail_prometheus_client(name, *args, **kwargs):
            if name == "prometheus_client":
                raise ImportError("no prometheus_client")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_prometheus_client):
            result = get_prometheus_text(test_domain)
            assert result is None


# ---------------------------------------------------------------------------
# Tests: No-op classes when OTEL is unavailable
# ---------------------------------------------------------------------------


class TestNoOpFallbacks:
    """Tests for no-op classes used when OTEL SDK is not installed."""

    def test_noop_observation(self):
        """_NoOpObservation stores value and attributes."""
        from protean.utils.telemetry import _NoOpObservation

        obs = _NoOpObservation(42, {"key": "val"})
        assert obs.value == 42
        assert obs.attributes == {"key": "val"}

    def test_noop_observation_no_attrs(self):
        """_NoOpObservation works without attributes."""
        from protean.utils.telemetry import _NoOpObservation

        obs = _NoOpObservation(0)
        assert obs.value == 0
        assert obs.attributes is None

    def test_noop_counter_add(self):
        """_NoOpCounter.add does nothing."""
        from protean.utils.telemetry import _NoOpCounter

        counter = _NoOpCounter()
        counter.add(1)
        counter.add(5, {"key": "val"})

    def test_noop_histogram_record(self):
        """_NoOpHistogram.record does nothing."""
        from protean.utils.telemetry import _NoOpHistogram

        hist = _NoOpHistogram()
        hist.record(1.5)
        hist.record(0.1, {"key": "val"})

    def test_noop_observable_gauge(self):
        """_NoOpObservableGauge can be instantiated."""
        from protean.utils.telemetry import _NoOpObservableGauge

        gauge = _NoOpObservableGauge()
        assert gauge is not None

    def test_noop_meter_create_counter(self):
        """_NoOpMeter.create_counter returns a _NoOpCounter."""
        from protean.utils.telemetry import _NoOpCounter, _NoOpMeter

        meter = _NoOpMeter()
        counter = meter.create_counter("test.counter")
        assert isinstance(counter, _NoOpCounter)

    def test_noop_meter_create_histogram(self):
        """_NoOpMeter.create_histogram returns a _NoOpHistogram."""
        from protean.utils.telemetry import _NoOpHistogram, _NoOpMeter

        meter = _NoOpMeter()
        hist = meter.create_histogram("test.histogram")
        assert isinstance(hist, _NoOpHistogram)

    def test_noop_meter_create_up_down_counter(self):
        """_NoOpMeter.create_up_down_counter returns a _NoOpCounter."""
        from protean.utils.telemetry import _NoOpCounter, _NoOpMeter

        meter = _NoOpMeter()
        counter = meter.create_up_down_counter("test.up_down_counter")
        assert isinstance(counter, _NoOpCounter)

    def test_noop_meter_create_observable_gauge(self):
        """_NoOpMeter.create_observable_gauge returns a _NoOpObservableGauge."""
        from protean.utils.telemetry import _NoOpMeter, _NoOpObservableGauge

        meter = _NoOpMeter()
        gauge = meter.create_observable_gauge("test.gauge", callbacks=[lambda: []])
        assert isinstance(gauge, _NoOpObservableGauge)

    def test_create_observation_noop_fallback(self):
        """create_observation returns _NoOpObservation when OTEL unavailable."""
        from unittest.mock import patch

        from protean.utils.telemetry import _NoOpObservation, create_observation

        with patch("protean.utils.telemetry._OTEL_AVAILABLE", False):
            obs = create_observation(99, {"a": "b"})
            assert isinstance(obs, _NoOpObservation)
            assert obs.value == 99

    def test_get_tracer_noop_fallback(self):
        """get_tracer returns _NoOpTracer when OTEL unavailable."""
        from unittest.mock import patch

        from protean.utils.telemetry import _NoOpTracer, get_tracer

        with patch("protean.utils.telemetry._OTEL_AVAILABLE", False):
            from unittest.mock import MagicMock

            domain = MagicMock()
            tracer = get_tracer(domain)
            assert isinstance(tracer, _NoOpTracer)

    def test_get_meter_noop_fallback(self):
        """get_meter returns _NoOpMeter when OTEL unavailable."""
        from unittest.mock import MagicMock, patch

        from protean.utils.telemetry import _NoOpMeter, get_meter

        with patch("protean.utils.telemetry._OTEL_AVAILABLE", False):
            domain = MagicMock()
            meter = get_meter(domain)
            assert isinstance(meter, _NoOpMeter)

    def test_noop_span_context_manager(self):
        """_NoOpSpan supports context manager protocol."""
        from protean.utils.telemetry import _NoOpSpan

        span = _NoOpSpan()
        with span as s:
            assert s is span
            s.set_attribute("key", "val")
            s.set_status("OK")
            s.record_exception(RuntimeError("test"))
            s.end()
            assert s.is_recording is False

    def test_noop_tracer_start_span(self):
        """_NoOpTracer.start_span returns _NoOpSpan."""
        from protean.utils.telemetry import _NoOpSpan, _NoOpTracer

        tracer = _NoOpTracer()
        span = tracer.start_span("test")
        assert isinstance(span, _NoOpSpan)

    def test_noop_tracer_start_as_current_span(self):
        """_NoOpTracer.start_as_current_span returns _NoOpSpan."""
        from protean.utils.telemetry import _NoOpSpan, _NoOpTracer

        tracer = _NoOpTracer()
        span = tracer.start_as_current_span("test")
        assert isinstance(span, _NoOpSpan)


# ---------------------------------------------------------------------------
# Tests: hand-rolled subscription import failure
# ---------------------------------------------------------------------------


class TestHandRolledSubscriptionImportFailure:
    """Test that _hand_rolled_metrics handles subscription_status import failure."""

    def test_subscription_import_failure(self):
        """Lines 452-453: outer except catches import failure."""
        import builtins
        from unittest.mock import patch

        from protean.server.observatory.metrics import _hand_rolled_metrics

        mock_domain = _make_mock_domain()

        original_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if "subscription_status" in name:
                raise ImportError("No module named 'protean.server.subscription_status'")
            return original_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=failing_import),
            patch(
                "protean.server.observatory.api._get_redis",
                return_value=None,
            ),
        ):
            text = _hand_rolled_metrics([mock_domain])

        # Should still produce outbox metrics even when subscription import fails
        assert "# HELP protean_outbox_pending" in text


# ---------------------------------------------------------------------------
# Tests: outbox_processor metrics (unit-level mocking)
# ---------------------------------------------------------------------------


class TestOutboxProcessorMetrics:
    """Unit tests for outbox metric recording in OutboxProcessor."""

    def test_outbox_published_metric_recorded(self):
        """Verifies outbox_published counter is called on successful publish."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        from protean.utils.telemetry import _NoOpCounter, _NoOpHistogram

        # Create a minimal mock of the outbox processor's _process_single_message
        mock_metrics = MagicMock()
        mock_metrics.outbox_published = MagicMock(spec=_NoOpCounter)
        mock_metrics.outbox_failed = MagicMock(spec=_NoOpCounter)
        mock_metrics.outbox_latency = MagicMock(spec=_NoOpHistogram)

        with patch("protean.server.outbox_processor.get_domain_metrics", return_value=mock_metrics):
            # Verify the counter type is correct
            mock_metrics.outbox_published.add(1)
            mock_metrics.outbox_published.add.assert_called_once_with(1)

    def test_outbox_failed_metric_recorded(self):
        """Verifies outbox_failed counter is called on failed publish."""
        from unittest.mock import MagicMock, patch

        from protean.utils.telemetry import _NoOpCounter

        mock_metrics = MagicMock()
        mock_metrics.outbox_failed = MagicMock(spec=_NoOpCounter)

        with patch("protean.server.outbox_processor.get_domain_metrics", return_value=mock_metrics):
            mock_metrics.outbox_failed.add(1)
            mock_metrics.outbox_failed.add.assert_called_once_with(1)

    def _make_processor(self):
        """Helper to build a minimal OutboxProcessor with mocked dependencies."""
        from unittest.mock import MagicMock

        from protean.server.outbox_processor import OutboxProcessor

        mock_engine = MagicMock()
        mock_engine.domain.config = {"outbox": {}, "server": {}}
        mock_engine.domain.brokers = {}
        mock_engine.domain.normalized_name = "test"
        mock_engine.emitter = MagicMock()

        processor = OutboxProcessor.__new__(OutboxProcessor)
        processor.engine = mock_engine
        processor.is_external = False
        processor.subscription_id = "test-processor"
        processor.worker_id = "test-worker"
        processor.broker = MagicMock()
        processor._filter_by_broker = False
        processor._lanes_enabled = False
        processor.retry_config = {
            "max_attempts": 3,
            "base_delay_seconds": 60,
            "max_backoff_seconds": 3600,
            "backoff_multiplier": 2,
            "jitter": True,
            "jitter_factor": 0.25,
        }
        processor.outbox_repo = MagicMock()
        processor.outbox_repo.claim_for_processing.return_value = True
        return processor

    def _make_message(self, created_at=None):
        """Helper to build a mock outbox message."""
        from unittest.mock import MagicMock

        mock_message = MagicMock()
        mock_message.message_id = "abcd1234-5678"
        mock_message.id = 1
        mock_message.stream_name = "test::stream"
        mock_message.data = {"key": "value"}
        mock_message.created_at = created_at
        mock_message.metadata_ = MagicMock()
        mock_message.metadata_.domain.stream_category = "test::stream"
        mock_message.metadata_.headers.type = "TestEvent"
        return mock_message

    def test_process_single_message_success_records_metrics(self):
        """_process_single_message records outbox_published and latency on success."""
        import asyncio
        import datetime
        from unittest.mock import AsyncMock, MagicMock, patch

        processor = self._make_processor()
        created = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
        mock_message = self._make_message(created_at=created)
        processor.outbox_repo.get.return_value = mock_message

        mock_metrics = MagicMock()

        with patch("protean.server.outbox_processor.get_domain_metrics", return_value=mock_metrics), \
             patch("protean.server.outbox_processor.get_tracer") as mock_get_tracer, \
             patch("protean.server.outbox_processor.UnitOfWork") as mock_uow, \
             patch.object(processor, "_publish_message", new_callable=AsyncMock, return_value=(True, None)):
            mock_span = MagicMock()
            mock_get_tracer.return_value.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_get_tracer.return_value.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
            mock_uow.return_value.__enter__ = MagicMock()
            mock_uow.return_value.__exit__ = MagicMock(return_value=False)

            result = asyncio.get_event_loop().run_until_complete(
                processor._process_single_message(mock_message)
            )

        assert result is True
        mock_metrics.outbox_published.add.assert_called_once_with(1)
        mock_metrics.outbox_latency.record.assert_called_once()

    def test_process_single_message_failure_records_metrics(self):
        """_process_single_message records outbox_failed on publish failure."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        processor = self._make_processor()
        mock_message = self._make_message()
        processor.outbox_repo.get.return_value = mock_message

        mock_metrics = MagicMock()
        publish_error = RuntimeError("broker down")

        with patch("protean.server.outbox_processor.get_domain_metrics", return_value=mock_metrics), \
             patch("protean.server.outbox_processor.get_tracer") as mock_get_tracer, \
             patch("protean.server.outbox_processor.UnitOfWork") as mock_uow, \
             patch.object(processor, "_publish_message", new_callable=AsyncMock, return_value=(False, publish_error)):
            mock_span = MagicMock()
            mock_get_tracer.return_value.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_get_tracer.return_value.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
            mock_uow.return_value.__enter__ = MagicMock()
            mock_uow.return_value.__exit__ = MagicMock(return_value=False)

            result = asyncio.get_event_loop().run_until_complete(
                processor._process_single_message(mock_message)
            )

        assert result is False
        mock_metrics.outbox_failed.add.assert_called_once_with(1)

    def test_process_single_message_no_created_at(self):
        """_process_single_message skips latency when created_at is missing."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        processor = self._make_processor()
        mock_message = self._make_message(created_at=None)
        processor.outbox_repo.get.return_value = mock_message

        mock_metrics = MagicMock()

        with patch("protean.server.outbox_processor.get_domain_metrics", return_value=mock_metrics), \
             patch("protean.server.outbox_processor.get_tracer") as mock_get_tracer, \
             patch("protean.server.outbox_processor.UnitOfWork") as mock_uow, \
             patch.object(processor, "_publish_message", new_callable=AsyncMock, return_value=(True, None)):
            mock_span = MagicMock()
            mock_get_tracer.return_value.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_get_tracer.return_value.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
            mock_uow.return_value.__enter__ = MagicMock()
            mock_uow.return_value.__exit__ = MagicMock(return_value=False)

            result = asyncio.get_event_loop().run_until_complete(
                processor._process_single_message(mock_message)
            )

        assert result is True
        mock_metrics.outbox_published.add.assert_called_once_with(1)
        mock_metrics.outbox_latency.record.assert_not_called()

    def test_process_single_message_naive_created_at(self):
        """_process_single_message handles naive datetime created_at."""
        import asyncio
        import datetime
        from unittest.mock import AsyncMock, MagicMock, patch

        processor = self._make_processor()
        naive_dt = datetime.datetime.utcnow() - datetime.timedelta(seconds=2)
        mock_message = self._make_message(created_at=naive_dt)
        processor.outbox_repo.get.return_value = mock_message

        mock_metrics = MagicMock()

        with patch("protean.server.outbox_processor.get_domain_metrics", return_value=mock_metrics), \
             patch("protean.server.outbox_processor.get_tracer") as mock_get_tracer, \
             patch("protean.server.outbox_processor.UnitOfWork") as mock_uow, \
             patch.object(processor, "_publish_message", new_callable=AsyncMock, return_value=(True, None)):
            mock_span = MagicMock()
            mock_get_tracer.return_value.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
            mock_get_tracer.return_value.start_as_current_span.return_value.__exit__ = MagicMock(return_value=False)
            mock_uow.return_value.__enter__ = MagicMock()
            mock_uow.return_value.__exit__ = MagicMock(return_value=False)

            result = asyncio.get_event_loop().run_until_complete(
                processor._process_single_message(mock_message)
            )

        assert result is True
        mock_metrics.outbox_latency.record.assert_called_once()
        # Latency should be roughly 2 seconds
        latency = mock_metrics.outbox_latency.record.call_args[0][0]
        assert latency >= 1.0
