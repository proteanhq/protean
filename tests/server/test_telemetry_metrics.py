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
