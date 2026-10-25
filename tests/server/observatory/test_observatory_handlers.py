"""Tests for Observatory Handlers API endpoints and supporting functions.

Tests for:
- routes/handlers.py: _extract_handled_messages, _handler_type_label,
  _infer_aggregate, _infer_stream_categories, collect_handler_metadata,
  merge_subscription_status, collect_per_handler_trace_metrics,
  collect_recent_messages, _build_summary, create_handlers_router
- routes/__init__.py: updated create_all_routes wiring
"""

import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector
from protean.core.subscriber import BaseSubscriber
from protean.fields import Identifier, String
from protean.server.observatory import Observatory
from protean.server.observatory.routes.handlers import (
    _build_summary,
    _extract_handled_messages,
    _get_redis,
    _handler_type_label,
    _infer_aggregate,
    _infer_stream_categories,
    collect_handler_metadata,
    collect_per_handler_trace_metrics,
    collect_recent_messages,
    create_handlers_router,
    merge_subscription_status,
)
from protean.server.tracing import TRACE_STREAM
from protean.utils import fqn
from protean.utils.mixins import handle
from tests.server.observatory.conftest import route_paths
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


class _FakeRedis:
    """In-memory stand-in for the raw ``redis.Redis`` client.

    The core test lane has no Redis server, so the stream reads the Observatory
    and the subscription-status collector make are answered from dicts here.
    """

    def __init__(self, *, lengths=None, groups=None, traces=None):
        self.lengths = lengths or {}
        self.groups = groups or {}
        # Trace stream entries, oldest first, as (stream_id, fields) pairs.
        self.traces = traces or []

    def xlen(self, name):
        return self.lengths.get(name, 0)

    def xinfo_groups(self, name):
        return self.groups.get(name, [])

    def xinfo_consumers(self, name, group):
        return []

    def xrange(self, name, min="-", max="+", count=None):
        if name != TRACE_STREAM:
            return []
        floor = 0 if min == "-" else int(str(min).split("-")[0])
        return [
            (sid, fields)
            for sid, fields in self.traces
            if int(_sid_str(sid).split("-")[0]) >= floor
        ]

    def xrevrange(self, name, max="+", min="-", count=None):
        if name != TRACE_STREAM:
            return []
        entries = list(reversed(self.traces))
        return entries[:count] if count else entries


def _sid_str(sid):
    return sid.decode() if isinstance(sid, bytes) else sid


def _inline_config():
    return {"brokers": {"default": {"provider": "inline"}}}


def _build_domain(name="Handlers", *, redis=None, event_store_subscriptions=False):
    """A real domain with one handler of each kind.

    With ``redis`` set, the domain reads this directory's ``domain.toml`` (a
    Redis broker and stream subscriptions) and its broker's raw client is
    replaced by that fake. Without it, the domain uses the inline broker, which
    has no Redis client at all.
    """
    if redis is not None:
        domain = Domain(name=name, root_path=__file__)
    else:
        domain = Domain(name=name, config=_inline_config())

    sub_opts = {"subscription_type": "event_store"} if event_store_subscriptions else {}

    @domain.aggregate
    class Order(BaseAggregate):
        customer = String()

    @domain.aggregate
    class Payment(BaseAggregate):
        amount = String()

    @domain.event(part_of=Order)
    class OrderPlaced(BaseEvent):
        order_id = Identifier(required=True)

    @domain.event(part_of=Order)
    class OrderShipped(BaseEvent):
        order_id = Identifier(required=True)

    @domain.event(part_of=Payment)
    class PaymentReceived(BaseEvent):
        order_id = Identifier(required=True)

    @domain.command(part_of=Order)
    class PlaceOrder(BaseCommand):
        order_id = Identifier(required=True)

    @domain.event_handler(part_of=Order, **sub_opts)
    class OrderEventHandler(BaseEventHandler):
        # Declared out of alphabetical order, so a sorted result shows sorting.
        @handle(OrderShipped)
        def a_on_shipped(self, event):
            pass

        @handle(OrderPlaced)
        def b_on_placed(self, event):
            pass

    @domain.event_handler(part_of=Order, **sub_opts)
    class CatchAllHandler(BaseEventHandler):
        @handle("$any")
        def on_any(self, event):
            pass

        @handle(OrderPlaced)
        def on_placed(self, event):
            pass

    @domain.command_handler(part_of=Order)
    class OrderCommandHandler(BaseCommandHandler):
        @handle(PlaceOrder)
        def place(self, command):
            pass

    @domain.projection
    class OrderSummary(BaseProjection):
        order_id = Identifier(identifier=True)

    @domain.projector(
        projector_for=OrderSummary, aggregates=[Order, Payment], **sub_opts
    )
    class OrderSummaryProjector(BaseProjector):
        @handle(OrderPlaced)
        def on_placed(self, event):
            pass

        @handle(PaymentReceived)
        def on_paid(self, event):
            pass

    @domain.subscriber(stream="external:payments")
    class PaymentSubscriber(BaseSubscriber):
        def __call__(self, data):
            pass

    @domain.process_manager(
        stream_categories=[Order.meta_.stream_category, Payment.meta_.stream_category]
    )
    class OrderFulfillment:
        order_id = Identifier(required=True)

        @handle(OrderPlaced, start=True, correlate="order_id")
        def on_placed(self, event):
            pass

        @handle(PaymentReceived, end=True, correlate="order_id")
        def on_paid(self, event):
            pass

    domain.init(traverse=False)
    if redis is not None:
        domain.brokers.get("default").redis_instance = redis

    return domain, SimpleNamespace(
        Order=Order,
        Payment=Payment,
        OrderEventHandler=OrderEventHandler,
        CatchAllHandler=CatchAllHandler,
        OrderCommandHandler=OrderCommandHandler,
        OrderSummary=OrderSummary,
        OrderSummaryProjector=OrderSummaryProjector,
        PaymentSubscriber=PaymentSubscriber,
        OrderFulfillment=OrderFulfillment,
    )


@pytest.fixture(scope="module")
def handlers_domain():
    # Read-only in every test that uses it, so one build serves the module.
    return _build_domain()


def _group(name, *, lag, pending=0, consumers=1):
    """One ``XINFO GROUPS`` entry, as redis-py returns it."""
    return {
        "name": name,
        "pending": pending,
        "lag": lag,
        "consumers": consumers,
        "last-delivered-id": "0-0",
    }


def _by_name(handlers):
    return {h["name"]: h for h in handlers}


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


def _now_sid(offset_ms=0):
    return f"{int(time.time() * 1000) - offset_ms}-0".encode()


# ---------------------------------------------------------------------------
# _extract_handled_messages
# ---------------------------------------------------------------------------


class TestExtractHandledMessages:
    def test_handler_without_handled_messages(self, handlers_domain):
        """A subscriber has no ``_handlers`` map; a plain class has neither."""

        class NotAHandler:
            pass

        _, ns = handlers_domain
        assert _extract_handled_messages(ns.PaymentSubscriber) == []
        assert _extract_handled_messages(NotAHandler) == []

    def test_empty_handlers_map(self):
        domain = Domain(name="EmptyHandler", config=_inline_config())

        @domain.aggregate
        class Order(BaseAggregate):
            customer = String()

        @domain.event_handler(part_of=Order)
        class IdleHandler(BaseEventHandler):
            pass

        domain.init(traverse=False)
        assert _extract_handled_messages(IdleHandler) == []

    def test_extracts_class_names_from_type_strings(self, handlers_domain):
        _, ns = handlers_domain
        result = _extract_handled_messages(ns.OrderEventHandler)
        assert result == ["OrderPlaced", "OrderShipped"]

    def test_skips_any_key(self, handlers_domain):
        _, ns = handlers_domain
        assert "$any" in ns.CatchAllHandler._handlers

        result = _extract_handled_messages(ns.CatchAllHandler)
        assert result == ["OrderPlaced"]

    def test_single_part_type_string(self):
        """Type string without dots uses entire key.

        Registered handlers always carry dotted ``__type__`` keys, so a plain
        class holds the undotted key here.
        """

        class UndottedKeys:
            _handlers = {"SimpleType": set()}

        assert _extract_handled_messages(UndottedKeys) == ["SimpleType"]

    def test_sorted_output(self, handlers_domain):
        _, ns = handlers_domain
        keys = [k.split(".")[1] for k in ns.OrderEventHandler._handlers]
        assert keys == ["OrderShipped", "OrderPlaced"]

        assert _extract_handled_messages(ns.OrderEventHandler) == [
            "OrderPlaced",
            "OrderShipped",
        ]


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
    def test_from_part_of(self, handlers_domain):
        _, ns = handlers_domain
        assert _infer_aggregate(ns.OrderEventHandler) == "Order"

    def test_from_projector_for(self, handlers_domain):
        _, ns = handlers_domain
        assert _infer_aggregate(ns.OrderSummaryProjector) == "OrderSummary"

    def test_no_aggregate(self, handlers_domain):
        _, ns = handlers_domain
        assert _infer_aggregate(ns.PaymentSubscriber) is None

    def test_no_meta(self):
        class NotAHandler:
            pass

        assert _infer_aggregate(NotAHandler) is None


# ---------------------------------------------------------------------------
# _infer_stream_categories
# ---------------------------------------------------------------------------


class TestInferStreamCategories:
    def test_projector_with_stream_categories(self, handlers_domain):
        _, ns = handlers_domain
        result = _infer_stream_categories(ns.OrderSummaryProjector, "PROJECTOR")
        assert result == ["handlers::order", "handlers::payment"]

    def test_process_manager_with_stream_categories(self, handlers_domain):
        _, ns = handlers_domain
        result = _infer_stream_categories(ns.OrderFulfillment, "PROCESS_MANAGER")
        assert result == ["handlers::order", "handlers::payment"]

    def test_event_handler_with_stream_category(self, handlers_domain):
        _, ns = handlers_domain
        result = _infer_stream_categories(ns.OrderEventHandler, "EVENT_HANDLER")
        assert result == ["handlers::order"]

    def test_command_handler_with_stream_category(self, handlers_domain):
        _, ns = handlers_domain
        result = _infer_stream_categories(ns.OrderCommandHandler, "COMMAND_HANDLER")
        assert result == ["handlers::order:command"]

    def test_projector_type_without_list_falls_back_to_stream_category(
        self, handlers_domain
    ):
        """A projector-type class with no ``stream_categories`` list uses its
        single ``stream_category``."""
        _, ns = handlers_domain
        result = _infer_stream_categories(ns.OrderEventHandler, "PROJECTOR")
        assert result == ["handlers::order"]

    def test_no_stream_info(self, handlers_domain):
        _, ns = handlers_domain
        result = _infer_stream_categories(ns.PaymentSubscriber, "EVENT_HANDLER")
        assert result == []

    def test_no_meta(self):
        class NotAHandler:
            pass

        assert _infer_stream_categories(NotAHandler, "EVENT_HANDLER") == []


# ---------------------------------------------------------------------------
# collect_handler_metadata
# ---------------------------------------------------------------------------


class TestCollectHandlerMetadata:
    def test_empty_domain(self):
        domain = Domain(name="Empty", config=_inline_config())
        domain.init(traverse=False)
        assert collect_handler_metadata([domain]) == []

    def test_event_handler(self, handlers_domain):
        domain, ns = handlers_domain
        h = _by_name(collect_handler_metadata([domain]))["OrderEventHandler"]

        assert h["qualname"] == fqn(ns.OrderEventHandler)
        assert h["type"] == "event_handler"
        assert h["domain"] == "Handlers"
        assert h["aggregate"] == "Order"
        assert h["stream_categories"] == ["handlers::order"]
        assert h["handled_messages"] == ["OrderPlaced", "OrderShipped"]
        assert h["subscription"] is None
        assert h["metrics"] is None

    def test_command_handler(self, handlers_domain):
        domain, _ = handlers_domain
        h = _by_name(collect_handler_metadata([domain]))["OrderCommandHandler"]
        assert h["type"] == "command_handler"
        assert h["handled_messages"] == ["PlaceOrder"]

    def test_projector(self, handlers_domain):
        domain, _ = handlers_domain
        h = _by_name(collect_handler_metadata([domain]))["OrderSummaryProjector"]
        assert h["type"] == "projector"
        assert h["aggregate"] == "OrderSummary"
        assert h["stream_categories"] == ["handlers::order", "handlers::payment"]

    def test_subscriber(self, handlers_domain):
        domain, _ = handlers_domain
        h = _by_name(collect_handler_metadata([domain]))["PaymentSubscriber"]
        assert h["type"] == "subscriber"
        assert h["handled_messages"] == ["external:payments"]
        assert h["stream_categories"] == ["external:payments"]

    def test_multiple_domains(self, handlers_domain):
        domain, _ = handlers_domain
        empty = Domain(name="Empty", config=_inline_config())
        empty.init(traverse=False)

        result = collect_handler_metadata([domain, empty])
        assert len(result) == 5
        assert {h["domain"] for h in result} == {"Handlers"}

    def test_multiple_handler_types_combined(self, handlers_domain):
        domain, _ = handlers_domain
        types = {h["type"] for h in collect_handler_metadata([domain])}
        assert types == {"event_handler", "command_handler", "projector", "subscriber"}


# ---------------------------------------------------------------------------
# merge_subscription_status
# ---------------------------------------------------------------------------


def _seed_event_store_lag(domain, handler_cls, category, *, read_up_to):
    """Write three events to ``category`` and a position at ``read_up_to``.

    Returns the time stamped on the position record, which is what the
    collector measures seconds of lag from.
    """
    store = domain.event_store.store
    with domain.domain_context():
        for n in range(3):
            store._write(f"{category}-1", "Happened", {"n": n})
        position_stream = f"position-{fqn(handler_cls)}-{category}"
        store._write(position_stream, "Read", {"position": read_up_to})
        return datetime.fromisoformat(store._read_last_message(position_stream)["time"])


class TestMergeSubscriptionStatus:
    def test_no_statuses_leaves_subscription_none(self, test_domain):
        handlers = [
            {"name": "TestHandler", "type": "event_handler", "stream_categories": []}
        ]
        merge_subscription_status(handlers, [test_domain])
        assert handlers[0].get("subscription") is None

    def test_event_handler_direct_match(self):
        fake = _FakeRedis()
        domain, ns = _build_domain(redis=fake)
        fake.groups["handlers::order"] = [
            _group(fqn(ns.OrderEventHandler), lag=0, consumers=1)
        ]

        handlers = collect_handler_metadata([domain])
        merge_subscription_status(handlers, [domain])

        sub = _by_name(handlers)["OrderEventHandler"]["subscription"]
        assert sub is not None
        assert sub["status"] == "ok"
        assert sub["lag"] == 0
        assert sub["consumer_count"] == 1

    def test_command_handler_matches_by_stream(self):
        fake = _FakeRedis()
        domain, _ = _build_domain(redis=fake)
        category = "handlers::order:command"
        fake.groups[category] = [
            _group(f"protean.server.engine.Commands:{category}", lag=0)
        ]

        handlers = collect_handler_metadata([domain])
        merge_subscription_status(handlers, [domain])

        sub = _by_name(handlers)["OrderCommandHandler"]["subscription"]
        assert sub is not None
        assert sub["status"] == "ok"
        assert sub["subscription_type"] == "stream"

    def test_projector_aggregates_across_streams(self):
        fake = _FakeRedis()
        domain, ns = _build_domain(redis=fake)
        group = fqn(ns.OrderSummaryProjector)
        fake.groups["handlers::order"] = [_group(group, lag=2, pending=1, consumers=1)]
        fake.groups["handlers::payment"] = [
            _group(group, lag=5, pending=3, consumers=2)
        ]
        fake.lengths["handlers::payment:dlq"] = 1

        handlers = collect_handler_metadata([domain])
        merge_subscription_status(handlers, [domain])

        sub = _by_name(handlers)["OrderSummaryProjector"]["subscription"]
        assert sub is not None
        assert sub["lag"] == 7  # 2 + 5
        assert sub["pending"] == 4  # 1 + 3
        assert sub["dlq_depth"] == 1
        assert sub["status"] == "lagging"
        assert sub["consumer_count"] == 2  # max

    def test_projector_worst_of_ok_and_lagging_is_lagging(self):
        fake = _FakeRedis()
        domain, ns = _build_domain(redis=fake)
        group = fqn(ns.OrderSummaryProjector)
        fake.groups["handlers::order"] = [_group(group, lag=0)]
        fake.groups["handlers::payment"] = [_group(group, lag=4)]

        handlers = collect_handler_metadata([domain])
        merge_subscription_status(handlers, [domain])

        sub = _by_name(handlers)["OrderSummaryProjector"]["subscription"]
        assert sub["status"] == "lagging"
        assert sub["lag"] == 4

    def test_projector_worst_status_unknown(self):
        """One stream lags and the other has no consumer group, so its lag is
        unknown; the projector reports the worse of the two."""
        fake = _FakeRedis()
        domain, ns = _build_domain(redis=fake)
        fake.groups["handlers::order"] = [_group(fqn(ns.OrderSummaryProjector), lag=2)]

        handlers = collect_handler_metadata([domain])
        merge_subscription_status(handlers, [domain])

        sub = _by_name(handlers)["OrderSummaryProjector"]["subscription"]
        assert sub["status"] == "unknown"
        assert sub["lag"] == 2

    def test_event_handler_carries_lag_seconds(self):
        domain, ns = _build_domain(event_store_subscriptions=True)
        written_at = _seed_event_store_lag(
            domain, ns.OrderEventHandler, "handlers::order", read_up_to=1
        )
        domain.clock = FrozenClock(written_at + timedelta(seconds=8.5))

        handlers = collect_handler_metadata([domain])
        merge_subscription_status(handlers, [domain])

        sub = _by_name(handlers)["OrderEventHandler"]["subscription"]
        assert sub["subscription_type"] == "event_store"
        assert sub["lag_seconds"] == 8.5

    def test_projector_lag_seconds_is_max_not_sum(self):
        """Seconds-lag aggregates as the worst (max) stream staleness, not a sum."""
        domain, ns = _build_domain(event_store_subscriptions=True)
        order_at = _seed_event_store_lag(
            domain, ns.OrderSummaryProjector, "handlers::order", read_up_to=1
        )
        payment_at = _seed_event_store_lag(
            domain, ns.OrderSummaryProjector, "handlers::payment", read_up_to=1
        )
        now = payment_at + timedelta(seconds=3)
        domain.clock = FrozenClock(now)

        handlers = collect_handler_metadata([domain])
        merge_subscription_status(handlers, [domain])

        sub = _by_name(handlers)["OrderSummaryProjector"]["subscription"]
        order_lag = (now - order_at).total_seconds()
        assert sub["lag_seconds"] == pytest.approx(order_lag)  # max, not order + 3

    def test_projector_lag_seconds_none_when_all_none(self):
        """Stream subscriptions report no seconds, so the aggregate stays None."""
        fake = _FakeRedis()
        domain, ns = _build_domain(redis=fake)
        group = fqn(ns.OrderSummaryProjector)
        fake.groups["handlers::order"] = [_group(group, lag=2)]
        fake.groups["handlers::payment"] = [_group(group, lag=1)]

        handlers = collect_handler_metadata([domain])
        merge_subscription_status(handlers, [domain])

        sub = _by_name(handlers)["OrderSummaryProjector"]["subscription"]
        assert sub["lag"] == 3
        assert sub["lag_seconds"] is None

    def test_exception_in_collect_does_not_crash(self, test_domain):
        handlers = [{"name": "H", "type": "event_handler", "stream_categories": []}]
        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            side_effect=Exception("Redis down"),
        ):
            # Should not raise
            merge_subscription_status(handlers, [test_domain])

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
        sid = _now_sid()
        redis = _FakeRedis(
            traces=[
                (sid, {b"data": _make_trace_entry("handler.completed", "H1", 20)}),
                (sid, {b"data": _make_trace_entry("handler.completed", "H1", 30)}),
                (sid, {b"data": _make_trace_entry("handler.failed", "H1")}),
                (sid, {b"data": _make_trace_entry("handler.completed", "H2", 10)}),
            ]
        )

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
        redis = _FakeRedis(
            traces=[(_now_sid(), {b"data": _make_trace_entry("message.dlq", "H1")})]
        )

        result = collect_per_handler_trace_metrics(redis, 300000)
        assert result["H1"]["failed"] == 1
        assert result["H1"]["processed"] == 0

    def test_skips_entries_without_handler(self):
        trace = json.dumps({"event": "handler.completed", "duration_ms": 10}).encode()
        redis = _FakeRedis(traces=[(_now_sid(), {b"data": trace})])

        assert collect_per_handler_trace_metrics(redis, 300000) == {}

    def test_skips_malformed_json(self):
        sid = _now_sid()
        redis = _FakeRedis(
            traces=[
                (sid, {b"data": b"not json"}),
                (sid, {b"data": _make_trace_entry("handler.completed", "H1", 10)}),
            ]
        )

        result = collect_per_handler_trace_metrics(redis, 300000)
        assert "H1" in result
        assert result["H1"]["processed"] == 1

    def test_skips_entries_without_data_field(self):
        sid = _now_sid()
        redis = _FakeRedis(
            traces=[
                (sid, {b"other_field": b"value"}),
                (sid, {b"data": _make_trace_entry("handler.completed", "H1", 10)}),
            ]
        )

        result = collect_per_handler_trace_metrics(redis, 300000)
        assert "H1" in result
        assert result["H1"]["processed"] == 1

    def test_throughput_buckets_populated(self):
        # 5 seconds ago is well inside the window, so the entry lands in a bucket.
        redis = _FakeRedis(
            traces=[
                (
                    _now_sid(offset_ms=5000),
                    {b"data": _make_trace_entry("handler.completed", "H1", 5)},
                ),
            ]
        )

        result = collect_per_handler_trace_metrics(redis, 300000)
        assert "throughput" in result["H1"]
        assert isinstance(result["H1"]["throughput"], list)
        assert sum(result["H1"]["throughput"]) >= 1

    def test_handles_string_data_field(self):
        """Redis may return string keys instead of bytes."""
        trace = json.dumps(
            {"event": "handler.completed", "handler": "H1", "duration_ms": 15}
        )
        redis = _FakeRedis(traces=[(_sid_str(_now_sid()), {"data": trace})])

        result = collect_per_handler_trace_metrics(redis, 300000)
        assert "H1" in result
        assert result["H1"]["processed"] == 1

    def test_no_entries(self):
        assert collect_per_handler_trace_metrics(_FakeRedis(), 300000) == {}


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
        sid = _now_sid()
        redis = _FakeRedis(
            traces=[
                (sid, {b"data": _make_trace_entry("handler.completed", "H1", 10)}),
                (sid, {b"data": _make_trace_entry("handler.completed", "H2", 20)}),
                (sid, {b"data": _make_trace_entry("handler.failed", "H1")}),
            ]
        )

        result = collect_recent_messages(redis, "H1", count=10)
        assert len(result) == 2
        assert all(m["handler"] == "H1" for m in result)

    def test_respects_count_limit(self):
        sid = _now_sid()
        redis = _FakeRedis(
            traces=[
                (sid, {b"data": _make_trace_entry("handler.completed", "H1", i)})
                for i in range(10)
            ]
        )

        result = collect_recent_messages(redis, "H1", count=3)
        assert len(result) == 3

    def test_includes_stream_id(self):
        sid = _now_sid()
        redis = _FakeRedis(
            traces=[
                (sid, {b"data": _make_trace_entry("handler.completed", "H1", 10)}),
            ]
        )

        result = collect_recent_messages(redis, "H1")
        assert len(result) == 1
        assert result[0]["_stream_id"] == sid.decode()

    @pytest.mark.parametrize(
        "unreadable",
        [{b"data": b"bad json"}, {b"other": b"value"}],
        ids=["malformed-json", "no-data-field"],
    )
    def test_skips_unreadable_entries(self, unreadable):
        sid = _now_sid()
        redis = _FakeRedis(
            traces=[
                (sid, unreadable),
                (sid, {b"data": _make_trace_entry("handler.completed", "H1", 10)}),
            ]
        )

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


class TestHandlersWithRegisteredHandlers:
    """The endpoints serve a domain with handlers and an inline broker (no Redis)."""

    @pytest.fixture
    def handlers_client(self, handlers_domain):
        domain, _ = handlers_domain
        return TestClient(Observatory(domains=[domain]).app)

    def test_list_returns_handlers(self, handlers_client):
        resp = handlers_client.get("/api/handlers")

        assert resp.status_code == 200
        data = resp.json()
        h = _by_name(data["handlers"])["OrderEventHandler"]
        assert h["type"] == "event_handler"
        assert data["summary"]["total"] == 5

    def test_detail_returns_handler(self, handlers_client):
        resp = handlers_client.get("/api/handlers/OrderEventHandler")

        assert resp.status_code == 200
        data = resp.json()
        assert data["handler"]["name"] == "OrderEventHandler"
        assert data["handler"]["recent_messages"] == []

    def test_detail_nonexistent_returns_404(self, handlers_client):
        resp = handlers_client.get("/api/handlers/DoesNotExist")
        assert resp.status_code == 404

    def test_metrics_null_without_redis(self, handlers_client):
        resp = handlers_client.get("/api/handlers")

        for h in resp.json()["handlers"]:
            assert h["metrics"] is None

    def test_subscription_status_failure_graceful(self, handlers_client):
        """If subscription collection raises, handlers still returned."""
        with patch(
            "protean.server.observatory.routes.handlers.collect_subscription_statuses",
            side_effect=Exception("Redis down"),
        ):
            resp = handlers_client.get("/api/handlers")

        assert resp.status_code == 200
        assert len(resp.json()["handlers"]) == 5


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
        _page_router, api_router = create_all_routes([test_domain], templates)

        # API router should have /handlers routes
        api_paths = route_paths(api_router.routes)
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
# _get_redis
# ---------------------------------------------------------------------------


class TestGetRedis:
    def test_returns_the_broker_redis_client(self):
        fake = _FakeRedis()
        domain, _ = _build_domain(redis=fake)
        assert _get_redis([domain]) is fake

    def test_no_redis_client_on_inline_broker(self, handlers_domain):
        domain, _ = handlers_domain
        assert _get_redis([domain]) is None

    def test_skips_a_broken_domain(self, handlers_domain):
        """A domain whose context cannot be entered is skipped, and the search
        moves on to the next domain."""
        broken, _ = handlers_domain
        fake = _FakeRedis()
        working, _ = _build_domain(name="Working", redis=fake)

        with patch.object(broken, "domain_context", side_effect=Exception("boom")):
            assert _get_redis([broken]) is None
            assert _get_redis([broken, working]) is fake


class TestMergeSubscriptionStatusNoMatch:
    def test_command_handler_no_matching_stream_status(self):
        """A dispatcher status for another stream does not attach to the handler."""
        fake = _FakeRedis()
        domain, _ = _build_domain(redis=fake)
        handlers = [
            {
                "name": "PaymentCommandHandler",
                "type": "command_handler",
                "stream_categories": ["handlers::payment:command"],
            }
        ]
        merge_subscription_status(handlers, [domain])

        assert handlers[0].get("subscription") is None

    def test_command_handler_empty_stream_categories(self, test_domain):
        handlers = [
            {"name": "EmptyCH", "type": "command_handler", "stream_categories": []}
        ]
        merge_subscription_status(handlers, [test_domain])

        assert handlers[0].get("subscription") is None

    def test_projector_no_matching_statuses(self, test_domain):
        handlers = [
            {
                "name": "OrphanProjector",
                "type": "projector",
                "stream_categories": ["order"],
            }
        ]
        merge_subscription_status(handlers, [test_domain])

        assert handlers[0].get("subscription") is None


class TestEndpointsWithRedis:
    """The endpoints with a Redis broker whose raw client is a fake, and the
    failures each endpoint survives."""

    def _client(self, fake=None):
        domain, _ = _build_domain(redis=fake or _FakeRedis())
        return TestClient(Observatory(domains=[domain]).app)

    def test_list_trace_metrics_exception_graceful(self):
        """Trace metrics exception in list endpoint doesn't crash."""
        client = self._client()

        with patch(
            "protean.server.observatory.routes.handlers.collect_per_handler_trace_metrics",
            side_effect=Exception("Redis error"),
        ):
            resp = client.get("/api/handlers")

        assert resp.status_code == 200
        assert len(resp.json()["handlers"]) == 5

    def test_list_merge_subscription_exception_graceful(self):
        """merge_subscription_status exception in list endpoint caught."""
        client = self._client()

        with patch(
            "protean.server.observatory.routes.handlers.merge_subscription_status",
            side_effect=Exception("Subscription error"),
        ):
            resp = client.get("/api/handlers")

        assert resp.status_code == 200

    def test_list_includes_trace_metrics(self):
        sid = _now_sid()
        fake = _FakeRedis(
            traces=[
                (
                    sid,
                    {
                        b"data": _make_trace_entry(
                            "handler.completed", "OrderEventHandler", 10
                        )
                    },
                )
            ]
        )
        resp = self._client(fake).get("/api/handlers")

        handlers = _by_name(resp.json()["handlers"])
        assert handlers["OrderEventHandler"]["metrics"]["processed"] == 1
        assert handlers["OrderCommandHandler"]["metrics"] is None

    def test_detail_with_redis_and_metrics(self):
        """Detail endpoint with Redis returns metrics and recent messages."""
        sid = _now_sid()
        fake = _FakeRedis(
            traces=[
                (
                    sid,
                    {
                        b"data": _make_trace_entry(
                            "handler.completed", "OrderEventHandler", 10
                        )
                    },
                )
                for _ in range(5)
            ]
            + [(sid, {b"data": _make_trace_entry("handler.completed", "Other", 10)})]
        )
        resp = self._client(fake).get("/api/handlers/OrderEventHandler")

        assert resp.status_code == 200
        data = resp.json()
        assert data["handler"]["metrics"]["processed"] == 5
        assert len(data["handler"]["recent_messages"]) == 5

    def test_detail_subscription_exception_graceful(self):
        """Subscription exception in detail endpoint doesn't crash."""
        client = self._client()

        with patch(
            "protean.server.observatory.routes.handlers.merge_subscription_status",
            side_effect=Exception("Error"),
        ):
            resp = client.get("/api/handlers/OrderEventHandler")

        assert resp.status_code == 200

    def test_detail_trace_metrics_exception_graceful(self):
        """Trace metrics exception in detail endpoint caught."""
        client = self._client()

        with patch(
            "protean.server.observatory.routes.handlers.collect_per_handler_trace_metrics",
            side_effect=Exception("Error"),
        ):
            resp = client.get("/api/handlers/OrderEventHandler")

        assert resp.status_code == 200

    def test_detail_recent_messages_exception_graceful(self):
        """Recent messages exception in detail endpoint returns empty list."""
        client = self._client()

        with patch(
            "protean.server.observatory.routes.handlers.collect_recent_messages",
            side_effect=Exception("Error"),
        ):
            resp = client.get("/api/handlers/OrderEventHandler")

        assert resp.status_code == 200
        assert resp.json()["handler"]["recent_messages"] == []
