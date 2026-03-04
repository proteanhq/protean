"""Tests for Observatory Processes API endpoints and supporting functions.

Covers:
- routes/processes.py: collect_pm_metadata, merge_pm_subscription_status,
  collect_pm_trace_metrics, get_pm_instance_count, get_pm_instances,
  _build_summary, create_processes_router
- templates/processes.html: structure and JS inclusion
- static/js/processes.js: file presence
"""

import json
import time
from collections import defaultdict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def observatory(test_domain):
    return Observatory(domains=[test_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


def _make_mock_pm_cls(
    *,
    name="TestPM",
    handlers=None,
    stream_category=None,
    stream_categories=None,
):
    """Create a mock PM class with the given metadata."""
    cls = MagicMock()
    cls.__name__ = name

    if handlers is not None:
        cls._handlers = handlers
    else:
        cls._handlers = defaultdict(set)

    meta = MagicMock()
    meta.stream_category = stream_category
    meta.stream_categories = stream_categories or []

    if stream_category is None:
        del meta.stream_category
    if stream_categories is None:
        meta.stream_categories = []

    cls.meta_ = meta
    return cls


def _make_mock_domain_record(name, qualname, cls):
    """Create a mock DomainRecord."""
    record = MagicMock()
    record.name = name
    record.qualname = qualname
    record.cls = cls
    return record


def _make_mock_domain(*, name="TestDomain", process_managers=None):
    """Create a mock domain with the given PM registry."""
    domain = MagicMock()
    domain.name = name

    registry = MagicMock()
    registry.process_managers = process_managers or {}

    domain.registry = registry
    return domain


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


# ---------------------------------------------------------------------------
# _extract_handled_messages
# ---------------------------------------------------------------------------


class TestExtractHandledMessages:
    def test_empty_handlers(self):
        cls = _make_mock_pm_cls(handlers=defaultdict(set))
        assert _extract_handled_messages(cls) == []

    def test_no_handlers_attr(self):
        cls = MagicMock(spec=[])
        assert _extract_handled_messages(cls) == []

    def test_extracts_short_names(self):
        handlers = defaultdict(set)
        handlers["MyApp.OrderPlaced.v1"] = {MagicMock()}
        handlers["MyApp.ShipmentCreated.v1"] = {MagicMock()}
        cls = _make_mock_pm_cls(handlers=handlers)
        result = _extract_handled_messages(cls)
        assert "OrderPlaced" in result
        assert "ShipmentCreated" in result

    def test_skips_dollar_any(self):
        handlers = defaultdict(set)
        handlers["$any"] = {MagicMock()}
        handlers["MyApp.OrderPlaced.v1"] = {MagicMock()}
        cls = _make_mock_pm_cls(handlers=handlers)
        result = _extract_handled_messages(cls)
        assert len(result) == 1
        assert "OrderPlaced" in result


# ---------------------------------------------------------------------------
# collect_pm_metadata
# ---------------------------------------------------------------------------


class TestCollectPMMetadata:
    def test_empty_domain(self):
        domain = _make_mock_domain()
        assert collect_pm_metadata([domain]) == []

    def test_single_pm(self):
        pm_cls = _make_mock_pm_cls(
            name="ShippingProcess",
            stream_category="test::shipping_process",
            stream_categories=["test::order", "test::shipment"],
        )
        record = _make_mock_domain_record(
            "ShippingProcess", "myapp.ShippingProcess", pm_cls
        )
        domain = _make_mock_domain(process_managers={"ShippingProcess": record})

        result = collect_pm_metadata([domain])
        assert len(result) == 1
        pm = result[0]
        assert pm["name"] == "ShippingProcess"
        assert pm["qualname"] == "myapp.ShippingProcess"
        assert pm["type"] == "process_manager"
        assert pm["domain"] == "TestDomain"
        assert pm["stream_category"] == "test::shipping_process"
        assert pm["stream_categories"] == ["test::order", "test::shipment"]
        assert pm["subscription"] is None
        assert pm["metrics"] is None
        assert pm["_cls"] is pm_cls
        assert pm["_domain"] is domain

    def test_multiple_pms_across_domains(self):
        pm1 = _make_mock_pm_cls(name="PM1")
        pm2 = _make_mock_pm_cls(name="PM2")
        d1 = _make_mock_domain(
            name="D1",
            process_managers={"PM1": _make_mock_domain_record("PM1", "a.PM1", pm1)},
        )
        d2 = _make_mock_domain(
            name="D2",
            process_managers={"PM2": _make_mock_domain_record("PM2", "b.PM2", pm2)},
        )

        result = collect_pm_metadata([d1, d2])
        assert len(result) == 2
        names = {p["name"] for p in result}
        assert names == {"PM1", "PM2"}


# ---------------------------------------------------------------------------
# merge_pm_subscription_status
# ---------------------------------------------------------------------------


class TestMergePMSubscriptionStatus:
    def test_no_statuses(self):
        pms = [{"name": "PM1", "type": "process_manager", "subscription": None}]
        domain = _make_mock_domain()

        with patch(
            "protean.server.observatory.routes.processes.collect_subscription_statuses",
            return_value=[],
        ):
            merge_pm_subscription_status(pms, [domain])

        assert pms[0]["subscription"] is None

    def test_matches_by_handler_name(self):
        pms = [
            {"name": "ShippingProcess", "type": "process_manager", "subscription": None}
        ]
        domain = _make_mock_domain()

        status = MagicMock()
        status.name = "ShippingProcess"
        status.handler_name = "ShippingProcess"
        status.status = "ok"
        status.lag = 5
        status.pending = 2
        status.dlq_depth = 0
        status.consumer_count = 1
        status.subscription_type = "event_store"

        with patch(
            "protean.server.observatory.routes.processes.collect_subscription_statuses",
            return_value=[status],
        ):
            merge_pm_subscription_status(pms, [domain])

        sub = pms[0]["subscription"]
        assert sub is not None
        assert sub["status"] == "ok"
        assert sub["lag"] == 5
        assert sub["pending"] == 2

    def test_aggregates_multiple_subscriptions(self):
        pms = [
            {"name": "ShippingProcess", "type": "process_manager", "subscription": None}
        ]
        domain = _make_mock_domain()

        s1 = MagicMock()
        s1.name = "ShippingProcess:order"
        s1.handler_name = "ShippingProcess"
        s1.status = "ok"
        s1.lag = 3
        s1.pending = 1
        s1.dlq_depth = 0
        s1.consumer_count = 1
        s1.subscription_type = "event_store"

        s2 = MagicMock()
        s2.name = "ShippingProcess:shipment"
        s2.handler_name = "ShippingProcess"
        s2.status = "lagging"
        s2.lag = 10
        s2.pending = 5
        s2.dlq_depth = 2
        s2.consumer_count = 1
        s2.subscription_type = "event_store"

        with patch(
            "protean.server.observatory.routes.processes.collect_subscription_statuses",
            return_value=[s1, s2],
        ):
            merge_pm_subscription_status(pms, [domain])

        sub = pms[0]["subscription"]
        assert sub["lag"] == 13
        assert sub["pending"] == 6
        assert sub["dlq_depth"] == 2
        assert sub["status"] == "lagging"

    def test_worst_status_unknown(self):
        pms = [{"name": "PM1", "type": "process_manager", "subscription": None}]
        domain = _make_mock_domain()

        s1 = MagicMock()
        s1.handler_name = "PM1"
        s1.status = "lagging"
        s1.lag = 5
        s1.pending = 0
        s1.dlq_depth = 0
        s1.consumer_count = 1
        s1.subscription_type = "event_store"

        s2 = MagicMock()
        s2.handler_name = "PM1"
        s2.status = "unknown"
        s2.lag = None
        s2.pending = 0
        s2.dlq_depth = 0
        s2.consumer_count = 0
        s2.subscription_type = "event_store"

        with patch(
            "protean.server.observatory.routes.processes.collect_subscription_statuses",
            return_value=[s1, s2],
        ):
            merge_pm_subscription_status(pms, [domain])

        assert pms[0]["subscription"]["status"] == "unknown"

    def test_handles_collection_exception(self):
        pms = [{"name": "PM1", "type": "process_manager", "subscription": None}]
        domain = _make_mock_domain()

        with patch(
            "protean.server.observatory.routes.processes.collect_subscription_statuses",
            side_effect=Exception("fail"),
        ):
            # Should not raise
            merge_pm_subscription_status(pms, [domain])

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

    def test_handles_malformed_data(self):
        now_ms = int(time.time() * 1000)
        redis = MagicMock()
        redis.xrange.return_value = [
            (f"{now_ms - 5000}-0".encode(), {b"data": b"not-json"}),
            (
                f"{now_ms - 4000}-0".encode(),
                {b"data": _make_trace_entry(handler="PM1")},
            ),
        ]

        result = collect_pm_trace_metrics(redis, {"PM1"}, 300000)
        assert result["PM1"]["processed"] == 1

    def test_skips_missing_data_field(self):
        now_ms = int(time.time() * 1000)
        redis = MagicMock()
        redis.xrange.return_value = [
            (f"{now_ms - 5000}-0".encode(), {b"other": b"value"}),
        ]

        result = collect_pm_trace_metrics(redis, {"PM1"}, 300000)
        assert result == {}


# ---------------------------------------------------------------------------
# get_pm_instance_count
# ---------------------------------------------------------------------------


class TestGetPMInstanceCount:
    def test_no_meta(self):
        cls = MagicMock(spec=[])
        domain = MagicMock()
        assert get_pm_instance_count(domain, cls) is None

    def test_no_stream_category(self):
        cls = MagicMock()
        cls.meta_ = MagicMock()
        cls.meta_.stream_category = None
        domain = MagicMock()
        assert get_pm_instance_count(domain, cls) is None

    def test_returns_count(self):
        cls = MagicMock()
        cls.meta_ = MagicMock()
        cls.meta_.stream_category = "test::pm"

        domain = MagicMock()
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.event_store.store._stream_identifiers.return_value = [
            "id1",
            "id2",
            "id3",
        ]

        assert get_pm_instance_count(domain, cls) == 3

    def test_handles_exception(self):
        cls = MagicMock()
        cls.__name__ = "TestPM"
        cls.meta_ = MagicMock()
        cls.meta_.stream_category = "test::pm"

        domain = MagicMock()
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.event_store.store._stream_identifiers.side_effect = Exception("fail")

        assert get_pm_instance_count(domain, cls) is None


# ---------------------------------------------------------------------------
# get_pm_instances
# ---------------------------------------------------------------------------


class TestGetPMInstances:
    def test_no_meta(self):
        cls = MagicMock(spec=[])
        domain = MagicMock()
        assert get_pm_instances(domain, cls) == []

    def test_no_stream_category(self):
        cls = MagicMock()
        cls.meta_ = MagicMock()
        cls.meta_.stream_category = None
        domain = MagicMock()
        assert get_pm_instances(domain, cls) == []

    def test_returns_instances(self):
        cls = MagicMock()
        cls.__name__ = "TestPM"
        cls.meta_ = MagicMock()
        cls.meta_.stream_category = "test::pm"

        msg1 = MagicMock()
        msg1.data = {"state": {"status": "started"}, "is_complete": False}
        msg1.time = "2024-01-01T00:00:00Z"

        msg2 = MagicMock()
        msg2.data = {"state": {"status": "completed"}, "is_complete": True}
        msg2.time = "2024-01-01T01:00:00Z"

        domain = MagicMock()
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.event_store.store._stream_identifiers.return_value = ["id1"]
        domain.event_store.store.read.return_value = [msg1, msg2]

        result = get_pm_instances(domain, cls)
        assert len(result) == 1
        inst = result[0]
        assert inst["instance_id"] == "id1"
        assert inst["version"] == 2
        assert inst["is_complete"] is True
        assert inst["state"] == {"status": "completed"}
        assert inst["event_count"] == 2

    def test_empty_stream(self):
        cls = MagicMock()
        cls.__name__ = "TestPM"
        cls.meta_ = MagicMock()
        cls.meta_.stream_category = "test::pm"

        domain = MagicMock()
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.event_store.store._stream_identifiers.return_value = ["id1"]
        domain.event_store.store.read.return_value = []

        result = get_pm_instances(domain, cls)
        assert result == []

    def test_respects_limit(self):
        cls = MagicMock()
        cls.__name__ = "TestPM"
        cls.meta_ = MagicMock()
        cls.meta_.stream_category = "test::pm"

        msg = MagicMock()
        msg.data = {"state": {}, "is_complete": False}
        msg.time = "2024-01-01T00:00:00Z"

        domain = MagicMock()
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.event_store.store._stream_identifiers.return_value = [
            f"id{i}" for i in range(10)
        ]
        domain.event_store.store.read.return_value = [msg]

        result = get_pm_instances(domain, cls, limit=3)
        assert len(result) == 3

    def test_handles_stream_identifiers_exception(self):
        cls = MagicMock()
        cls.__name__ = "TestPM"
        cls.meta_ = MagicMock()
        cls.meta_.stream_category = "test::pm"

        domain = MagicMock()
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.event_store.store._stream_identifiers.side_effect = Exception("fail")

        assert get_pm_instances(domain, cls) == []


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
    def test_strips_internal_keys(self):
        pm = {
            "name": "TestPM",
            "type": "process_manager",
            "_cls": MagicMock(),
            "_domain": MagicMock(),
        }
        result = _serialize_pm(pm)
        assert "name" in result
        assert "_cls" not in result
        assert "_domain" not in result

    def test_preserves_public_keys(self):
        pm = {
            "name": "TestPM",
            "type": "process_manager",
            "metrics": {"processed": 5},
            "_cls": MagicMock(),
        }
        result = _serialize_pm(pm)
        assert result["name"] == "TestPM"
        assert result["metrics"] == {"processed": 5}


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

    def test_with_mock_pms(self):
        pm_cls = _make_mock_pm_cls(
            name="TestPM",
            stream_category="test::pm",
            stream_categories=["test::order"],
        )
        record = _make_mock_domain_record("TestPM", "a.TestPM", pm_cls)
        domain = _make_mock_domain(process_managers={"TestPM": record})

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)
        resp = c.get("/api/processes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["processes"]) == 1
        assert data["processes"][0]["name"] == "TestPM"
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

    def test_returns_instances(self):
        pm_cls = MagicMock()
        pm_cls.__name__ = "TestPM"
        pm_cls.meta_ = MagicMock()
        pm_cls.meta_.stream_category = "test::pm"
        pm_cls.meta_.stream_categories = []
        pm_cls._handlers = defaultdict(set)

        record = _make_mock_domain_record("TestPM", "a.TestPM", pm_cls)
        domain = _make_mock_domain(process_managers={"TestPM": record})

        # Mock event store
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.event_store.store._stream_identifiers.return_value = ["inst-1"]

        msg = MagicMock()
        msg.data = {"state": {"status": "active"}, "is_complete": False}
        msg.time = "2024-01-01T00:00:00Z"
        domain.event_store.store.read.return_value = [msg]

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)
        resp = c.get("/api/processes/TestPM/instances")
        assert resp.status_code == 200
        data = resp.json()
        assert data["process"] == "TestPM"
        assert len(data["instances"]) == 1
        assert data["instances"][0]["instance_id"] == "inst-1"

    def test_handles_instance_exception(self):
        pm_cls = MagicMock()
        pm_cls.__name__ = "TestPM"
        pm_cls.meta_ = MagicMock()
        pm_cls.meta_.stream_category = "test::pm"
        pm_cls.meta_.stream_categories = []
        pm_cls._handlers = defaultdict(set)

        record = _make_mock_domain_record("TestPM", "a.TestPM", pm_cls)
        domain = _make_mock_domain(process_managers={"TestPM": record})

        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.event_store.store._stream_identifiers.side_effect = Exception("fail")

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)
        resp = c.get("/api/processes/TestPM/instances")
        assert resp.status_code == 200
        data = resp.json()
        assert data["instances"] == []


# ---------------------------------------------------------------------------
# Template: processes.html
# ---------------------------------------------------------------------------


class TestProcessesTemplate:
    def test_renders_page(self, client):
        resp = client.get("/processes")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_includes_summary_cards(self, client):
        html = client.get("/processes").text
        assert 'id="summary-total"' in html
        assert 'id="summary-instances"' in html
        assert 'id="summary-healthy"' in html
        assert 'id="summary-lagging"' in html

    def test_includes_table(self, client):
        html = client.get("/processes").text
        assert 'id="processes-tbody"' in html

    def test_includes_search_and_filter(self, client):
        html = client.get("/processes").text
        assert 'id="process-search"' in html
        assert 'id="process-status-filter"' in html

    def test_includes_instance_explorer(self, client):
        html = client.get("/processes").text
        assert 'id="instance-explorer"' in html
        assert 'id="instances-tbody"' in html

    def test_includes_processes_js(self, client):
        html = client.get("/processes").text
        assert "/static/js/processes.js" in html

    def test_sort_headers(self, client):
        html = client.get("/processes").text
        assert 'data-sort="name"' in html
        assert 'data-sort="instances"' in html
        assert 'data-sort="processed"' in html


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
    def test_create_processes_router_returns_router(self):
        router = create_processes_router([])
        assert hasattr(router, "routes")

    def test_processes_routes_present(self):
        domain = MagicMock()
        domain.name = "test"
        router = create_processes_router([domain])
        paths = [r.path for r in router.routes]
        assert "/processes" in paths
        assert "/processes/{name}/instances" in paths

    def test_api_router_includes_processes_routes(self, client):
        """Verify processes routes are wired into the Observatory app."""
        resp = client.get("/api/processes")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# _get_redis
# ---------------------------------------------------------------------------


class TestGetRedis:
    def test_returns_none_when_broker_raises_exception(self):
        """Lines 63-67: broker raises exception, _get_redis returns None."""
        domain = MagicMock()
        domain.name = "TestDomain"
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.brokers.get.side_effect = Exception("Redis connection refused")

        result = _get_redis([domain])
        assert result is None

    def test_returns_none_when_domain_context_raises(self):
        """Lines 65-66: domain_context itself raises, _get_redis continues."""
        domain = MagicMock()
        domain.name = "TestDomain"
        domain.domain_context.side_effect = Exception("context error")

        result = _get_redis([domain])
        assert result is None

    def test_returns_redis_instance(self):
        """Happy path: broker has redis_instance attribute."""
        domain = MagicMock()
        domain.name = "TestDomain"
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        redis_mock = MagicMock()
        broker = MagicMock()
        broker.redis_instance = redis_mock
        domain.brokers.get.return_value = broker

        result = _get_redis([domain])
        assert result is redis_mock

    def test_skips_failing_domain_tries_next(self):
        """First domain fails, second succeeds."""
        d1 = MagicMock()
        d1.name = "Failing"
        d1.domain_context.side_effect = Exception("fail")

        d2 = MagicMock()
        d2.name = "Working"
        d2.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        d2.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        redis_mock = MagicMock()
        broker = MagicMock()
        broker.redis_instance = redis_mock
        d2.brokers.get.return_value = broker

        result = _get_redis([d1, d2])
        assert result is redis_mock

    def test_returns_none_for_empty_domains(self):
        result = _get_redis([])
        assert result is None


# ---------------------------------------------------------------------------
# _decode_stream_id
# ---------------------------------------------------------------------------


class TestDecodeStreamId:
    def test_bytes_input(self):
        """Lines 72-73: bytes stream ID is decoded to utf-8 string."""
        result = _decode_stream_id(b"1234567890-0")
        assert result == "1234567890-0"
        assert isinstance(result, str)

    def test_string_input(self):
        """Line 74: string stream ID is passed through."""
        result = _decode_stream_id("1234567890-0")
        assert result == "1234567890-0"
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _extract_handled_messages — fallback type key (line 94)
# ---------------------------------------------------------------------------


class TestExtractHandledMessagesFallback:
    def test_type_key_without_dots(self):
        """Line 94: type key with no dots falls through to append(type_key)."""
        handlers = defaultdict(set)
        handlers["SimpleEvent"] = {MagicMock()}
        cls = _make_mock_pm_cls(handlers=handlers)
        result = _extract_handled_messages(cls)
        assert result == ["SimpleEvent"]

    def test_mixed_dotted_and_undotted_keys(self):
        """Mix of dotted keys (normal) and undotted keys (fallback)."""
        handlers = defaultdict(set)
        handlers["MyApp.OrderPlaced.v1"] = {MagicMock()}
        handlers["BareEvent"] = {MagicMock()}
        cls = _make_mock_pm_cls(handlers=handlers)
        result = _extract_handled_messages(cls)
        assert "BareEvent" in result
        assert "OrderPlaced" in result


# ---------------------------------------------------------------------------
# _extract_time (from processes.py) — timestamp from metadata
# ---------------------------------------------------------------------------


class TestExtractTimeProcesses:
    def test_extracts_time_attribute(self):
        msg = MagicMock()
        msg.time = "2024-01-01T00:00:00Z"
        assert _extract_time(msg) == "2024-01-01T00:00:00Z"

    def test_falls_back_to_metadata_timestamp(self):
        """Lines 378-381: message has no time, falls back to metadata.timestamp."""
        msg = MagicMock()
        msg.time = None
        msg.metadata = MagicMock()
        msg.metadata.timestamp = "2024-06-15T12:00:00Z"
        assert _extract_time(msg) == "2024-06-15T12:00:00Z"

    def test_returns_none_when_no_time_or_metadata(self):
        msg = MagicMock()
        msg.time = None
        msg.metadata = None
        assert _extract_time(msg) is None

    def test_returns_none_when_metadata_has_no_timestamp(self):
        msg = MagicMock(spec=["time", "metadata"])
        msg.time = None
        msg.metadata = MagicMock(spec=[])  # no timestamp attribute
        assert _extract_time(msg) is None


# ---------------------------------------------------------------------------
# _build_summary — unknown subscription status (line 402)
# ---------------------------------------------------------------------------


class TestBuildSummaryUnknownStatus:
    def test_unknown_subscription_status(self):
        """Line 402: subscription status that is neither 'ok' nor 'lagging'
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
# Endpoint: /api/processes/{name}/instances — get_pm_instances fails (line 517-520)
# ---------------------------------------------------------------------------


class TestProcessesInstancesGetPMInstancesFails:
    def test_pm_instances_endpoint_when_get_pm_instances_raises(self):
        """Lines 517-520: get_pm_instances raises inside the endpoint handler,
        endpoint catches and returns empty list."""
        pm_cls = MagicMock()
        pm_cls.__name__ = "TestPM"
        pm_cls.meta_ = MagicMock()
        pm_cls.meta_.stream_category = "test::pm"
        pm_cls.meta_.stream_categories = []
        pm_cls._handlers = defaultdict(set)

        record = _make_mock_domain_record("TestPM", "a.TestPM", pm_cls)
        domain = _make_mock_domain(process_managers={"TestPM": record})

        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)

        # Make _stream_identifiers work for collect but get_pm_instances fail
        call_count = 0
        original_identifiers = ["inst-1"]

        def side_effect_identifiers(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # First calls for collect_pm_metadata (instance count check)
                return original_identifiers
            raise Exception("Store connection lost")

        domain.event_store.store._stream_identifiers.side_effect = (
            side_effect_identifiers
        )

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)

        with patch(
            "protean.server.observatory.routes.processes.get_pm_instances",
            side_effect=Exception("unexpected error"),
        ):
            resp = c.get("/api/processes/TestPM/instances")
            assert resp.status_code == 200
            data = resp.json()
            assert data["instances"] == []


# ---------------------------------------------------------------------------
# Endpoint: /api/processes/{name}/instances — stream read fails (line 336-338)
# ---------------------------------------------------------------------------


class TestGetPMInstancesStreamReadFails:
    def test_stream_read_exception_skips_instance(self):
        """Lines 336-338: individual stream read fails, that instance is skipped."""
        cls = MagicMock()
        cls.__name__ = "TestPM"
        cls.meta_ = MagicMock()
        cls.meta_.stream_category = "test::pm"

        msg = MagicMock()
        msg.data = {"state": {"status": "active"}, "is_complete": False}
        msg.time = "2024-01-01T00:00:00Z"

        domain = MagicMock()
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.event_store.store._stream_identifiers.return_value = ["id1", "id2"]

        # First read fails, second succeeds
        domain.event_store.store.read.side_effect = [
            Exception("stream corrupted"),
            [msg],
        ]

        result = get_pm_instances(domain, cls)
        assert len(result) == 1
        assert result[0]["instance_id"] == "id2"


# ---------------------------------------------------------------------------
# Endpoint: /api/processes — collect_subscription_statuses raises (line 459-460)
# ---------------------------------------------------------------------------


class TestProcessesEndpointSubscriptionStatusException:
    def test_processes_endpoint_when_merge_subscription_status_raises(self):
        """Lines 459-460: merge_pm_subscription_status raises at the endpoint level."""
        pm_cls = _make_mock_pm_cls(
            name="TestPM",
            stream_category="test::pm",
            stream_categories=[],
        )
        record = _make_mock_domain_record("TestPM", "a.TestPM", pm_cls)
        domain = _make_mock_domain(process_managers={"TestPM": record})

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)

        with patch(
            "protean.server.observatory.routes.processes.merge_pm_subscription_status",
            side_effect=Exception("subscription merge error"),
        ):
            resp = c.get("/api/processes")
            assert resp.status_code == 200
            data = resp.json()
            # Should still return processes even when merge fails
            assert len(data["processes"]) == 1
            assert data["processes"][0]["name"] == "TestPM"


# ---------------------------------------------------------------------------
# Endpoint: /api/processes — collect_pm_trace_metrics raises (line 464-480)
# ---------------------------------------------------------------------------


class TestProcessesEndpointTraceMetricsException:
    def test_processes_endpoint_when_trace_metrics_raises(self):
        """Lines 472-473: collect_pm_trace_metrics raises inside the endpoint."""
        pm_cls = _make_mock_pm_cls(
            name="TestPM",
            stream_category="test::pm",
            stream_categories=[],
        )
        record = _make_mock_domain_record("TestPM", "a.TestPM", pm_cls)
        domain = _make_mock_domain(process_managers={"TestPM": record})

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)

        with (
            patch(
                "protean.server.observatory.routes.processes._get_redis",
                return_value=MagicMock(),  # Return a non-None redis
            ),
            patch(
                "protean.server.observatory.routes.processes.collect_pm_trace_metrics",
                side_effect=Exception("trace stream error"),
            ),
        ):
            resp = c.get("/api/processes")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["processes"]) == 1

    def test_processes_endpoint_when_instance_count_raises(self):
        """Lines 477-482: get_pm_instance_count raises for a PM."""
        pm_cls = _make_mock_pm_cls(
            name="TestPM",
            stream_category="test::pm",
            stream_categories=[],
        )
        record = _make_mock_domain_record("TestPM", "a.TestPM", pm_cls)
        domain = _make_mock_domain(process_managers={"TestPM": record})

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)

        with patch(
            "protean.server.observatory.routes.processes.get_pm_instance_count",
            side_effect=Exception("count error"),
        ):
            resp = c.get("/api/processes")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["processes"]) == 1
