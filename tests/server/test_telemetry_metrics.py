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

import builtins
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.metrics import Observation
from opentelemetry.sdk.metrics import Counter, Histogram
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from protean.adapters.broker.redis import RedisBroker
from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.exceptions import CommandExpiredError
from protean.fields import Identifier, String
from protean.server import Engine
from protean.server.observatory.metrics import (
    _GAUGES_REGISTERED_KEY,
    _hand_rolled_metrics,
    _register_infrastructure_gauges,
    _scrape_cache,
    create_metrics_endpoint,
)
from protean.server.outbox_processor import OutboxProcessor
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.globals import current_domain
from protean.utils.mixins import handle
from protean.utils.outbox import Outbox
from protean.utils.telemetry import (
    _DOMAIN_METRICS_KEY,
    _METER_PROVIDER_KEY,
    _PROMETHEUS_READER_KEY,
    _TELEMETRY_INIT_KEY,
    _TRACER_PROVIDER_KEY,
    DomainMetrics,
    _build_prometheus_reader,
    _NoOpCounter,
    _NoOpHistogram,
    _NoOpMeter,
    _NoOpObservableGauge,
    _NoOpObservation,
    _NoOpSpan,
    _NoOpTracer,
    create_observation,
    get_domain_metrics,
    get_meter,
    get_prometheus_text,
    get_tracer,
    init_telemetry,
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


@pytest.fixture(autouse=True)
def _clear_scrape_cache():
    """Clear the per-scrape metrics cache between tests."""
    _scrape_cache.clear()


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


def _metric_names(data) -> set[str]:
    """Return the names of every metric in a metrics snapshot."""
    return {
        metric.name
        for resource_metric in data.resource_metrics
        for scope_metric in resource_metric.scope_metrics
        for metric in scope_metric.metrics
    }


def _points_in(data, name: str) -> list:
    """Return the data points of metric ``name`` in a metrics snapshot."""
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == name:
                    return list(metric.data.data_points)
    return []


def _register_gauges_and_collect(domain, metric_reader):
    """Register the infrastructure gauges and return one metrics snapshot."""
    if hasattr(domain, _GAUGES_REGISTERED_KEY):
        delattr(domain, _GAUGES_REGISTERED_KEY)
    _register_infrastructure_gauges([domain])
    return metric_reader.get_metrics_data()


def _enqueue_open_account(test_domain) -> None:
    """Write one OpenAccount command to its stream without handling it.

    ``AccountCommandHandler`` then trails the stream head, so its lag is a
    known number, while ``AccountWithEventHandler`` has no messages and an
    unknown (None) lag.
    """
    test_domain.config["command_processing"] = "async"
    test_domain.process(
        OpenAccount(account_id=str(uuid4()), name="Queued"),
        asynchronous=True,
    )


class RedisServer:
    """Stands in for the Redis server behind a real ``RedisBroker``.

    It answers the commands the broker health check and the Observatory
    scrape send: PING, INFO, TYPE, XLEN, SCAN, XINFO GROUPS and
    XINFO CONSUMERS.
    """

    def __init__(
        self,
        info=None,
        streams=None,
        groups=None,
        consumers=None,
        groups_error=None,
        consumers_error=None,
    ):
        self._info = info or {}
        self._streams = streams or {}
        self._groups = groups or []
        self._consumers = consumers or []
        self._groups_error = groups_error
        self._consumers_error = consumers_error

    def ping(self):
        return True

    def info(self):
        return self._info

    def type(self, key):
        return b"stream" if key in self._streams else b"none"

    def xlen(self, key):
        return self._streams[key]

    def scan(self, cursor=0, count=None, _type=None):
        return 0, [name.encode() for name in self._streams]

    def xgroup_create(self, stream, group, id=None, mkstream=False):
        return True

    def xinfo_groups(self, stream):
        if self._groups_error is not None:
            raise self._groups_error
        return self._groups

    def xinfo_consumers(self, stream, group):
        if self._consumers_error is not None:
            raise self._consumers_error
        return self._consumers


def _use_redis_broker(monkeypatch, domain, server: RedisServer) -> RedisBroker:
    """Make a real ``RedisBroker`` talking to ``server`` the default broker."""
    broker = RedisBroker("default", domain, {"URI": "redis://localhost:6379/0"})
    broker.redis_instance = server
    monkeypatch.setitem(domain.brokers, "default", broker)
    return broker


def _fail(*args, **kwargs):
    raise RuntimeError("broker down")


# ---------------------------------------------------------------------------
# Tests: Command, handler and UoW metrics
# ---------------------------------------------------------------------------


class TestCommandMetrics:
    """Processing a command records command, handler and UoW metrics."""

    def test_sync_success_records_command_handler_and_uow_metrics(
        self, test_domain, telemetry
    ):
        _, metric_reader = telemetry

        for _ in range(3):
            test_domain.process(
                OpenAccount(account_id=str(uuid4()), name="Corp"),
                asynchronous=False,
            )

        data = metric_reader.get_metrics_data()

        processed = _points_in(data, "protean.command.processed")
        ok_points = [p for p in processed if dict(p.attributes).get("status") == "ok"]
        assert len(ok_points) == 1
        assert ok_points[0].value == 3
        assert "OpenAccount" in dict(ok_points[0].attributes)["command_type"]

        duration = _points_in(data, "protean.command.duration")
        ok_points = [p for p in duration if dict(p.attributes).get("status") == "ok"]
        assert len(ok_points) == 1
        assert ok_points[0].sum > 0
        assert ok_points[0].count == 3

        invocations = _points_in(data, "protean.handler.invocations")
        ok_points = [p for p in invocations if dict(p.attributes).get("status") == "ok"]
        assert len(ok_points) == 1
        assert ok_points[0].value == 3
        assert dict(ok_points[0].attributes)["handler_name"] == "AccountCommandHandler"

        handler_duration = _points_in(data, "protean.handler.duration")
        ok_points = [
            p for p in handler_duration if dict(p.attributes).get("status") == "ok"
        ]
        assert len(ok_points) == 1
        assert ok_points[0].sum > 0
        assert ok_points[0].count == 3

        commits = _points_in(data, "protean.uow.commits")
        assert sum(p.value for p in commits) >= 3

        # OpenAccount raises no events, so each commit records zero events.
        events_per_commit = _points_in(data, "protean.uow.events_per_commit")
        assert len(events_per_commit) >= 1
        assert sum(p.sum for p in events_per_commit) == 0

    def test_sync_error_records_error_status(self, test_domain, telemetry):
        _, metric_reader = telemetry

        with pytest.raises(RuntimeError, match="handler exploded"):
            test_domain.process(
                FailingCommand(account_id=str(uuid4())),
                asynchronous=False,
            )

        data = metric_reader.get_metrics_data()

        def error_points(name):
            return [
                p
                for p in _points_in(data, name)
                if dict(p.attributes).get("status") == "error"
            ]

        (processed,) = error_points("protean.command.processed")
        assert processed.value == 1

        (duration,) = error_points("protean.command.duration")
        assert duration.sum > 0

        (invocations,) = error_points("protean.handler.invocations")
        assert invocations.value == 1
        assert dict(invocations.attributes)["handler_name"] == "FailingCommandHandler"

        (handler_duration,) = error_points("protean.handler.duration")
        assert handler_duration.sum > 0

    def test_async_path_records_enqueued_status(self, test_domain, telemetry):
        _, metric_reader = telemetry

        # Force async processing so the async path is taken
        test_domain.config["command_processing"] = "async"

        test_domain.process(
            OpenAccount(account_id=str(uuid4()), name="Async Corp"),
            asynchronous=True,
        )

        data = metric_reader.get_metrics_data()

        (processed,) = [
            p
            for p in _points_in(data, "protean.command.processed")
            if dict(p.attributes).get("status") == "enqueued"
        ]
        assert processed.value == 1

        (duration,) = [
            p
            for p in _points_in(data, "protean.command.duration")
            if dict(p.attributes).get("status") == "enqueued"
        ]
        assert duration.sum > 0

    def test_sync_expiry_increments_expired_counter(self, test_domain, telemetry):
        _, metric_reader = telemetry

        past = datetime.now(UTC) - timedelta(seconds=1)
        with pytest.raises(CommandExpiredError):
            test_domain.process(
                OpenAccount(account_id=str(uuid4()), name="Acme"),
                asynchronous=False,
                deadline=past,
            )

        points = _get_metric_data_points(metric_reader, "protean.command.expired")
        assert len(points) == 1
        assert points[0].value == 1
        assert "OpenAccount" in dict(points[0].attributes)["command_type"]

    def test_command_with_events_records_event_count(self, test_domain, telemetry):
        _, metric_reader = telemetry

        test_domain.process(
            CreateAccountWithEvent(account_id=str(uuid4()), name="WithEvents"),
            asynchronous=False,
        )

        points = _get_metric_data_points(metric_reader, "protean.uow.events_per_commit")
        assert len(points) >= 1
        # At least one commit should have recorded events > 0
        total_events = sum(p.sum for p in points)
        assert total_events >= 1


# ---------------------------------------------------------------------------
# Tests: DomainMetrics caching
# ---------------------------------------------------------------------------


class TestDomainMetricsCaching:
    """DomainMetrics is cached per domain and cleaned up on shutdown."""

    def test_returns_one_cached_instance_of_real_instruments(
        self, test_domain, telemetry
    ):
        m1 = get_domain_metrics(test_domain)
        m2 = get_domain_metrics(test_domain)

        assert m1 is m2
        assert isinstance(m1, DomainMetrics)
        for name in (
            "command_processed",
            "handler_invocations",
            "uow_commits",
            "outbox_published",
            "outbox_failed",
        ):
            assert isinstance(getattr(m1, name), Counter)
        for name in (
            "command_duration",
            "handler_duration",
            "uow_events_per_commit",
            "outbox_latency",
        ):
            assert isinstance(getattr(m1, name), Histogram)

    def test_shutdown_clears_cache_and_reinit_recreates_metrics(
        self, test_domain, telemetry
    ):
        m1 = get_domain_metrics(test_domain)
        assert hasattr(test_domain, _DOMAIN_METRICS_KEY)

        shutdown_telemetry(test_domain)
        assert not hasattr(test_domain, _DOMAIN_METRICS_KEY)

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
        account_id = str(uuid4())
        result = test_domain.process(
            OpenAccount(account_id=account_id, name="NoTelemetry"),
            asynchronous=False,
        )
        assert result == {"opened": account_id}

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
# Tests: Metrics endpoint and Prometheus text
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    """The /metrics endpoint serves OTel text when telemetry is enabled."""

    @pytest.mark.asyncio
    async def test_endpoint_falls_back_to_hand_rolled_text(self, test_domain):
        """Without telemetry the endpoint serves hand-rolled Prometheus text."""
        endpoint = create_metrics_endpoint([test_domain])

        response = await endpoint()

        assert response.status_code == 200
        assert "text/plain" in response.media_type
        body = response.body.decode("utf-8")
        assert "# HELP protean_outbox_pending_count" in body
        assert body.endswith("\n")

    @pytest.mark.asyncio
    async def test_endpoint_serves_otel_text(self, test_domain, telemetry):
        """Endpoint serves OTel Prometheus text when telemetry is enabled."""
        setattr(test_domain, _PROMETHEUS_READER_KEY, PrometheusMetricReader())

        endpoint = create_metrics_endpoint([test_domain])
        response = await endpoint()

        assert len(response.body.decode("utf-8")) > 0
        assert "text/plain" in response.media_type

    def test_get_prometheus_text_with_reader(self, test_domain, telemetry):
        setattr(test_domain, _PROMETHEUS_READER_KEY, PrometheusMetricReader())

        result = get_prometheus_text(test_domain)

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.parametrize(
        "case", ["non_domain", "not_initialized", "initialized_without_reader"]
    )
    def test_get_prometheus_text_returns_none(self, test_domain, case):
        if case == "non_domain":
            target = object()
        elif case == "not_initialized":
            test_domain._otel_init_attempted = False
            target = test_domain
        else:
            _init_telemetry_in_memory(test_domain)
            assert not hasattr(test_domain, _PROMETHEUS_READER_KEY)
            target = test_domain

        assert get_prometheus_text(target) is None


# ---------------------------------------------------------------------------
# Tests: _hand_rolled_metrics
# ---------------------------------------------------------------------------


class TestHandRolledMetrics:
    """Tests for _hand_rolled_metrics using the real test_domain."""

    def test_outbox_and_broker_metrics(self, test_domain, monkeypatch):
        """Hand-rolled metrics render outbox and Redis broker sections."""
        broker = _use_redis_broker(
            monkeypatch,
            test_domain,
            RedisServer(
                info={
                    "used_memory": 2048,
                    "connected_clients": 3,
                    "instantaneous_ops_per_sec": 100,
                },
                streams={"test::stream": 50},
                groups=[{"name": "TestGroup", "pending": 2}],
            ),
        )
        broker._ensure_group("TestGroup", "test::stream")

        text = _hand_rolled_metrics([test_domain])

        assert f'domain="{test_domain.name}"' in text
        assert "protean_broker_up 1" in text
        assert "protean_broker_memory_bytes 2048" in text
        assert "protean_broker_connected_clients 3" in text
        assert "protean_broker_ops_per_sec 100" in text
        assert "protean_stream_messages_total 50" in text
        assert "protean_stream_pending 2" in text

    def test_outbox_query_failure_gracefully_handled(self, test_domain, monkeypatch):
        """Hand-rolled metrics handle outbox query failure."""
        monkeypatch.setattr(test_domain, "_get_outbox_repo", _fail)

        text = _hand_rolled_metrics([test_domain])

        assert "# HELP protean_outbox_pending_count" in text

    def test_broker_query_failure_gracefully_handled(self, test_domain, monkeypatch):
        """Hand-rolled metrics handle broker query failure."""
        with test_domain.domain_context():
            broker = test_domain.brokers.get("default")
        monkeypatch.setattr(broker, "health_stats", _fail)

        text = _hand_rolled_metrics([test_domain])

        assert "# HELP protean_outbox_pending_count" in text
        assert "protean_broker_up" not in text


# ---------------------------------------------------------------------------
# Tests: Subscription metrics in hand-rolled path
# ---------------------------------------------------------------------------


class TestHandRolledSubscriptionMetrics:
    """Test subscription metrics section in hand-rolled path."""

    def test_subscription_status_rendering(self, test_domain):
        """Each subscription renders pending, DLQ and status lines; only a
        known lag renders a consumer_lag line."""
        _enqueue_open_account(test_domain)

        text = _hand_rolled_metrics([test_domain])

        assert "protean_subscription_consumer_lag" in text
        assert "protean_subscription_pending_messages" in text
        assert "protean_subscription_dlq_depth" in text
        assert "protean_subscription_status" in text
        assert 'handler="AccountCommandHandler"' in text
        assert 'handler="AccountWithEventHandler"' in text

        lag_lines = [
            line
            for line in text.split("\n")
            if line.startswith("protean_subscription_consumer_lag{")
        ]
        assert any('handler="AccountCommandHandler"' in line for line in lag_lines)
        # AccountWithEventHandler's lag is None, so it gets no lag line.
        assert not any(
            'handler="AccountWithEventHandler"' in line for line in lag_lines
        )

    @pytest.mark.parametrize(
        "error", [ImportError("no module"), RuntimeError("connection lost")]
    )
    def test_subscription_collection_failure_handled(self, test_domain, error):
        """A failing subscription collection does not stop the scrape."""
        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            side_effect=error,
        ):
            text = _hand_rolled_metrics([test_domain])

        assert "# HELP protean_outbox_pending_count" in text

    def test_subscription_import_failure(self, test_domain):
        """Outer except catches import failure gracefully."""
        original_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if "subscription_status" in name:
                raise ImportError(
                    "No module named 'protean.server.subscription_status'"
                )
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=failing_import):
            text = _hand_rolled_metrics([test_domain])

        # Should still produce outbox metrics even when subscription import fails
        assert "# HELP protean_outbox_pending_count" in text


# ---------------------------------------------------------------------------
# Tests: Per-consumer metrics in hand-rolled path
# ---------------------------------------------------------------------------


class TestHandRolledConsumerMetrics:
    """Tests for per-consumer Redis metrics in the hand-rolled path."""

    def test_consumer_metrics_skip_malformed_entries(self, test_domain, monkeypatch):
        """Valid groups and consumers render; non-dict entries and groups
        without a name are skipped."""
        _use_redis_broker(
            monkeypatch,
            test_domain,
            RedisServer(
                streams={"test::stream": 1},
                groups=[
                    "not-a-dict",
                    {"name": None, "pending": 0},
                    {"name": "TestGroup", "pending": 5},
                ],
                consumers=[
                    "not-a-dict",
                    {"name": "Consumer1", "pending": 3, "idle": 1000},
                ],
            ),
        )

        text = _hand_rolled_metrics([test_domain])

        assert "protean_consumer_pending" in text
        assert "protean_consumer_idle_ms" in text
        assert 'consumer="Consumer1"' in text
        assert 'group="TestGroup"' in text
        assert 'group="None"' not in text

    def test_consumer_metrics_with_bytes_keys(self, test_domain, monkeypatch):
        """Per-consumer metrics handle bytes keys from Redis."""
        _use_redis_broker(
            monkeypatch,
            test_domain,
            RedisServer(
                streams={"test::stream": 1},
                groups=[{b"name": b"ByteGroup", b"pending": 2}],
                consumers=[{b"name": b"ByteConsumer", b"pending": 1, b"idle": 500}],
            ),
        )

        text = _hand_rolled_metrics([test_domain])

        assert 'consumer="ByteConsumer"' in text
        assert 'group="ByteGroup"' in text

    @pytest.mark.parametrize(
        "server_kwargs",
        [
            {
                "groups": [{"name": "FailGroup"}],
                "consumers_error": RuntimeError("connection reset"),
            },
            {"groups_error": RuntimeError("timeout")},
        ],
        ids=["xinfo_consumers", "xinfo_groups"],
    )
    def test_consumer_metrics_redis_error(
        self, test_domain, monkeypatch, server_kwargs
    ):
        """A Redis error while reading groups or consumers does not stop the
        scrape."""
        _use_redis_broker(
            monkeypatch,
            test_domain,
            RedisServer(streams={"test::stream": 1}, **server_kwargs),
        )

        text = _hand_rolled_metrics([test_domain])

        assert "# HELP protean_outbox_pending_count" in text

    def test_consumer_metrics_get_redis_failure(self, test_domain):
        """_get_redis failure doesn't crash metrics."""
        with patch(
            "protean.server.observatory.api._get_redis",
            side_effect=RuntimeError("import error"),
        ):
            text = _hand_rolled_metrics([test_domain])

        assert "# HELP protean_outbox_pending_count" in text

    def test_no_consumer_metrics_without_redis(self, test_domain):
        """The inline broker has no Redis connection, so no consumer metrics."""
        text = _hand_rolled_metrics([test_domain])

        assert "protean_consumer_pending" not in text


# ---------------------------------------------------------------------------
# Tests: ObservableGauge callbacks with telemetry active
# ---------------------------------------------------------------------------


class TestGaugeCallbacks:
    """Tests for ObservableGauge callback functions."""

    def test_gauges_report_outbox_and_inline_broker(self, test_domain, telemetry):
        _, metric_reader = telemetry

        data = _register_gauges_and_collect(test_domain, metric_reader)

        names = _metric_names(data)
        assert "protean.outbox.pending_count" in names
        assert "protean_broker_up" in names
        (outbox,) = _points_in(data, "protean.outbox.pending_count")
        assert outbox.value == 0
        (broker_up,) = _points_in(data, "protean_broker_up")
        assert broker_up.value == 1

    def test_broker_gauges_report_redis_stats(
        self, test_domain, telemetry, monkeypatch
    ):
        _, metric_reader = telemetry
        _use_redis_broker(
            monkeypatch,
            test_domain,
            RedisServer(
                info={
                    "used_memory": 4096,
                    "connected_clients": 5,
                    "instantaneous_ops_per_sec": 200,
                }
            ),
        )

        data = _register_gauges_and_collect(test_domain, metric_reader)

        assert [p.value for p in _points_in(data, "protean_broker_up")] == [1]
        assert [p.value for p in _points_in(data, "protean_broker_memory_bytes")] == [
            4096
        ]
        assert [
            p.value for p in _points_in(data, "protean_broker_connected_clients")
        ] == [5]
        assert [p.value for p in _points_in(data, "protean_broker_ops_per_sec")] == [
            200
        ]

    def test_broker_gauges_report_zero_when_health_check_raises(
        self, test_domain, telemetry, monkeypatch
    ):
        _, metric_reader = telemetry
        with test_domain.domain_context():
            broker = test_domain.brokers.get("default")
        monkeypatch.setattr(broker, "health_stats", _fail)

        data = _register_gauges_and_collect(test_domain, metric_reader)

        for name in (
            "protean_broker_up",
            "protean_broker_memory_bytes",
            "protean_broker_connected_clients",
            "protean_broker_ops_per_sec",
        ):
            assert [p.value for p in _points_in(data, name)] == [0]

    def test_outbox_gauge_skips_domain_when_query_raises(
        self, test_domain, telemetry, monkeypatch
    ):
        _, metric_reader = telemetry
        monkeypatch.setattr(test_domain, "_get_outbox_repo", _fail)

        data = _register_gauges_and_collect(test_domain, metric_reader)

        assert _points_in(data, "protean.outbox.pending_count") == []

    def test_subscription_gauges_report_statuses(self, test_domain, telemetry):
        """The four subscription gauges are registered, and the lag gauge has no
        point for a subscription whose lag is None."""
        _, metric_reader = telemetry
        _enqueue_open_account(test_domain)

        data = _register_gauges_and_collect(test_domain, metric_reader)

        names = _metric_names(data)
        assert "protean.subscription.consumer_lag" in names
        assert "protean.subscription.pending_messages" in names
        assert "protean_subscription_dlq_depth" in names
        assert "protean_subscription_status" in names

        lag_handlers = {
            p.attributes["handler"]
            for p in _points_in(data, "protean.subscription.consumer_lag")
        }
        assert "AccountCommandHandler" in lag_handlers
        assert "AccountWithEventHandler" not in lag_handlers

    def test_subscription_gauges_empty_when_collection_raises(
        self, test_domain, telemetry
    ):
        _, metric_reader = telemetry

        with patch(
            "protean.server.subscription_status.collect_subscription_statuses",
            side_effect=RuntimeError("subscription error"),
        ):
            data = _register_gauges_and_collect(test_domain, metric_reader)

        assert _points_in(data, "protean.subscription.consumer_lag") == []
        assert _points_in(data, "protean.subscription.pending_messages") == []


# ---------------------------------------------------------------------------
# Tests: telemetry init and shutdown
# ---------------------------------------------------------------------------


class TestTelemetryInitAndShutdown:
    """Tests for init_telemetry and shutdown_telemetry internals."""

    def test_init_telemetry_disabled(self, test_domain):
        """init_telemetry returns None when telemetry is disabled."""
        result = init_telemetry(test_domain)
        assert result is None
        assert test_domain._otel_init_attempted is True

    @pytest.mark.parametrize(
        "extra_config, resource_attribute",
        [
            ({}, None),
            ({"service_name": "custom-svc"}, ("service.name", "custom-svc")),
            (
                {"resource_attributes": {"deployment.environment": "test"}},
                ("deployment.environment", "test"),
            ),
            ({"exporter": "console"}, None),
        ],
        ids=["default", "service_name", "resource_attributes", "console_exporter"],
    )
    def test_init_sets_providers_and_shutdown_clears_them(
        self, test_domain, extra_config, resource_attribute
    ):
        test_domain.config["telemetry"] = {"enabled": True, **extra_config}
        test_domain._otel_init_attempted = False

        result = init_telemetry(test_domain)

        assert result is not None
        tracer_provider = getattr(test_domain, _TRACER_PROVIDER_KEY)
        assert tracer_provider is not None
        assert getattr(test_domain, _METER_PROVIDER_KEY) is not None
        assert hasattr(test_domain, _PROMETHEUS_READER_KEY)
        if resource_attribute is not None:
            key, value = resource_attribute
            assert tracer_provider.resource.attributes[key] == value
        text = get_prometheus_text(test_domain)
        assert isinstance(text, str)

        shutdown_telemetry(test_domain)

        assert not hasattr(test_domain, _PROMETHEUS_READER_KEY)
        assert test_domain._otel_init_attempted is False

    def test_build_prometheus_reader_returns_reader(self):
        """_build_prometheus_reader returns a PrometheusMetricReader."""
        assert isinstance(_build_prometheus_reader(), PrometheusMetricReader)

    def test_build_prometheus_reader_import_error(self):
        """_build_prometheus_reader returns None when package is missing."""
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
        setattr(test_domain, _TELEMETRY_INIT_KEY, True)
        setattr(test_domain, _PROMETHEUS_READER_KEY, PrometheusMetricReader())

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

    @pytest.mark.parametrize(
        "args, attributes", [((42, {"key": "val"}), {"key": "val"}), ((0,), None)]
    )
    def test_noop_observation(self, args, attributes):
        """_NoOpObservation stores value and attributes."""
        obs = _NoOpObservation(*args)
        assert obs.value == args[0]
        assert obs.attributes == attributes

    def test_noop_counter_add(self):
        """_NoOpCounter.add does nothing."""
        counter = _NoOpCounter()
        counter.add(1)
        counter.add(5, {"key": "val"})

    def test_noop_histogram_record(self):
        """_NoOpHistogram.record does nothing."""
        hist = _NoOpHistogram()
        hist.record(1.5)
        hist.record(0.1, {"key": "val"})

    def test_noop_observable_gauge(self):
        """_NoOpObservableGauge can be instantiated."""
        assert _NoOpObservableGauge() is not None

    @pytest.mark.parametrize(
        "method, kwargs, expected",
        [
            ("create_counter", {}, _NoOpCounter),
            ("create_histogram", {}, _NoOpHistogram),
            ("create_up_down_counter", {}, _NoOpCounter),
            ("create_observable_gauge", {"callbacks": [list]}, _NoOpObservableGauge),
        ],
    )
    def test_noop_meter_creates_noop_instruments(self, method, kwargs, expected):
        instrument = getattr(_NoOpMeter(), method)("test.instrument", **kwargs)
        assert isinstance(instrument, expected)

    def test_create_observation_returns_otel_observation(self):
        """create_observation returns real OTel Observation when available."""
        obs = create_observation(42, {"key": "val"})
        assert isinstance(obs, Observation)

    def test_create_observation_noop_fallback(self):
        """create_observation returns _NoOpObservation when OTEL unavailable."""
        with patch("protean.utils.telemetry._OTEL_AVAILABLE", False):
            obs = create_observation(99, {"a": "b"})
            assert isinstance(obs, _NoOpObservation)
            assert obs.value == 99

    def test_get_tracer_noop_fallback(self, test_domain):
        """get_tracer returns _NoOpTracer when OTEL unavailable."""
        with patch("protean.utils.telemetry._OTEL_AVAILABLE", False):
            tracer = get_tracer(test_domain)
            assert isinstance(tracer, _NoOpTracer)

    def test_get_meter_noop_fallback(self, test_domain):
        """get_meter returns _NoOpMeter when OTEL unavailable."""
        with patch("protean.utils.telemetry._OTEL_AVAILABLE", False):
            meter = get_meter(test_domain)
            assert isinstance(meter, _NoOpMeter)

    def test_noop_span_context_manager(self):
        """_NoOpSpan supports context manager protocol."""
        span = _NoOpSpan()
        with span as s:
            assert s is span
            s.set_attribute("key", "val")
            s.set_status("OK")
            s.record_exception(RuntimeError("test"))
            s.end()
            assert s.is_recording is False

    @pytest.mark.parametrize("method", ["start_span", "start_as_current_span"])
    def test_noop_tracer_returns_noop_span(self, method):
        span = getattr(_NoOpTracer(), method)("test")
        assert isinstance(span, _NoOpSpan)


# ---------------------------------------------------------------------------
# Tests: outbox processor metrics
# ---------------------------------------------------------------------------


def _add_outbox_row(domain, created_at: datetime | None = None) -> Outbox:
    """Store one pending outbox row, optionally with a given ``created_at``."""
    metadata = Metadata(
        headers=MessageHeaders(id="msg-1", type="AccountCreated", stream="test-stream"),
        domain=DomainMeta(stream_category="test-stream"),
    )
    row = Outbox.create_message(
        message_id="msg-1",
        stream_name="test-stream",
        message_type="AccountCreated",
        data={"account_id": "1", "name": "Acme"},
        metadata=metadata,
    )
    if created_at is not None:
        row.created_at = created_at
    with domain.domain_context():
        domain._get_outbox_repo("default").add(row)
    return row


async def _new_outbox_processor(domain) -> OutboxProcessor:
    processor = OutboxProcessor(
        Engine(domain=domain, test_mode=True), "default", "default"
    )
    await processor.initialize()
    return processor


async def _process_one_batch(processor: OutboxProcessor) -> int:
    messages = await processor.get_next_batch_of_messages()
    return await processor.process_batch(messages)


class TestOutboxProcessorMetrics:
    """OutboxProcessor records outbox metrics for each row it publishes."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "created_at",
        [
            datetime.now(UTC) - timedelta(seconds=2),
            datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=2),
        ],
        ids=["aware", "naive"],
    )
    async def test_published_row_records_count_and_latency(
        self, test_domain, telemetry, created_at
    ):
        _, metric_reader = telemetry
        _add_outbox_row(test_domain, created_at=created_at)

        assert await _process_one_batch(await _new_outbox_processor(test_domain)) == 1

        data = metric_reader.get_metrics_data()
        assert [p.value for p in _points_in(data, "protean.outbox.published")] == [1]
        (latency,) = _points_in(data, "protean.outbox.latency")
        assert latency.count == 1
        assert latency.sum >= 1.0

    @pytest.mark.asyncio
    async def test_publish_failure_records_failed_count(
        self, test_domain, telemetry, monkeypatch
    ):
        _, metric_reader = telemetry
        _add_outbox_row(test_domain)
        processor = await _new_outbox_processor(test_domain)
        monkeypatch.setattr(processor.broker, "publish", _fail)

        assert await _process_one_batch(processor) == 0

        data = metric_reader.get_metrics_data()
        assert [p.value for p in _points_in(data, "protean.outbox.failed")] == [1]
        assert _points_in(data, "protean.outbox.published") == []

    @pytest.mark.asyncio
    async def test_row_without_created_at_records_no_latency(
        self, test_domain, telemetry, monkeypatch
    ):
        """The Outbox model always sets ``created_at``, so the processor's
        guard for a row without one is reached only through a stand-in row."""
        _, metric_reader = telemetry
        _add_outbox_row(test_domain)
        processor = await _new_outbox_processor(test_domain)
        repo_get = processor.outbox_repo.get

        def get_without_created_at(identifier):
            row = repo_get(identifier)
            row.__dict__["created_at"] = None
            return row

        monkeypatch.setattr(processor.outbox_repo, "get", get_without_created_at)

        assert await _process_one_batch(processor) == 1

        data = metric_reader.get_metrics_data()
        assert [p.value for p in _points_in(data, "protean.outbox.published")] == [1]
        assert _points_in(data, "protean.outbox.latency") == []
