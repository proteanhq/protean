"""Tests for Observatory Processes API endpoints and supporting functions.

Tests for:
- routes/processes.py: collect_pm_metadata, merge_pm_subscription_status,
  collect_pm_trace_metrics, get_pm_instance_count, get_pm_instances,
  _build_summary, create_processes_router
- templates/processes.html: structure and JS inclusion
- static/js/processes.js: file presence
"""

import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.core.value_object import BaseValueObject
from protean.fields import Identifier, String
from protean.server.observatory import Observatory
from protean.server.observatory.routes.processes import (
    _build_summary,
    _decode_stream_id,
    _extract_handled_messages,
    _extract_time,
    _get_redis,
    _serialize_pm,
    collect_pm_metadata,
    collect_pm_trace_metrics,
    create_processes_router,
    get_pm_instance_count,
    get_pm_instances,
    merge_pm_subscription_status,
)
from protean.utils import fqn
from protean.utils.eventing import Message
from protean.utils.mixins import handle
from tests.shared import FrozenClock

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def observatory(test_domain):
    return Observatory(domains=[test_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


def _register_fulfillment(domain, **pm_options):
    """Register an order-fulfillment process manager on ``domain`` and init it.

    The process manager listens to the ``order`` and ``shipment`` streams. It
    starts on ``OrderPlaced`` and completes on ``OrderShipped``.
    """

    class Order(BaseAggregate):
        customer_id = Identifier()

    class Shipment(BaseAggregate):
        order_id = Identifier()

    class OrderPlaced(BaseEvent):
        order_id = Identifier(required=True)

    class OrderShipped(BaseEvent):
        order_id = Identifier(required=True)

    class OrderFulfillment(BaseProcessManager):
        order_id = Identifier()
        status = String(default="new")

        @handle(OrderPlaced, start=True, correlate="order_id")
        def on_placed(self, event):
            self.order_id = event.order_id
            self.status = "started"

        @handle(OrderShipped, end=True, correlate="order_id")
        def on_shipped(self, event):
            self.status = "shipped"

    domain.register(Order)
    domain.register(Shipment)
    domain.register(OrderPlaced, part_of=Order)
    domain.register(OrderShipped, part_of=Shipment)
    domain.register(
        OrderFulfillment, stream_categories=["order", "shipment"], **pm_options
    )
    domain.init(traverse=False)

    return SimpleNamespace(
        domain=domain,
        pm=OrderFulfillment,
        Order=Order,
        Shipment=Shipment,
        OrderPlaced=OrderPlaced,
        OrderShipped=OrderShipped,
    )


def _deliver_latest(app, aggregate_cls, aggregate):
    """Save the aggregate, then hand its newest stored event to the process
    manager, the way the engine delivers it."""
    domain = app.domain
    with domain.domain_context():
        domain.repository_for(aggregate_cls).add(aggregate)
        store = domain.event_store.store
        stream = f"{aggregate_cls.meta_.stream_category}-{aggregate.id}"
        message = store.read(stream)[-1]
        app.pm._handle(message)


def _start_order(app):
    """Start one process-manager instance and return its correlation id."""
    order = app.Order(customer_id="c1")
    order.raise_(app.OrderPlaced(order_id=order.id))
    _deliver_latest(app, app.Order, order)
    return order.id


def _ship_order(app, order_id):
    """Complete the process-manager instance for ``order_id``."""
    shipment = app.Shipment(order_id=order_id)
    shipment.raise_(app.OrderShipped(order_id=order_id))
    _deliver_latest(app, app.Shipment, shipment)


@pytest.fixture
def fulfillment(test_domain):
    """The test domain with the order-fulfillment process manager registered.

    The test domain's default subscription type is ``stream``, so each of the
    two stream categories becomes a Redis stream subscription.
    """
    return _register_fulfillment(test_domain)


class _FakeRedisStreams:
    """Stands in for the raw ``redis.Redis`` client the broker holds.

    ``groups`` maps a stream name to its consumer-group entries, ``lengths``
    maps a stream name (including ``<stream>:dlq``) to its length.
    """

    def __init__(self, groups=None, lengths=None):
        self.groups = groups or {}
        self.lengths = lengths or {}

    def xlen(self, stream):
        return self.lengths.get(stream, 0)

    def xinfo_groups(self, stream):
        return self.groups.get(stream, [])

    def xrange(self, stream, min="-", max="+", count=None):
        return []


def _group(pm_cls, *, lag, pending=0, consumers=1):
    """One consumer-group entry for ``pm_cls``, shaped like ``XINFO GROUPS``."""
    return {
        "name": fqn(pm_cls),
        "pending": pending,
        "last-delivered-id": "1-0",
        "lag": lag,
        "consumers": consumers,
    }


def _make_trace_entry(
    event="handler.completed",
    handler="TestPM",
    duration_ms=25.0,
):
    """Create a serialized trace entry as Redis would return."""
    trace = {
        "event": event,
        "handler": handler,
        "duration_ms": duration_ms,
        "timestamp": time.time(),
    }
    return json.dumps(trace).encode("utf-8")


def _handler_class_with_keys(*type_keys):
    """A class carrying only a ``_handlers`` map with the given keys."""
    return type("KeyedHandler", (), {"_handlers": {k: set() for k in type_keys}})


# ---------------------------------------------------------------------------
# _extract_handled_messages
# ---------------------------------------------------------------------------


class TestExtractHandledMessages:
    def test_empty_handlers(self, test_domain):
        @test_domain.event_handler(part_of=test_domain.aggregate(type("Idle", (), {})))
        class IdleHandler(BaseEventHandler):
            pass

        test_domain.init(traverse=False)
        assert _extract_handled_messages(IdleHandler) == []

    def test_no_handlers_attr(self):
        assert _extract_handled_messages(object) == []

    def test_extracts_short_names(self, fulfillment):
        result = _extract_handled_messages(fulfillment.pm)
        assert result == ["OrderPlaced", "OrderShipped"]

    def test_skips_dollar_any(self, test_domain):
        @test_domain.aggregate
        class Ledger(BaseAggregate):
            name = String()

        @test_domain.event(part_of=Ledger)
        class LedgerOpened(BaseEvent):
            name = String()

        @test_domain.event_handler(part_of=Ledger)
        class LedgerAudit(BaseEventHandler):
            @handle("$any")
            def on_any(self, event):
                pass

            @handle(LedgerOpened)
            def on_opened(self, event):
                pass

        test_domain.init(traverse=False)
        assert "$any" in LedgerAudit._handlers
        assert _extract_handled_messages(LedgerAudit) == ["LedgerOpened"]


# ---------------------------------------------------------------------------
# collect_pm_metadata
# ---------------------------------------------------------------------------


class TestCollectPMMetadata:
    def test_empty_domain(self, test_domain):
        assert collect_pm_metadata([test_domain]) == []

    def test_single_pm(self, fulfillment, test_domain):
        result = collect_pm_metadata([test_domain])
        assert len(result) == 1
        pm = result[0]
        assert pm["name"] == "OrderFulfillment"
        assert pm["qualname"] == fqn(fulfillment.pm)
        assert pm["type"] == "process_manager"
        assert pm["domain"] == "Observatory Tests"
        assert pm["stream_category"] == "observatory_tests::order_fulfillment"
        assert pm["stream_categories"] == [
            "observatory_tests::order",
            "observatory_tests::shipment",
        ]
        assert pm["handled_messages"] == ["OrderPlaced", "OrderShipped"]
        assert pm["subscription"] is None
        assert pm["metrics"] is None
        assert pm["_cls"] is fulfillment.pm
        assert pm["_domain"] is test_domain

    def test_multiple_pms_across_domains(self, fulfillment, test_domain):
        other = _register_fulfillment(Domain(name="Other"))

        result = collect_pm_metadata([test_domain, other.domain])
        assert len(result) == 2
        assert {p["domain"] for p in result} == {"Observatory Tests", "Other"}
        assert {p["_cls"] for p in result} == {fulfillment.pm, other.pm}


# ---------------------------------------------------------------------------
# merge_pm_subscription_status
# ---------------------------------------------------------------------------


def _use_redis(domain, fake):
    """Point the domain's Redis broker at a fake raw client."""
    return patch.object(domain.brokers.get("default"), "redis_instance", fake)


class TestMergePMSubscriptionStatus:
    def test_no_statuses(self, test_domain):
        pms = [{"name": "PM1", "type": "process_manager", "subscription": None}]

        merge_pm_subscription_status(pms, [test_domain])

        assert pms[0]["subscription"] is None

    def test_matches_by_handler_name(self, fulfillment, test_domain):
        pm_cls = fulfillment.pm
        order, shipment = pm_cls.meta_.stream_categories
        fake = _FakeRedisStreams(
            groups={
                order: [_group(pm_cls, lag=5, pending=2)],
                shipment: [_group(pm_cls, lag=0)],
            }
        )
        pms = collect_pm_metadata([test_domain])

        with _use_redis(test_domain, fake):
            merge_pm_subscription_status(pms, [test_domain])

        sub = pms[0]["subscription"]
        assert sub is not None
        assert sub["status"] == "lagging"
        assert sub["lag"] == 5
        assert sub["pending"] == 2
        assert sub["consumer_count"] == 1
        assert sub["subscription_type"] == "stream"

    def test_all_caught_up_is_ok(self, fulfillment, test_domain):
        pm_cls = fulfillment.pm
        order, shipment = pm_cls.meta_.stream_categories
        fake = _FakeRedisStreams(
            groups={
                order: [_group(pm_cls, lag=0)],
                shipment: [_group(pm_cls, lag=0)],
            }
        )
        pms = collect_pm_metadata([test_domain])

        with _use_redis(test_domain, fake):
            merge_pm_subscription_status(pms, [test_domain])

        assert pms[0]["subscription"]["status"] == "ok"
        assert pms[0]["subscription"]["lag"] == 0

    def test_aggregates_multiple_subscriptions(self, fulfillment, test_domain):
        pm_cls = fulfillment.pm
        order, shipment = pm_cls.meta_.stream_categories
        fake = _FakeRedisStreams(
            groups={
                order: [_group(pm_cls, lag=3, pending=1, consumers=1)],
                shipment: [_group(pm_cls, lag=10, pending=5, consumers=2)],
            },
            lengths={f"{shipment}:dlq": 2},
        )
        pms = collect_pm_metadata([test_domain])

        with _use_redis(test_domain, fake):
            merge_pm_subscription_status(pms, [test_domain])

        sub = pms[0]["subscription"]
        assert sub["lag"] == 13
        assert sub["pending"] == 6
        assert sub["dlq_depth"] == 2
        assert sub["consumer_count"] == 2
        assert sub["status"] == "lagging"

    def test_worst_status_unknown(self, fulfillment, test_domain):
        """One stream lags and the other has no consumer group, so its lag is
        unknown. The process manager reports the worse of the two: unknown."""
        pm_cls = fulfillment.pm
        order, _shipment = pm_cls.meta_.stream_categories
        fake = _FakeRedisStreams(groups={order: [_group(pm_cls, lag=5)]})
        pms = collect_pm_metadata([test_domain])

        with _use_redis(test_domain, fake):
            merge_pm_subscription_status(pms, [test_domain])

        assert pms[0]["subscription"]["status"] == "unknown"
        assert pms[0]["subscription"]["lag"] == 5

    def test_lag_seconds_is_max_not_sum(self, test_domain):
        """Seconds-lag aggregates as the worst (max) stream staleness, not a sum."""
        app = _register_fulfillment(test_domain, subscription_type="event_store")
        pm_cls = app.pm
        store = test_domain.event_store.store
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

        # Each stream gets one checkpoint at position 0, then one event past it,
        # so both lag. The order checkpoint is 30s old, the shipment one 4s old.
        for category, written_at in zip(
            pm_cls.meta_.stream_categories,
            [start, start + timedelta(seconds=26)],
            strict=True,
        ):
            test_domain.clock = FrozenClock(written_at)
            store._write(f"position-{fqn(pm_cls)}-{category}", "Read", {"position": 0})
        order_id = _start_order(app)
        _ship_order(app, order_id)

        test_domain.clock = FrozenClock(start + timedelta(seconds=30))
        pms = collect_pm_metadata([test_domain])
        merge_pm_subscription_status(pms, [test_domain])

        sub = pms[0]["subscription"]
        assert sub["subscription_type"] == "event_store"
        assert sub["status"] == "lagging"
        assert sub["lag_seconds"] == 30.0  # max, not 34.0

    def test_lag_seconds_none_when_all_none(self, fulfillment, test_domain):
        """Stream subscriptions report no seconds, so the aggregate stays None
        (unavailable)."""
        pm_cls = fulfillment.pm
        order, shipment = pm_cls.meta_.stream_categories
        fake = _FakeRedisStreams(
            groups={
                order: [_group(pm_cls, lag=3)],
                shipment: [_group(pm_cls, lag=1)],
            }
        )
        pms = collect_pm_metadata([test_domain])

        with _use_redis(test_domain, fake):
            merge_pm_subscription_status(pms, [test_domain])

        assert pms[0]["subscription"]["lag"] == 4
        assert pms[0]["subscription"]["lag_seconds"] is None

    def test_handles_collection_exception(self, fulfillment, test_domain):
        pms = collect_pm_metadata([test_domain])

        with patch(
            "protean.server.observatory.routes.processes.collect_subscription_statuses",
            side_effect=Exception("fail"),
        ):
            # Should not raise
            merge_pm_subscription_status(pms, [test_domain])

        assert pms[0]["subscription"] is None


# ---------------------------------------------------------------------------
# collect_pm_trace_metrics
# ---------------------------------------------------------------------------


class TestCollectPMTraceMetrics:
    def test_no_redis(self):
        assert collect_pm_trace_metrics(None, {"PM1"}, 300000) == {}

    def test_no_pm_names(self):
        assert collect_pm_trace_metrics(MagicMock(), set(), 300000) == {}

    def test_single_completed_event(self):
        now_ms = int(time.time() * 1000)
        redis = MagicMock()
        redis.xrange.return_value = [
            (
                f"{now_ms - 5000}-0".encode(),
                {b"data": _make_trace_entry(handler="PM1", duration_ms=30.0)},
            ),
        ]

        result = collect_pm_trace_metrics(redis, {"PM1"}, 300000)
        assert "PM1" in result
        assert result["PM1"]["processed"] == 1
        assert result["PM1"]["failed"] == 0
        assert result["PM1"]["avg_latency_ms"] == 30.0

    def test_error_events(self):
        now_ms = int(time.time() * 1000)
        redis = MagicMock()
        redis.xrange.return_value = [
            (
                f"{now_ms - 5000}-0".encode(),
                {b"data": _make_trace_entry(event="handler.failed", handler="PM1")},
            ),
            (
                f"{now_ms - 4000}-0".encode(),
                {b"data": _make_trace_entry(event="message.dlq", handler="PM1")},
            ),
        ]

        result = collect_pm_trace_metrics(redis, {"PM1"}, 300000)
        assert result["PM1"]["failed"] == 2
        assert result["PM1"]["processed"] == 0

    def test_filters_by_pm_names(self):
        now_ms = int(time.time() * 1000)
        redis = MagicMock()
        redis.xrange.return_value = [
            (
                f"{now_ms - 5000}-0".encode(),
                {b"data": _make_trace_entry(handler="PM1")},
            ),
            (
                f"{now_ms - 4000}-0".encode(),
                {b"data": _make_trace_entry(handler="NotAPM")},
            ),
        ]

        result = collect_pm_trace_metrics(redis, {"PM1"}, 300000)
        assert "PM1" in result
        assert "NotAPM" not in result

    def test_handles_xrange_exception(self):
        redis = MagicMock()
        redis.xrange.side_effect = Exception("Redis error")
        result = collect_pm_trace_metrics(redis, {"PM1"}, 300000)
        assert result == {}


# ---------------------------------------------------------------------------
# get_pm_instance_count
# ---------------------------------------------------------------------------


@pytest.fixture
def plain_value_object(test_domain):
    """A real element whose ``meta_`` has no stream category."""

    @test_domain.value_object
    class Money(BaseValueObject):
        currency = String()

    return Money


def _fail_stream_identifiers(domain):
    """Make the event store fail to list stream identifiers."""
    return patch.object(
        domain.event_store.store,
        "_stream_identifiers",
        side_effect=Exception("fail"),
    )


class TestGetPMInstanceCount:
    def test_no_meta(self, test_domain):
        assert get_pm_instance_count(test_domain, object) is None

    def test_no_stream_category(self, test_domain, plain_value_object):
        assert get_pm_instance_count(test_domain, plain_value_object) is None

    def test_returns_count(self, fulfillment, test_domain):
        for _ in range(3):
            _start_order(fulfillment)

        assert get_pm_instance_count(test_domain, fulfillment.pm) == 3

    def test_handles_exception(self, fulfillment, test_domain):
        _start_order(fulfillment)

        with _fail_stream_identifiers(test_domain):
            assert get_pm_instance_count(test_domain, fulfillment.pm) is None


# ---------------------------------------------------------------------------
# get_pm_instances
# ---------------------------------------------------------------------------


class TestGetPMInstances:
    def test_no_meta(self, test_domain):
        assert get_pm_instances(test_domain, object) == []

    def test_no_stream_category(self, test_domain, plain_value_object):
        assert get_pm_instances(test_domain, plain_value_object) == []

    def test_returns_instances(self, fulfillment, test_domain):
        order_id = _start_order(fulfillment)
        _ship_order(fulfillment, order_id)

        result = get_pm_instances(test_domain, fulfillment.pm)
        assert len(result) == 1
        inst = result[0]
        assert inst["instance_id"] == order_id
        assert inst["version"] == 2
        assert inst["is_complete"] is True
        assert inst["state"]["status"] == "shipped"
        assert inst["event_count"] == 2

    def test_empty_stream(self, fulfillment, test_domain):
        """A stream from another category whose name ends with the process
        manager's category is listed as an identifier, but the process
        manager's own stream for it is empty, so no instance is returned."""
        store = test_domain.event_store.store
        category = fulfillment.pm.meta_.stream_category
        store._write(f"legacy_{category}-id1", "Noted", {})

        assert store._stream_identifiers(category) == ["id1"]
        assert get_pm_instances(test_domain, fulfillment.pm) == []

    def test_respects_limit(self, fulfillment, test_domain):
        for _ in range(5):
            _start_order(fulfillment)

        result = get_pm_instances(test_domain, fulfillment.pm, limit=3)
        assert len(result) == 3

    def test_handles_stream_identifiers_exception(self, fulfillment, test_domain):
        _start_order(fulfillment)

        with _fail_stream_identifiers(test_domain):
            assert get_pm_instances(test_domain, fulfillment.pm) == []


# ---------------------------------------------------------------------------
# _build_summary
# ---------------------------------------------------------------------------


class TestBuildSummary:
    def test_empty_list(self):
        summary = _build_summary([])
        assert summary["total"] == 0
        assert summary["total_instances"] == 0
        assert summary["healthy"] == 0

    def test_counts_statuses(self):
        pms = [
            {"subscription": {"status": "ok"}, "instance_count": 10, "metrics": None},
            {
                "subscription": {"status": "lagging"},
                "instance_count": 5,
                "metrics": None,
            },
            {"subscription": None, "instance_count": None, "metrics": None},
        ]
        summary = _build_summary(pms)
        assert summary["total"] == 3
        assert summary["healthy"] == 1
        assert summary["lagging"] == 1
        assert summary["unknown"] == 1
        assert summary["total_instances"] == 15

    def test_accumulates_metrics(self):
        pms = [
            {
                "subscription": {"status": "ok"},
                "instance_count": 5,
                "metrics": {"processed": 100, "failed": 3},
            },
            {
                "subscription": {"status": "ok"},
                "instance_count": 10,
                "metrics": {"processed": 200, "failed": 7},
            },
        ]
        summary = _build_summary(pms)
        assert summary["total_processed"] == 300
        assert summary["total_errors"] == 10


# ---------------------------------------------------------------------------
# _serialize_pm
# ---------------------------------------------------------------------------


class TestSerializePM:
    def test_keeps_public_keys_and_strips_internal_keys(self, fulfillment, test_domain):
        pm = {
            "name": "TestPM",
            "type": "process_manager",
            "metrics": {"processed": 5},
            "_cls": fulfillment.pm,
            "_domain": test_domain,
        }
        assert _serialize_pm(pm) == {
            "name": "TestPM",
            "type": "process_manager",
            "metrics": {"processed": 5},
        }


# ---------------------------------------------------------------------------
# Endpoint: /api/processes
# ---------------------------------------------------------------------------


class TestProcessesListEndpoint:
    def test_returns_shape(self, client):
        resp = client.get("/api/processes")
        assert resp.status_code == 200
        data = resp.json()
        assert "processes" in data
        assert "summary" in data
        assert "window" in data

    def test_invalid_window(self, client):
        resp = client.get("/api/processes?window=invalid")
        assert resp.status_code == 400

    def test_lists_registered_process_manager(self, fulfillment, client):
        _start_order(fulfillment)

        resp = client.get("/api/processes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["processes"]) == 1
        assert data["processes"][0]["name"] == "OrderFulfillment"
        assert data["processes"][0]["instance_count"] == 1
        assert data["summary"]["total_instances"] == 1
        # Internal keys should not be serialized
        assert "_cls" not in data["processes"][0]
        assert "_domain" not in data["processes"][0]


# ---------------------------------------------------------------------------
# Endpoint: /api/processes/{name}/instances
# ---------------------------------------------------------------------------


class TestProcessesInstancesEndpoint:
    def test_not_found(self, client):
        resp = client.get("/api/processes/NonExistentPM/instances")
        assert resp.status_code == 404

    def test_returns_instances(self, fulfillment, client):
        order_id = _start_order(fulfillment)

        resp = client.get("/api/processes/OrderFulfillment/instances")
        assert resp.status_code == 200
        data = resp.json()
        assert data["process"] == "OrderFulfillment"
        assert len(data["instances"]) == 1
        assert data["instances"][0]["instance_id"] == order_id
        assert data["total"] == 1

    def test_handles_instance_exception(self, fulfillment, test_domain, client):
        _start_order(fulfillment)

        with _fail_stream_identifiers(test_domain):
            resp = client.get("/api/processes/OrderFulfillment/instances")
        assert resp.status_code == 200
        data = resp.json()
        assert data["instances"] == []
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# Template: processes.html
# ---------------------------------------------------------------------------


class TestProcessesTemplate:
    @pytest.mark.parametrize(
        "markers",
        [
            [
                'id="summary-total"',
                'id="summary-instances"',
                'id="summary-healthy"',
                'id="summary-lagging"',
            ],
            ['id="processes-tbody"'],
            ['id="process-search"', 'id="process-status-filter"'],
            ['id="instance-explorer"', 'id="instances-tbody"'],
            ["/static/js/processes.js"],
            ['data-sort="name"', 'data-sort="instances"', 'data-sort="processed"'],
        ],
        ids=[
            "summary-cards",
            "table",
            "search-and-filter",
            "instance-explorer",
            "processes-js",
            "sort-headers",
        ],
    )
    def test_includes(self, client, markers):
        html = client.get("/processes").text
        for marker in markers:
            assert marker in html


# ---------------------------------------------------------------------------
# Static: processes.js
# ---------------------------------------------------------------------------


class TestProcessesStaticFiles:
    def test_processes_js_exists(self, client):
        resp = client.get("/static/js/processes.js")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Route Wiring
# ---------------------------------------------------------------------------


class TestProcessesRouteWiring:
    def test_processes_routes_present(self, test_domain):
        router = create_processes_router([test_domain])
        paths = [r.path for r in router.routes]
        assert "/processes" in paths
        assert "/processes/{name}/instances" in paths


# ---------------------------------------------------------------------------
# _get_redis
# ---------------------------------------------------------------------------


def _broken_domain(name):
    """A domain whose context cannot be entered."""
    domain = Domain(name=name)
    patcher = patch.object(
        domain, "domain_context", side_effect=Exception("context error")
    )
    return domain, patcher


class TestGetRedis:
    def test_returns_none_when_broker_raises_exception(self, test_domain):
        """A broker lookup that raises makes _get_redis return None."""
        with patch.object(
            test_domain.brokers,
            "get",
            side_effect=Exception("Redis connection refused"),
        ):
            assert _get_redis([test_domain]) is None

    def test_returns_none_when_domain_context_raises(self):
        """A domain whose context cannot be entered yields no client."""
        domain, patcher = _broken_domain("Broken")
        with patcher:
            assert _get_redis([domain]) is None

    def test_skips_failing_domain_tries_next(self, test_domain):
        """First domain fails, second succeeds."""
        failing, patcher = _broken_domain("Failing")
        with patcher:
            result = _get_redis([failing, test_domain])
        assert result is test_domain.brokers.get("default").redis_instance

    def test_returns_none_without_a_redis_broker(self):
        """An inline broker has no Redis client to hand out."""
        domain = Domain(name="Inline")
        domain.config["brokers"] = {"default": {"provider": "inline"}}
        domain.init(traverse=False)
        assert _get_redis([domain]) is None

    def test_returns_none_for_empty_domains(self):
        result = _get_redis([])
        assert result is None


# ---------------------------------------------------------------------------
# _decode_stream_id
# ---------------------------------------------------------------------------


class TestDecodeStreamId:
    def test_bytes_input(self):
        """bytes stream ID is decoded to utf-8 string."""
        result = _decode_stream_id(b"1234567890-0")
        assert result == "1234567890-0"
        assert isinstance(result, str)

    def test_string_input(self):
        """string stream ID is passed through."""
        result = _decode_stream_id("1234567890-0")
        assert result == "1234567890-0"
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _extract_handled_messages: keys without a dotted type
# ---------------------------------------------------------------------------


class TestExtractHandledMessagesFallback:
    def test_mixed_dotted_and_undotted_keys(self):
        """Dotted keys give their short name, undotted keys are kept whole."""
        cls = _handler_class_with_keys("MyApp.OrderPlaced.v1", "BareEvent")
        result = _extract_handled_messages(cls)
        assert result == ["BareEvent", "OrderPlaced"]


# ---------------------------------------------------------------------------
# _extract_time (from processes.py): timestamp from metadata
# ---------------------------------------------------------------------------


class TestExtractTimeProcesses:
    """A stored ``Message`` carries neither ``time`` nor ``metadata.timestamp``,
    so the tests that need those attributes pass a plain object that has them."""

    def test_extracts_time_attribute(self):
        msg = SimpleNamespace(time="2024-01-01T00:00:00Z")
        assert _extract_time(msg) == "2024-01-01T00:00:00Z"

    def test_falls_back_to_metadata_timestamp(self):
        """A message with no time falls back to metadata.timestamp."""
        msg = SimpleNamespace(
            time=None, metadata=SimpleNamespace(timestamp="2024-06-15T12:00:00Z")
        )
        assert _extract_time(msg) == "2024-06-15T12:00:00Z"

    def test_returns_none_when_no_time_or_metadata(self):
        assert _extract_time(Message(data={})) is None

    def test_returns_none_when_metadata_has_no_timestamp(
        self, fulfillment, test_domain
    ):
        order_id = _start_order(fulfillment)
        stream = f"{fulfillment.pm.meta_.stream_category}-{order_id}"
        stored = test_domain.event_store.store.read(stream)[-1]

        assert stored.metadata is not None
        assert _extract_time(stored) is None

    def test_datetime_object_uses_isoformat(self):
        """datetime objects should be serialized via .isoformat(), not str()."""
        msg = SimpleNamespace(time=datetime(2025, 6, 15, 12, 30, 45))
        result = _extract_time(msg)
        assert result == "2025-06-15T12:30:45"
        assert "T" in result  # isoformat uses 'T' separator

    def test_metadata_timestamp_datetime_uses_isoformat(self):
        """Metadata timestamp as datetime should use .isoformat()."""
        msg = SimpleNamespace(
            time=None, metadata=SimpleNamespace(timestamp=datetime(2025, 1, 1))
        )
        result = _extract_time(msg)
        assert result == "2025-01-01T00:00:00"
        assert "T" in result


# ---------------------------------------------------------------------------
# _build_summary: unknown subscription status
# ---------------------------------------------------------------------------


class TestBuildSummaryUnknownStatus:
    def test_unknown_subscription_status(self):
        """subscription status that is neither 'ok' nor 'lagging'
        is counted as unknown."""
        pms = [
            {
                "subscription": {"status": "error"},
                "instance_count": 5,
                "metrics": None,
            },
        ]
        summary = _build_summary(pms)
        assert summary["unknown"] == 1
        assert summary["healthy"] == 0
        assert summary["lagging"] == 0


# ---------------------------------------------------------------------------
# Endpoint: /api/processes/{name}/instances, get_pm_instances fails
# ---------------------------------------------------------------------------


class TestProcessesInstancesGetPMInstancesFails:
    def test_pm_instances_endpoint_when_get_pm_instances_raises(
        self, fulfillment, client
    ):
        """get_pm_instances raises inside the endpoint handler,
        endpoint catches and returns empty list."""
        _start_order(fulfillment)

        with patch(
            "protean.server.observatory.routes.processes.get_pm_instances",
            side_effect=Exception("unexpected error"),
        ):
            resp = client.get("/api/processes/OrderFulfillment/instances")
            assert resp.status_code == 200
            data = resp.json()
            assert data["instances"] == []
            assert data["total"] == 1


# ---------------------------------------------------------------------------
# get_pm_instances: one stream read fails
# ---------------------------------------------------------------------------


class TestGetPMInstancesStreamReadFails:
    def test_stream_read_exception_skips_instance(self, fulfillment, test_domain):
        """individual stream read fails, that instance is skipped."""
        first, second = sorted([_start_order(fulfillment), _start_order(fulfillment)])
        store = test_domain.event_store.store
        category = fulfillment.pm.meta_.stream_category
        real_read = store.read

        def read_failing_first(stream_name, *args, **kwargs):
            if stream_name == f"{category}-{first}":
                raise Exception("stream corrupted")
            return real_read(stream_name, *args, **kwargs)

        with patch.object(store, "read", side_effect=read_failing_first):
            result = get_pm_instances(test_domain, fulfillment.pm)

        assert len(result) == 1
        assert result[0]["instance_id"] == second


# ---------------------------------------------------------------------------
# Endpoint: /api/processes, a collaborator raises
# ---------------------------------------------------------------------------


class TestProcessesEndpointSubscriptionStatusException:
    def test_processes_endpoint_when_merge_subscription_status_raises(
        self, fulfillment, client
    ):
        """merge_pm_subscription_status raises at the endpoint level."""
        with patch(
            "protean.server.observatory.routes.processes.merge_pm_subscription_status",
            side_effect=Exception("subscription merge error"),
        ):
            resp = client.get("/api/processes")
            assert resp.status_code == 200
            data = resp.json()
            # Should still return processes even when merge fails
            assert len(data["processes"]) == 1
            assert data["processes"][0]["name"] == "OrderFulfillment"


class TestProcessesEndpointTraceMetricsException:
    def test_processes_endpoint_when_trace_metrics_raises(self, fulfillment, client):
        """collect_pm_trace_metrics raises inside the endpoint. The test
        domain's Redis broker hands out a client, so the endpoint calls it."""
        with patch(
            "protean.server.observatory.routes.processes.collect_pm_trace_metrics",
            side_effect=Exception("trace stream error"),
        ) as collect:
            resp = client.get("/api/processes")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["processes"]) == 1
            assert data["processes"][0]["metrics"] is None
        assert collect.called

    def test_processes_endpoint_when_instance_count_raises(self, fulfillment, client):
        """get_pm_instance_count raises for a PM."""
        _start_order(fulfillment)

        with patch(
            "protean.server.observatory.routes.processes.get_pm_instance_count",
            side_effect=Exception("count error"),
        ):
            resp = client.get("/api/processes")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["processes"]) == 1
            assert data["processes"][0]["instance_count"] is None


# ---------------------------------------------------------------------------
# get_pm_instance_count / get_pm_instances: event store not yet initialized
# (store is None)
# ---------------------------------------------------------------------------


class TestPMInstancesStoreUnavailable:
    """When ``domain.event_store.store`` is ``None`` (the domain has not
    initialized its event store yet), the instance helpers must degrade
    gracefully rather than raise."""

    def test_get_pm_instance_count_returns_none_when_store_is_none(self, fulfillment):
        """An uninitialized domain has no store, so the count is ``None``."""
        domain = Domain(name="NotInitialized")
        assert get_pm_instance_count(domain, fulfillment.pm) is None

    def test_get_pm_instances_returns_empty_when_store_is_none(self, fulfillment):
        """An uninitialized domain has no store, so no instances are listed."""
        domain = Domain(name="NotInitialized")
        assert get_pm_instances(domain, fulfillment.pm) == []
