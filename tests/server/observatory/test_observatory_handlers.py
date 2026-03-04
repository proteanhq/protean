"""Tests for Observatory Handlers API endpoints and supporting functions.

Covers:
- routes/handlers.py: _extract_handled_messages, _handler_type_label,
  _infer_aggregate, _infer_stream_categories, collect_handler_metadata,
  merge_subscription_status, collect_per_handler_trace_metrics,
  collect_recent_messages, _build_summary, create_handlers_router
- routes/__init__.py: updated create_all_routes wiring
"""

import json
import time
from collections import defaultdict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory
from protean.server.observatory.routes.handlers import (
    _build_summary,
    _extract_handled_messages,
    _handler_type_label,
    _infer_aggregate,
    _infer_stream_categories,
    collect_handler_metadata,
    collect_per_handler_trace_metrics,
    collect_recent_messages,
    create_handlers_router,
    merge_subscription_status,
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


def _make_mock_handler_cls(
    *,
    name="TestHandler",
    handlers=None,
    part_of=None,
    projector_for=None,
    stream_category=None,
    stream_categories=None,
    stream=None,
    broker=None,
):
    """Create a mock handler class with the given metadata."""
    cls = MagicMock()
    cls.__name__ = name

    if handlers is not None:
        cls._handlers = handlers
    else:
        cls._handlers = defaultdict(set)

    meta = MagicMock()
    meta.part_of = part_of
    meta.projector_for = projector_for
    meta.stream_category = stream_category
    meta.stream_categories = stream_categories
    meta.stream = stream
    meta.broker = broker

    # Control hasattr behavior
    if stream_categories is None:
        del meta.stream_categories
    if projector_for is None:
        del meta.projector_for
    if part_of is None:
        del meta.part_of
    if stream_category is None:
        del meta.stream_category
    if stream is None:
        del meta.stream
    if broker is None:
        del meta.broker

    cls.meta_ = meta
    return cls


def _make_mock_domain_record(name, qualname, class_type, cls):
    """Create a mock DomainRecord."""
    record = MagicMock()
    record.name = name
    record.qualname = qualname
    record.class_type = class_type
    record.cls = cls
    return record


def _make_mock_domain(
    *,
    name="TestDomain",
    event_handlers=None,
    command_handlers=None,
    projectors=None,
    subscribers=None,
):
    """Create a mock domain with the given registry."""
    domain = MagicMock()
    domain.name = name

    registry = MagicMock()
    registry.event_handlers = event_handlers or {}
    registry.command_handlers = command_handlers or {}
    registry.projectors = projectors or {}
    registry.subscribers = subscribers or {}

    domain.registry = registry
    return domain


def _make_trace_entry(
    event="handler.completed",
    handler="TestHandler",
    duration_ms=25.0,
    message_type="TestEvent",
    stream="test-stream",
    timestamp=None,
):
    """Create a serialized trace entry as Redis would return."""
    trace = {
        "event": event,
        "handler": handler,
        "duration_ms": duration_ms,
        "message_type": message_type,
        "stream": stream,
        "timestamp": timestamp or time.time(),
    }
    return json.dumps(trace).encode("utf-8")


# ---------------------------------------------------------------------------
# _extract_handled_messages
# ---------------------------------------------------------------------------


class TestExtractHandledMessages:
    def test_empty_handlers(self):
        cls = _make_mock_handler_cls(handlers=defaultdict(set))
        assert _extract_handled_messages(cls) == []

    def test_no_handlers_attr(self):
        cls = MagicMock(spec=[])
        assert _extract_handled_messages(cls) == []

    def test_extracts_class_names_from_type_strings(self):
        handlers = defaultdict(set)
        handlers["App.OrderPlaced.v1"] = {MagicMock()}
        handlers["App.OrderShipped.v1"] = {MagicMock()}
        cls = _make_mock_handler_cls(handlers=handlers)

        result = _extract_handled_messages(cls)
        assert result == ["OrderPlaced", "OrderShipped"]

    def test_skips_any_key(self):
        handlers = defaultdict(set)
        handlers["$any"] = {MagicMock()}
        handlers["App.OrderPlaced.v1"] = {MagicMock()}
        cls = _make_mock_handler_cls(handlers=handlers)

        result = _extract_handled_messages(cls)
        assert result == ["OrderPlaced"]
        assert "$any" not in result

    def test_single_part_type_string(self):
        """Type string without dots uses entire key."""
        handlers = defaultdict(set)
        handlers["SimpleType"] = {MagicMock()}
        cls = _make_mock_handler_cls(handlers=handlers)

        result = _extract_handled_messages(cls)
        assert result == ["SimpleType"]

    def test_sorted_output(self):
        handlers = defaultdict(set)
        handlers["App.Zebra.v1"] = {MagicMock()}
        handlers["App.Alpha.v1"] = {MagicMock()}
        cls = _make_mock_handler_cls(handlers=handlers)

        result = _extract_handled_messages(cls)
        assert result == ["Alpha", "Zebra"]


# ---------------------------------------------------------------------------
# _handler_type_label
# ---------------------------------------------------------------------------


class TestHandlerTypeLabel:
    def test_event_handler(self):
        assert _handler_type_label("EVENT_HANDLER") == "event_handler"

    def test_command_handler(self):
        assert _handler_type_label("COMMAND_HANDLER") == "command_handler"

    def test_projector(self):
        assert _handler_type_label("PROJECTOR") == "projector"

    def test_subscriber(self):
        assert _handler_type_label("SUBSCRIBER") == "subscriber"

    def test_process_manager(self):
        assert _handler_type_label("PROCESS_MANAGER") == "process_manager"

    def test_unknown_type(self):
        assert _handler_type_label("UNKNOWN") == "unknown"


# ---------------------------------------------------------------------------
# _infer_aggregate
# ---------------------------------------------------------------------------


class TestInferAggregate:
    def test_from_part_of(self):
        part_of = MagicMock()
        part_of.__name__ = "Order"
        cls = _make_mock_handler_cls(part_of=part_of)
        assert _infer_aggregate(cls) == "Order"

    def test_from_projector_for(self):
        proj_for = MagicMock()
        proj_for.__name__ = "OrderProjection"
        cls = _make_mock_handler_cls(projector_for=proj_for)
        assert _infer_aggregate(cls) == "OrderProjection"

    def test_projector_for_takes_priority(self):
        """projector_for is checked before part_of."""
        proj_for = MagicMock()
        proj_for.__name__ = "OrderProjection"
        part_of = MagicMock()
        part_of.__name__ = "Order"
        cls = _make_mock_handler_cls(projector_for=proj_for, part_of=part_of)
        assert _infer_aggregate(cls) == "OrderProjection"

    def test_no_aggregate(self):
        cls = _make_mock_handler_cls()
        assert _infer_aggregate(cls) is None

    def test_no_meta(self):
        cls = MagicMock(spec=[])
        assert _infer_aggregate(cls) is None


# ---------------------------------------------------------------------------
# _infer_stream_categories
# ---------------------------------------------------------------------------


class TestInferStreamCategories:
    def test_projector_with_stream_categories(self):
        cls = _make_mock_handler_cls(stream_categories=["order", "payment"])
        result = _infer_stream_categories(cls, "PROJECTOR")
        assert result == ["order", "payment"]

    def test_process_manager_with_stream_categories(self):
        cls = _make_mock_handler_cls(stream_categories=["order"])
        result = _infer_stream_categories(cls, "PROCESS_MANAGER")
        assert result == ["order"]

    def test_event_handler_with_stream_category(self):
        cls = _make_mock_handler_cls(stream_category="order")
        result = _infer_stream_categories(cls, "EVENT_HANDLER")
        assert result == ["order"]

    def test_command_handler_with_stream_category(self):
        cls = _make_mock_handler_cls(stream_category="order")
        result = _infer_stream_categories(cls, "COMMAND_HANDLER")
        assert result == ["order"]

    def test_no_stream_info(self):
        cls = _make_mock_handler_cls()
        result = _infer_stream_categories(cls, "EVENT_HANDLER")
        assert result == []

    def test_no_meta(self):
        cls = MagicMock(spec=[])
        result = _infer_stream_categories(cls, "EVENT_HANDLER")
        assert result == []


# ---------------------------------------------------------------------------
# collect_handler_metadata
# ---------------------------------------------------------------------------


class TestCollectHandlerMetadata:
    def test_empty_domain(self):
        domain = _make_mock_domain()
        result = collect_handler_metadata([domain])
        assert result == []

    def test_event_handler(self):
        part_of = MagicMock()
        part_of.__name__ = "Order"
        handlers = defaultdict(set)
        handlers["App.OrderPlaced.v1"] = {MagicMock()}

        cls = _make_mock_handler_cls(
            name="OrderEventHandler",
            handlers=handlers,
            part_of=part_of,
            stream_category="order",
        )
        record = _make_mock_domain_record(
            "OrderEventHandler",
            "myapp.handlers.OrderEventHandler",
            "EVENT_HANDLER",
            cls,
        )
        domain = _make_mock_domain(event_handlers={"OrderEventHandler": record})

        result = collect_handler_metadata([domain])
        assert len(result) == 1
        h = result[0]
        assert h["name"] == "OrderEventHandler"
        assert h["qualname"] == "myapp.handlers.OrderEventHandler"
        assert h["type"] == "event_handler"
        assert h["domain"] == "TestDomain"
        assert h["aggregate"] == "Order"
        assert h["stream_categories"] == ["order"]
        assert h["handled_messages"] == ["OrderPlaced"]
        assert h["subscription"] is None
        assert h["metrics"] is None

    def test_command_handler(self):
        part_of = MagicMock()
        part_of.__name__ = "Order"
        handlers = defaultdict(set)
        handlers["App.PlaceOrder.v1"] = {MagicMock()}

        cls = _make_mock_handler_cls(
            name="OrderCommandHandler",
            handlers=handlers,
            part_of=part_of,
            stream_category="order",
        )
        record = _make_mock_domain_record(
            "OrderCommandHandler",
            "myapp.handlers.OrderCommandHandler",
            "COMMAND_HANDLER",
            cls,
        )
        domain = _make_mock_domain(command_handlers={"OrderCommandHandler": record})

        result = collect_handler_metadata([domain])
        assert len(result) == 1
        assert result[0]["type"] == "command_handler"
        assert result[0]["handled_messages"] == ["PlaceOrder"]

    def test_projector(self):
        proj_for = MagicMock()
        proj_for.__name__ = "OrderProjection"
        handlers = defaultdict(set)
        handlers["App.OrderPlaced.v1"] = {MagicMock()}

        cls = _make_mock_handler_cls(
            name="OrderProjector",
            handlers=handlers,
            projector_for=proj_for,
            stream_categories=["order"],
        )
        record = _make_mock_domain_record(
            "OrderProjector",
            "myapp.projectors.OrderProjector",
            "PROJECTOR",
            cls,
        )
        domain = _make_mock_domain(projectors={"OrderProjector": record})

        result = collect_handler_metadata([domain])
        assert len(result) == 1
        assert result[0]["type"] == "projector"
        assert result[0]["aggregate"] == "OrderProjection"
        assert result[0]["stream_categories"] == ["order"]

    def test_subscriber(self):
        cls = _make_mock_handler_cls(
            name="PaymentSubscriber",
            stream="external:payments",
            broker="default",
        )
        # Subscribers have no _handlers dict
        cls._handlers = defaultdict(set)

        record = _make_mock_domain_record(
            "PaymentSubscriber",
            "myapp.subscribers.PaymentSubscriber",
            "SUBSCRIBER",
            cls,
        )
        domain = _make_mock_domain(subscribers={"PaymentSubscriber": record})

        result = collect_handler_metadata([domain])
        assert len(result) == 1
        h = result[0]
        assert h["type"] == "subscriber"
        assert h["handled_messages"] == ["external:payments"]
        assert h["stream_categories"] == ["external:payments"]

    def test_multiple_domains(self):
        part_of = MagicMock()
        part_of.__name__ = "User"
        cls = _make_mock_handler_cls(
            name="UserHandler",
            part_of=part_of,
            stream_category="user",
        )
        record = _make_mock_domain_record(
            "UserHandler", "app.UserHandler", "EVENT_HANDLER", cls
        )

        d1 = _make_mock_domain(name="Domain1", event_handlers={"UserHandler": record})
        d2 = _make_mock_domain(name="Domain2")

        result = collect_handler_metadata([d1, d2])
        assert len(result) == 1
        assert result[0]["domain"] == "Domain1"

    def test_multiple_handler_types_combined(self):
        part_of = MagicMock()
        part_of.__name__ = "Order"

        eh_cls = _make_mock_handler_cls(
            name="EH", part_of=part_of, stream_category="order"
        )
        eh_rec = _make_mock_domain_record("EH", "app.EH", "EVENT_HANDLER", eh_cls)

        ch_cls = _make_mock_handler_cls(
            name="CH", part_of=part_of, stream_category="order"
        )
        ch_rec = _make_mock_domain_record("CH", "app.CH", "COMMAND_HANDLER", ch_cls)

        domain = _make_mock_domain(
            event_handlers={"EH": eh_rec},
            command_handlers={"CH": ch_rec},
        )

        result = collect_handler_metadata([domain])
        assert len(result) == 2
        types = {h["type"] for h in result}
        assert types == {"event_handler", "command_handler"}


# ---------------------------------------------------------------------------
# merge_subscription_status
# ---------------------------------------------------------------------------


class TestMergeSubscriptionStatus:
    def test_no_statuses_leaves_subscription_none(self):
        handlers = [
            {"name": "TestHandler", "type": "event_handler", "stream_categories": []}
        ]
        domain = MagicMock()
        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            return_value=[],
        ):
            merge_subscription_status(handlers, [domain])
        assert handlers[0].get("subscription") is None

    def test_event_handler_direct_match(self):
        status = MagicMock()
        status.name = "OrderEventHandler"
        status.handler_name = "OrderEventHandler"
        status.status = "ok"
        status.lag = 0
        status.pending = 0
        status.dlq_depth = 0
        status.consumer_count = 1
        status.subscription_type = "stream"

        handlers = [
            {
                "name": "OrderEventHandler",
                "type": "event_handler",
                "stream_categories": ["order"],
            }
        ]
        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            return_value=[status],
        ):
            merge_subscription_status(handlers, [MagicMock()])

        sub = handlers[0]["subscription"]
        assert sub is not None
        assert sub["status"] == "ok"
        assert sub["lag"] == 0
        assert sub["consumer_count"] == 1

    def test_command_handler_matches_by_stream(self):
        status = MagicMock()
        status.name = "commands:order"
        status.handler_name = "OrderCommandHandler"
        status.status = "ok"
        status.lag = 0
        status.pending = 0
        status.dlq_depth = 0
        status.consumer_count = 1
        status.subscription_type = "stream"

        handlers = [
            {
                "name": "OrderCommandHandler",
                "type": "command_handler",
                "stream_categories": ["order"],
            }
        ]
        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            return_value=[status],
        ):
            merge_subscription_status(handlers, [MagicMock()])

        sub = handlers[0]["subscription"]
        assert sub is not None
        assert sub["subscription_type"] == "stream"

    def test_projector_aggregates_across_streams(self):
        s1 = MagicMock()
        s1.name = "MyProjector-order"
        s1.handler_name = "MyProjector"
        s1.status = "ok"
        s1.lag = 2
        s1.pending = 1
        s1.dlq_depth = 0
        s1.consumer_count = 1
        s1.subscription_type = "stream"

        s2 = MagicMock()
        s2.name = "MyProjector-payment"
        s2.handler_name = "MyProjector"
        s2.status = "lagging"
        s2.lag = 5
        s2.pending = 3
        s2.dlq_depth = 1
        s2.consumer_count = 2
        s2.subscription_type = "stream"

        handlers = [
            {
                "name": "MyProjector",
                "type": "projector",
                "stream_categories": ["order", "payment"],
            }
        ]
        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            return_value=[s1, s2],
        ):
            merge_subscription_status(handlers, [MagicMock()])

        sub = handlers[0]["subscription"]
        assert sub is not None
        assert sub["lag"] == 7  # 2 + 5
        assert sub["pending"] == 4  # 1 + 3
        assert sub["dlq_depth"] == 1
        assert sub["status"] == "lagging"  # worst of ok/lagging
        assert sub["consumer_count"] == 2  # max

    def test_projector_worst_status_unknown(self):
        s1 = MagicMock()
        s1.name = "P-order"
        s1.handler_name = "P"
        s1.status = "lagging"
        s1.lag = 2
        s1.pending = 0
        s1.dlq_depth = 0
        s1.consumer_count = 1
        s1.subscription_type = "stream"

        s2 = MagicMock()
        s2.name = "P-payment"
        s2.handler_name = "P"
        s2.status = "unknown"
        s2.lag = None
        s2.pending = 0
        s2.dlq_depth = 0
        s2.consumer_count = 0
        s2.subscription_type = "stream"

        handlers = [{"name": "P", "type": "projector", "stream_categories": []}]
        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            return_value=[s1, s2],
        ):
            merge_subscription_status(handlers, [MagicMock()])

        assert handlers[0]["subscription"]["status"] == "unknown"

    def test_exception_in_collect_does_not_crash(self):
        handlers = [{"name": "H", "type": "event_handler", "stream_categories": []}]
        domain = MagicMock()
        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            side_effect=Exception("Redis down"),
        ):
            # Should not raise
            merge_subscription_status(handlers, [domain])

        assert handlers[0].get("subscription") is None


# ---------------------------------------------------------------------------
# collect_per_handler_trace_metrics
# ---------------------------------------------------------------------------


class TestCollectPerHandlerTraceMetrics:
    def test_returns_empty_when_no_redis(self):
        assert collect_per_handler_trace_metrics(None, 300000) == {}

    def test_returns_empty_on_redis_error(self):
        redis = MagicMock()
        redis.xrange.side_effect = Exception("Connection lost")
        assert collect_per_handler_trace_metrics(redis, 300000) == {}

    def test_counts_completed_and_failed(self):
        now_ms = int(time.time() * 1000)
        stream_id = f"{now_ms}-0".encode()
        redis = MagicMock()
        redis.xrange.return_value = [
            (stream_id, {b"data": _make_trace_entry("handler.completed", "H1", 20)}),
            (stream_id, {b"data": _make_trace_entry("handler.completed", "H1", 30)}),
            (stream_id, {b"data": _make_trace_entry("handler.failed", "H1")}),
            (stream_id, {b"data": _make_trace_entry("handler.completed", "H2", 10)}),
        ]

        result = collect_per_handler_trace_metrics(redis, 300000)

        assert "H1" in result
        assert result["H1"]["processed"] == 2
        assert result["H1"]["failed"] == 1
        assert result["H1"]["error_rate"] == pytest.approx(33.33, abs=0.01)
        assert result["H1"]["avg_latency_ms"] == 25.0  # (20+30)/2

        assert "H2" in result
        assert result["H2"]["processed"] == 1
        assert result["H2"]["failed"] == 0
        assert result["H2"]["error_rate"] == 0.0

    def test_message_dlq_counts_as_failed(self):
        now_ms = int(time.time() * 1000)
        stream_id = f"{now_ms}-0".encode()
        redis = MagicMock()
        redis.xrange.return_value = [
            (stream_id, {b"data": _make_trace_entry("message.dlq", "H1")}),
        ]

        result = collect_per_handler_trace_metrics(redis, 300000)
        assert result["H1"]["failed"] == 1
        assert result["H1"]["processed"] == 0

    def test_skips_entries_without_handler(self):
        now_ms = int(time.time() * 1000)
        stream_id = f"{now_ms}-0".encode()
        trace = json.dumps({"event": "handler.completed", "duration_ms": 10}).encode()
        redis = MagicMock()
        redis.xrange.return_value = [(stream_id, {b"data": trace})]

        result = collect_per_handler_trace_metrics(redis, 300000)
        assert result == {}

    def test_skips_malformed_json(self):
        now_ms = int(time.time() * 1000)
        stream_id = f"{now_ms}-0".encode()
        redis = MagicMock()
        redis.xrange.return_value = [
            (stream_id, {b"data": b"not json"}),
            (stream_id, {b"data": _make_trace_entry("handler.completed", "H1", 10)}),
        ]

        result = collect_per_handler_trace_metrics(redis, 300000)
        assert "H1" in result
        assert result["H1"]["processed"] == 1

    def test_throughput_buckets_populated(self):
        now_ms = int(time.time() * 1000)
        window_ms = 300000
        # Place stream ID near end of window so bucket index is valid
        # The bucket_idx formula is: (ts_ms - (now_ms - window_ms)) // bucket_ms
        # We need ts_ms > (now_ms - window_ms) to get a positive bucket index
        trace_ts = now_ms - 5000  # 5 seconds ago — well within window
        stream_id = f"{trace_ts}-0".encode()
        redis = MagicMock()
        redis.xrange.return_value = [
            (stream_id, {b"data": _make_trace_entry("handler.completed", "H1", 5)}),
        ]

        result = collect_per_handler_trace_metrics(redis, window_ms)
        assert "throughput" in result["H1"]
        assert isinstance(result["H1"]["throughput"], list)
        # At least one bucket should have a count
        assert sum(result["H1"]["throughput"]) >= 1

    def test_handles_string_data_field(self):
        """Redis may return string keys instead of bytes."""
        now_ms = int(time.time() * 1000)
        stream_id = f"{now_ms}-0"
        trace = json.dumps(
            {"event": "handler.completed", "handler": "H1", "duration_ms": 15}
        )
        redis = MagicMock()
        redis.xrange.return_value = [(stream_id, {"data": trace})]

        result = collect_per_handler_trace_metrics(redis, 300000)
        assert "H1" in result
        assert result["H1"]["processed"] == 1

    def test_no_entries(self):
        redis = MagicMock()
        redis.xrange.return_value = []
        assert collect_per_handler_trace_metrics(redis, 300000) == {}


# ---------------------------------------------------------------------------
# collect_recent_messages
# ---------------------------------------------------------------------------


class TestCollectRecentMessages:
    def test_returns_empty_when_no_redis(self):
        assert collect_recent_messages(None, "H1") == []

    def test_returns_empty_on_redis_error(self):
        redis = MagicMock()
        redis.xrevrange.side_effect = Exception("Error")
        assert collect_recent_messages(redis, "H1") == []

    def test_filters_by_handler_name(self):
        now_ms = int(time.time() * 1000)
        sid = f"{now_ms}-0".encode()
        redis = MagicMock()
        redis.xrevrange.return_value = [
            (sid, {b"data": _make_trace_entry("handler.completed", "H1", 10)}),
            (sid, {b"data": _make_trace_entry("handler.completed", "H2", 20)}),
            (sid, {b"data": _make_trace_entry("handler.failed", "H1")}),
        ]

        result = collect_recent_messages(redis, "H1", count=10)
        assert len(result) == 2
        assert all(m["handler"] == "H1" for m in result)

    def test_respects_count_limit(self):
        now_ms = int(time.time() * 1000)
        sid = f"{now_ms}-0".encode()
        entries = [
            (sid, {b"data": _make_trace_entry("handler.completed", "H1", i)})
            for i in range(10)
        ]
        redis = MagicMock()
        redis.xrevrange.return_value = entries

        result = collect_recent_messages(redis, "H1", count=3)
        assert len(result) == 3

    def test_includes_stream_id(self):
        now_ms = int(time.time() * 1000)
        sid = f"{now_ms}-0".encode()
        redis = MagicMock()
        redis.xrevrange.return_value = [
            (sid, {b"data": _make_trace_entry("handler.completed", "H1", 10)}),
        ]

        result = collect_recent_messages(redis, "H1")
        assert len(result) == 1
        assert "_stream_id" in result[0]
        assert result[0]["_stream_id"] == f"{now_ms}-0"

    def test_skips_malformed_json(self):
        now_ms = int(time.time() * 1000)
        sid = f"{now_ms}-0".encode()
        redis = MagicMock()
        redis.xrevrange.return_value = [
            (sid, {b"data": b"bad json"}),
            (sid, {b"data": _make_trace_entry("handler.completed", "H1", 10)}),
        ]

        result = collect_recent_messages(redis, "H1")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _build_summary
# ---------------------------------------------------------------------------


class TestBuildSummary:
    def test_empty_handlers(self):
        summary = _build_summary([])
        assert summary["total"] == 0
        assert summary["healthy"] == 0
        assert summary["lagging"] == 0
        assert summary["unknown"] == 0
        assert summary["error_rate"] == 0.0

    def test_counts_by_type(self):
        handlers = [
            {"type": "event_handler", "subscription": None, "metrics": None},
            {"type": "event_handler", "subscription": None, "metrics": None},
            {"type": "command_handler", "subscription": None, "metrics": None},
        ]
        summary = _build_summary(handlers)
        assert summary["total"] == 3
        assert summary["by_type"]["event_handler"] == 2
        assert summary["by_type"]["command_handler"] == 1

    def test_status_classification(self):
        handlers = [
            {
                "type": "event_handler",
                "subscription": {"status": "ok"},
                "metrics": None,
            },
            {
                "type": "event_handler",
                "subscription": {"status": "lagging"},
                "metrics": None,
            },
            {
                "type": "event_handler",
                "subscription": {"status": "unknown"},
                "metrics": None,
            },
            {"type": "event_handler", "subscription": None, "metrics": None},
        ]
        summary = _build_summary(handlers)
        assert summary["healthy"] == 1
        assert summary["lagging"] == 1
        assert summary["unknown"] == 2  # explicit unknown + None subscription

    def test_error_rate_calculation(self):
        handlers = [
            {
                "type": "event_handler",
                "subscription": None,
                "metrics": {"processed": 90, "failed": 10},
            },
        ]
        summary = _build_summary(handlers)
        assert summary["total_processed"] == 90
        assert summary["total_errors"] == 10
        assert summary["error_rate"] == 10.0


# ---------------------------------------------------------------------------
# API Endpoint Tests
# ---------------------------------------------------------------------------


class TestHandlersListEndpoint:
    def test_returns_200_with_empty_registry(self, client):
        resp = client.get("/api/handlers")
        assert resp.status_code == 200
        data = resp.json()
        assert "handlers" in data
        assert "summary" in data
        assert "window" in data
        assert data["handlers"] == []
        assert data["summary"]["total"] == 0

    def test_invalid_window_returns_400(self, client):
        resp = client.get("/api/handlers?window=99m")
        assert resp.status_code == 400
        assert "Invalid window" in resp.json()["error"]

    def test_valid_windows(self, client):
        for w in ["5m", "15m", "1h", "24h", "7d"]:
            resp = client.get(f"/api/handlers?window={w}")
            assert resp.status_code == 200
            assert resp.json()["window"] == w

    def test_default_window_is_5m(self, client):
        resp = client.get("/api/handlers")
        assert resp.json()["window"] == "5m"


class TestHandlersDetailEndpoint:
    def test_unknown_handler_returns_404(self, client):
        resp = client.get("/api/handlers/NonExistent")
        assert resp.status_code == 404
        assert "not found" in resp.json()["error"]

    def test_invalid_window_returns_400(self, client):
        resp = client.get("/api/handlers/Test?window=bad")
        assert resp.status_code == 400

    def test_returns_recent_messages_field(self, client):
        """Even for non-existent handlers in an empty domain, we get 404."""
        resp = client.get("/api/handlers/Anything?message_count=5")
        assert resp.status_code == 404


@pytest.mark.no_test_domain
class TestHandlersWithMockDomain:
    """Tests using mock domains to verify handler data integration."""

    def _make_observatory_with_handlers(self):
        """Create an Observatory with mock domains containing handlers."""
        part_of = MagicMock()
        part_of.__name__ = "Order"
        part_of.meta_ = MagicMock()
        part_of.meta_.stream_category = "order"

        handlers = defaultdict(set)
        handlers["App.OrderPlaced.v1"] = {MagicMock()}

        cls = _make_mock_handler_cls(
            name="OrderEventHandler",
            handlers=handlers,
            part_of=part_of,
            stream_category="order",
        )
        record = _make_mock_domain_record(
            "OrderEventHandler",
            "myapp.OrderEventHandler",
            "EVENT_HANDLER",
            cls,
        )

        domain = _make_mock_domain(event_handlers={"OrderEventHandler": record})
        # Mock domain_context
        domain.domain_context.return_value.__enter__ = MagicMock()
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)

        # Mock brokers to avoid Redis
        domain.brokers = MagicMock()
        domain.brokers.get.return_value = None

        return Observatory(domains=[domain])

    def test_list_returns_handlers(self):
        obs = self._make_observatory_with_handlers()
        client = TestClient(obs.app)

        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            return_value=[],
        ):
            resp = client.get("/api/handlers")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["handlers"]) == 1
        assert data["handlers"][0]["name"] == "OrderEventHandler"
        assert data["handlers"][0]["type"] == "event_handler"
        assert data["summary"]["total"] == 1

    def test_detail_returns_handler(self):
        obs = self._make_observatory_with_handlers()
        client = TestClient(obs.app)

        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            return_value=[],
        ):
            resp = client.get("/api/handlers/OrderEventHandler")

        assert resp.status_code == 200
        data = resp.json()
        assert data["handler"]["name"] == "OrderEventHandler"
        assert "recent_messages" in data["handler"]

    def test_detail_nonexistent_returns_404(self):
        obs = self._make_observatory_with_handlers()
        client = TestClient(obs.app)

        resp = client.get("/api/handlers/DoesNotExist")
        assert resp.status_code == 404

    def test_metrics_null_without_redis(self):
        obs = self._make_observatory_with_handlers()
        client = TestClient(obs.app)

        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            return_value=[],
        ):
            resp = client.get("/api/handlers")

        data = resp.json()
        assert data["handlers"][0]["metrics"] is None

    def test_subscription_status_failure_graceful(self):
        """If subscription collection raises, handlers still returned."""
        obs = self._make_observatory_with_handlers()
        client = TestClient(obs.app)

        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            side_effect=Exception("Redis down"),
        ):
            resp = client.get("/api/handlers")

        assert resp.status_code == 200
        assert len(resp.json()["handlers"]) == 1


# ---------------------------------------------------------------------------
# Template Tests
# ---------------------------------------------------------------------------


class TestHandlersTemplate:
    def test_handlers_page_returns_200(self, client):
        resp = client.get("/handlers")
        assert resp.status_code == 200

    def test_handlers_page_is_html(self, client):
        resp = client.get("/handlers")
        assert "text/html" in resp.headers["content-type"]

    def test_handlers_page_contains_table(self, client):
        resp = client.get("/handlers")
        assert "handlers-tbody" in resp.text

    def test_handlers_page_contains_tabs(self, client):
        resp = client.get("/handlers")
        assert "handler-tabs" in resp.text
        assert "Commands" in resp.text
        assert "Events" in resp.text
        assert "Projectors" in resp.text
        assert "Subscribers" in resp.text

    def test_handlers_page_contains_search(self, client):
        resp = client.get("/handlers")
        assert "handler-search" in resp.text

    def test_handlers_page_contains_status_filter(self, client):
        resp = client.get("/handlers")
        assert "status-filter" in resp.text

    def test_handlers_page_contains_detail_panel(self, client):
        resp = client.get("/handlers")
        assert "handler-detail" in resp.text

    def test_handlers_page_includes_handlers_js(self, client):
        resp = client.get("/handlers")
        assert "handlers.js" in resp.text

    def test_handlers_page_contains_summary_cards(self, client):
        resp = client.get("/handlers")
        assert "summary-total" in resp.text
        assert "summary-healthy" in resp.text
        assert "summary-lagging" in resp.text
        assert "summary-error-rate" in resp.text


# ---------------------------------------------------------------------------
# Static File Tests
# ---------------------------------------------------------------------------


class TestHandlersStaticFiles:
    def test_handlers_js_served(self, client):
        resp = client.get("/static/js/handlers.js")
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]

    def test_handlers_js_contains_init(self, client):
        resp = client.get("/static/js/handlers.js")
        assert "HandlersView" in resp.text or "init" in resp.text


# ---------------------------------------------------------------------------
# Route Wiring Tests
# ---------------------------------------------------------------------------


class TestRouteWiring:
    def test_create_all_routes_returns_api_router_with_handlers(self, test_domain):
        from fastapi.templating import Jinja2Templates

        from protean.server.observatory import _TEMPLATES_DIR
        from protean.server.observatory.routes import create_all_routes

        templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
        page_router, api_router = create_all_routes([test_domain], templates)

        # API router should have /handlers routes
        api_paths = [r.path for r in api_router.routes]
        assert "/handlers" in api_paths
        assert "/handlers/{name}" in api_paths

    def test_handlers_api_accessible_through_observatory(self, client):
        """Handlers endpoint is accessible at /api/handlers."""
        resp = client.get("/api/handlers")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# create_handlers_router unit test
# ---------------------------------------------------------------------------


class TestCreateHandlersRouter:
    def test_returns_api_router(self):
        router = create_handlers_router([])
        assert hasattr(router, "routes")

    def test_router_has_expected_routes(self):
        router = create_handlers_router([])
        paths = [r.path for r in router.routes]
        assert "/handlers" in paths
        assert "/handlers/{name}" in paths


# ---------------------------------------------------------------------------
# Coverage gap tests
# ---------------------------------------------------------------------------


class TestGetRedis:
    """Cover _get_redis exception path."""

    def test_get_redis_exception_continues(self):
        from protean.server.observatory.routes.handlers import _get_redis

        domain = MagicMock()
        domain.domain_context.return_value.__enter__ = MagicMock(
            side_effect=Exception("boom")
        )
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)

        assert _get_redis([domain]) is None

    def test_get_redis_returns_instance(self):
        from protean.server.observatory.routes.handlers import _get_redis

        mock_redis = MagicMock()
        broker = MagicMock()
        broker.redis_instance = mock_redis

        domain = MagicMock()
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=None)
        ctx.__exit__ = MagicMock(return_value=False)
        domain.domain_context.return_value = ctx
        domain.brokers.get.return_value = broker

        assert _get_redis([domain]) is mock_redis


class TestProjectorFallthrough:
    """Cover projector with empty stream_categories falling to stream_category."""

    def test_projector_empty_stream_categories_falls_through(self):
        """Projector with stream_categories=[] falls through to stream_category."""
        cls = _make_mock_handler_cls(stream_categories=[], stream_category="order")
        result = _infer_stream_categories(cls, "PROJECTOR")
        # Empty list is falsy, so it falls through to stream_category
        assert result == ["order"]


class TestCommandHandlerNoMatchingStream:
    """Cover command handler loop where no stream matches."""

    def test_command_handler_no_matching_stream_status(self):
        status = MagicMock()
        status.name = "commands:payment"
        status.handler_name = "PaymentCH"
        status.status = "ok"

        handlers = [
            {
                "name": "OrderCH",
                "type": "command_handler",
                "stream_categories": ["order"],
            }
        ]
        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            return_value=[status],
        ):
            merge_subscription_status(handlers, [MagicMock()])

        # No match → subscription stays None
        assert handlers[0].get("subscription") is None

    def test_command_handler_empty_stream_categories(self):
        handlers = [
            {
                "name": "EmptyCH",
                "type": "command_handler",
                "stream_categories": [],
            }
        ]
        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            return_value=[],
        ):
            merge_subscription_status(handlers, [MagicMock()])

        assert handlers[0].get("subscription") is None


class TestProjectorNoStatuses:
    """Cover projector/PM path where status_by_handler has no match."""

    def test_projector_no_matching_statuses(self):
        handlers = [
            {
                "name": "OrphanProjector",
                "type": "projector",
                "stream_categories": ["order"],
            }
        ]
        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            return_value=[],
        ):
            merge_subscription_status(handlers, [MagicMock()])

        assert handlers[0].get("subscription") is None


class TestTraceEntryNoDataField:
    """Cover trace entries with missing data field."""

    def test_trace_entry_with_no_data(self):
        now_ms = int(time.time() * 1000)
        stream_id = f"{now_ms}-0".encode()
        redis = MagicMock()
        redis.xrange.return_value = [
            (stream_id, {b"other_field": b"value"}),  # no "data" key
            (stream_id, {b"data": _make_trace_entry("handler.completed", "H1", 10)}),
        ]

        result = collect_per_handler_trace_metrics(redis, 300000)
        assert "H1" in result
        assert result["H1"]["processed"] == 1

    def test_recent_messages_entry_with_no_data(self):
        now_ms = int(time.time() * 1000)
        sid = f"{now_ms}-0".encode()
        redis = MagicMock()
        redis.xrevrange.return_value = [
            (sid, {b"other": b"value"}),  # no "data" key
            (sid, {b"data": _make_trace_entry("handler.completed", "H1", 10)}),
        ]

        result = collect_recent_messages(redis, "H1")
        assert len(result) == 1


@pytest.mark.no_test_domain
class TestEndpointExceptionPaths:
    """Cover exception handling in the list and detail endpoints."""

    def _make_obs_with_redis(self):
        """Create Observatory with a mock domain that has a Redis broker."""
        part_of = MagicMock()
        part_of.__name__ = "Order"
        part_of.meta_ = MagicMock()
        part_of.meta_.stream_category = "order"

        cls = _make_mock_handler_cls(
            name="OrderHandler",
            part_of=part_of,
            stream_category="order",
        )
        record = _make_mock_domain_record(
            "OrderHandler", "app.OrderHandler", "EVENT_HANDLER", cls
        )
        domain = _make_mock_domain(event_handlers={"OrderHandler": record})

        # Set up broker with redis
        mock_redis = MagicMock()
        broker = MagicMock()
        broker.redis_instance = mock_redis

        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=None)
        ctx.__exit__ = MagicMock(return_value=False)
        domain.domain_context.return_value = ctx
        domain.brokers.get.return_value = broker

        obs = Observatory(domains=[domain])
        return obs, mock_redis

    def test_list_trace_metrics_exception_graceful(self):
        """Trace metrics exception in list endpoint doesn't crash."""
        obs, mock_redis = self._make_obs_with_redis()
        client = TestClient(obs.app)

        with (
            patch(
                "protean.server.observatory.routes.handlers.collect_subscription_statuses",
                return_value=[],
            ),
            patch(
                "protean.server.observatory.routes.handlers.collect_per_handler_trace_metrics",
                side_effect=Exception("Redis error"),
            ),
        ):
            resp = client.get("/api/handlers")

        assert resp.status_code == 200
        assert len(resp.json()["handlers"]) == 1

    def test_list_merge_subscription_exception_graceful(self):
        """merge_subscription_status exception in list endpoint caught."""
        obs, _ = self._make_obs_with_redis()
        client = TestClient(obs.app)

        with patch(
            "protean.server.observatory.routes.handlers.merge_subscription_status",
            side_effect=Exception("Subscription error"),
        ):
            resp = client.get("/api/handlers")

        assert resp.status_code == 200

    def test_detail_with_redis_and_metrics(self):
        """Detail endpoint with Redis returns metrics and recent messages."""
        obs, mock_redis = self._make_obs_with_redis()
        client = TestClient(obs.app)

        with (
            patch(
                "protean.server.observatory.routes.handlers.collect_subscription_statuses",
                return_value=[],
            ),
            patch(
                "protean.server.observatory.routes.handlers.collect_per_handler_trace_metrics",
                return_value={"OrderHandler": {"processed": 5, "failed": 0}},
            ),
            patch(
                "protean.server.observatory.routes.handlers.collect_recent_messages",
                return_value=[
                    {"event": "handler.completed", "handler": "OrderHandler"}
                ],
            ),
        ):
            resp = client.get("/api/handlers/OrderHandler")

        assert resp.status_code == 200
        data = resp.json()
        assert data["handler"]["metrics"]["processed"] == 5
        assert len(data["handler"]["recent_messages"]) == 1

    def test_detail_subscription_exception_graceful(self):
        """Subscription exception in detail endpoint doesn't crash."""
        obs, _ = self._make_obs_with_redis()
        client = TestClient(obs.app)

        with patch(
            "protean.server.observatory.routes.handlers.merge_subscription_status",
            side_effect=Exception("Error"),
        ):
            resp = client.get("/api/handlers/OrderHandler")

        assert resp.status_code == 200

    def test_detail_trace_metrics_exception_graceful(self):
        """Trace metrics exception in detail endpoint caught."""
        obs, mock_redis = self._make_obs_with_redis()
        client = TestClient(obs.app)

        with (
            patch(
                "protean.server.observatory.routes.handlers.collect_subscription_statuses",
                return_value=[],
            ),
            patch(
                "protean.server.observatory.routes.handlers.collect_per_handler_trace_metrics",
                side_effect=Exception("Error"),
            ),
        ):
            resp = client.get("/api/handlers/OrderHandler")

        assert resp.status_code == 200

    def test_detail_recent_messages_exception_graceful(self):
        """Recent messages exception in detail endpoint returns empty list."""
        obs, mock_redis = self._make_obs_with_redis()
        client = TestClient(obs.app)

        with (
            patch(
                "protean.server.observatory.routes.handlers.collect_subscription_statuses",
                return_value=[],
            ),
            patch(
                "protean.server.observatory.routes.handlers.collect_per_handler_trace_metrics",
                return_value={},
            ),
            patch(
                "protean.server.observatory.routes.handlers.collect_recent_messages",
                side_effect=Exception("Error"),
            ),
        ):
            resp = client.get("/api/handlers/OrderHandler")

        assert resp.status_code == 200
        assert resp.json()["handler"]["recent_messages"] == []
