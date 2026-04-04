"""Tests for causation tree enrichment with timing and handler data.

Covers:
- CausationNode new fields (handler, duration_ms, delta_ms) serialize via asdict()
- _build_causation_tree_from_group computes delta_ms from parent/child timestamps
- _build_causation_tree_from_group enriches nodes from traces_by_message_id
- build_correlation_response includes total_duration_ms
- Graceful fallback: all new fields are None when no trace data
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.port.event_store import CausationNode
from protean.server.observatory.routes.timeline import (
    _build_causation_tree_from_group,
    _load_traces_for_correlation,
    _sum_tree_duration,
    build_correlation_response,
)

pytestmark = pytest.mark.no_test_domain


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------


class UserRegistered(BaseEvent):
    user_id = Identifier(required=True)
    name = String(required=True)


class UserRenamed(BaseEvent):
    user_id = Identifier(required=True)
    name = String(required=True)


class User(BaseAggregate):
    user_id = Identifier(identifier=True)
    name = String(required=True)

    class Meta:
        is_event_sourced = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def correlated_domain(tmp_path):
    """Create a domain with correlated messages (real event store)."""
    domain = Domain(name="EnrichmentTests", root_path=str(tmp_path))
    domain._initialize()
    domain.register(User)
    domain.register(UserRegistered, part_of=User)
    domain.register(UserRenamed, part_of=User)
    domain.init(traverse=False)

    with domain.domain_context():
        corr_id = "corr-enrich-001"
        user_id = str(uuid.uuid4())
        stream = f"{User.meta_.stream_category}-{user_id}"

        # Root command
        domain.event_store.store._write(
            stream,
            "Test.RegisterUser.v1",
            {"user_id": user_id, "name": "Alice"},
            metadata={
                "headers": {
                    "id": "msg-root-cmd",
                    "type": "Test.RegisterUser.v1",
                    "stream": stream,
                },
                "domain": {
                    "kind": "COMMAND",
                    "correlation_id": corr_id,
                    "causation_id": None,
                },
            },
        )

        # Event caused by command
        domain.event_store.store._write(
            stream,
            "Test.UserRegistered.v1",
            {"user_id": user_id, "name": "Alice"},
            metadata={
                "headers": {
                    "id": "msg-evt-registered",
                    "type": "Test.UserRegistered.v1",
                    "stream": stream,
                },
                "domain": {
                    "kind": "EVENT",
                    "correlation_id": corr_id,
                    "causation_id": "msg-root-cmd",
                },
            },
        )

        # Second event caused by first event
        domain.event_store.store._write(
            stream,
            "Test.UserRenamed.v1",
            {"user_id": user_id, "name": "Alice Smith"},
            metadata={
                "headers": {
                    "id": "msg-evt-renamed",
                    "type": "Test.UserRenamed.v1",
                    "stream": stream,
                },
                "domain": {
                    "kind": "EVENT",
                    "correlation_id": corr_id,
                    "causation_id": "msg-evt-registered",
                },
            },
        )

        yield domain, corr_id, user_id, stream


def _make_timed_group(
    base_time: datetime,
) -> list[dict]:
    """Create a synthetic correlation group with precise timestamps."""
    return [
        {
            "type": "Test.RegisterUser.v1",
            "stream_name": "test::user-1",
            "global_position": 1,
            "time": base_time,
            "metadata": {
                "headers": {"id": "msg-root-cmd"},
                "domain": {
                    "kind": "COMMAND",
                    "correlation_id": "corr-timed",
                    "causation_id": None,
                },
            },
        },
        {
            "type": "Test.UserRegistered.v1",
            "stream_name": "test::user-1",
            "global_position": 2,
            "time": base_time + timedelta(milliseconds=50),
            "metadata": {
                "headers": {"id": "msg-evt-registered"},
                "domain": {
                    "kind": "EVENT",
                    "correlation_id": "corr-timed",
                    "causation_id": "msg-root-cmd",
                },
            },
        },
        {
            "type": "Test.UserRenamed.v1",
            "stream_name": "test::user-1",
            "global_position": 3,
            "time": base_time + timedelta(milliseconds=120),
            "metadata": {
                "headers": {"id": "msg-evt-renamed"},
                "domain": {
                    "kind": "EVENT",
                    "correlation_id": "corr-timed",
                    "causation_id": "msg-evt-registered",
                },
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tests: CausationNode serialization with new fields
# ---------------------------------------------------------------------------


class TestCausationNodeNewFields:
    def test_defaults_to_none(self):
        node = CausationNode(
            message_id="m1",
            message_type="SomeEvent",
            kind="EVENT",
            stream="test::user-1",
            time=None,
            global_position=1,
        )
        assert node.handler is None
        assert node.duration_ms is None
        assert node.delta_ms is None

    def test_asdict_includes_new_fields(self):
        node = CausationNode(
            message_id="m1",
            message_type="SomeEvent",
            kind="EVENT",
            stream="test::user-1",
            time="2026-04-01T12:00:00+00:00",
            global_position=1,
            handler="UserProjector",
            duration_ms=23.45,
            delta_ms=50.0,
        )
        d = asdict(node)
        assert d["handler"] == "UserProjector"
        assert d["duration_ms"] == 23.45
        assert d["delta_ms"] == 50.0
        assert d["children"] == []

    def test_asdict_with_none_new_fields(self):
        node = CausationNode(
            message_id="m1",
            message_type="SomeEvent",
            kind="EVENT",
            stream="test::user-1",
            time=None,
            global_position=1,
        )
        d = asdict(node)
        assert d["handler"] is None
        assert d["duration_ms"] is None
        assert d["delta_ms"] is None

    def test_nested_tree_serialization(self):
        child = CausationNode(
            message_id="c1",
            message_type="ChildEvent",
            kind="EVENT",
            stream="test::user-1",
            time=None,
            global_position=2,
            handler="ChildHandler",
            duration_ms=10.0,
            delta_ms=5.0,
        )
        root = CausationNode(
            message_id="r1",
            message_type="RootCmd",
            kind="COMMAND",
            stream="test::user-1",
            time=None,
            global_position=1,
            handler=None,
            duration_ms=None,
            delta_ms=None,
            children=[child],
        )
        d = asdict(root)
        assert len(d["children"]) == 1
        assert d["children"][0]["handler"] == "ChildHandler"
        assert d["children"][0]["duration_ms"] == 10.0
        assert d["children"][0]["delta_ms"] == 5.0


# ---------------------------------------------------------------------------
# Tests: Tree builder computes delta_ms
# ---------------------------------------------------------------------------


class TestTreeBuilderDeltaMs:
    def test_computes_delta_between_parent_and_child(self, correlated_domain):
        domain, _, _, _ = correlated_domain
        store = domain.event_store.store

        base_time = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        group = _make_timed_group(base_time)

        tree = _build_causation_tree_from_group(store, group)
        assert tree is not None

        # Root has no parent, so delta_ms is None
        assert tree.delta_ms is None

        # First child: 50ms after root
        assert len(tree.children) > 0
        child = tree.children[0]
        assert child.delta_ms is not None
        assert abs(child.delta_ms - 50.0) < 0.01

        # Grandchild: 70ms after first child (120 - 50)
        assert len(child.children) > 0
        grandchild = child.children[0]
        assert grandchild.delta_ms is not None
        assert abs(grandchild.delta_ms - 70.0) < 0.01

    def test_delta_ms_with_iso_string_timestamps(self, correlated_domain):
        domain, _, _, _ = correlated_domain
        store = domain.event_store.store

        group = [
            {
                "type": "Test.Evt.v1",
                "stream_name": "test::x-1",
                "global_position": 1,
                "time": "2026-04-01T12:00:00+00:00",
                "metadata": {
                    "headers": {"id": "a1"},
                    "domain": {"kind": "EVENT"},
                },
            },
            {
                "type": "Test.Evt.v1",
                "stream_name": "test::x-1",
                "global_position": 2,
                "time": "2026-04-01T12:00:00.100000+00:00",
                "metadata": {
                    "headers": {"id": "a2"},
                    "domain": {"kind": "EVENT", "causation_id": "a1"},
                },
            },
        ]

        tree = _build_causation_tree_from_group(store, group)
        assert tree is not None
        assert len(tree.children) > 0
        # 100ms delta
        assert tree.children[0].delta_ms is not None
        assert abs(tree.children[0].delta_ms - 100.0) < 0.01

    def test_delta_ms_none_when_no_timestamps(self, correlated_domain):
        domain, _, _, _ = correlated_domain
        store = domain.event_store.store

        group = [
            {
                "type": "Test.Evt.v1",
                "stream_name": "test::x-1",
                "global_position": 1,
                "metadata": {
                    "headers": {"id": "a1"},
                    "domain": {"kind": "EVENT"},
                },
            },
            {
                "type": "Test.Evt.v1",
                "stream_name": "test::x-1",
                "global_position": 2,
                "metadata": {
                    "headers": {"id": "a2"},
                    "domain": {"kind": "EVENT", "causation_id": "a1"},
                },
            },
        ]

        tree = _build_causation_tree_from_group(store, group)
        assert tree is not None
        assert tree.delta_ms is None
        assert len(tree.children) > 0
        assert tree.children[0].delta_ms is None


# ---------------------------------------------------------------------------
# Tests: Tree builder enrichment from traces
# ---------------------------------------------------------------------------


class TestTreeBuilderTraceEnrichment:
    def test_enriches_handler_and_duration(self, correlated_domain):
        domain, _, _, _ = correlated_domain
        store = domain.event_store.store

        base_time = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        group = _make_timed_group(base_time)

        traces = {
            "msg-root-cmd": {
                "handler": "RegisterUserHandler",
                "duration_ms": 15.5,
            },
            "msg-evt-registered": {
                "handler": "UserProjector",
                "duration_ms": 8.2,
            },
        }

        tree = _build_causation_tree_from_group(
            store, group, traces_by_message_id=traces
        )
        assert tree is not None

        # Root node enriched
        assert tree.handler == "RegisterUserHandler"
        assert tree.duration_ms == 15.5

        # First child enriched
        assert len(tree.children) > 0
        child = tree.children[0]
        assert child.handler == "UserProjector"
        assert child.duration_ms == 8.2

        # Grandchild not in traces — None
        assert len(child.children) > 0
        grandchild = child.children[0]
        assert grandchild.handler is None
        assert grandchild.duration_ms is None

    def test_graceful_fallback_no_traces(self, correlated_domain):
        domain, corr_id, _, _ = correlated_domain
        store = domain.event_store.store
        group = store._load_correlation_group(corr_id)

        # No traces dict → all enrichment fields None
        tree = _build_causation_tree_from_group(store, group)
        assert tree is not None
        assert tree.handler is None
        assert tree.duration_ms is None

        # Children also None
        assert len(tree.children) > 0
        assert tree.children[0].handler is None
        assert tree.children[0].duration_ms is None

    def test_empty_traces_dict(self, correlated_domain):
        domain, corr_id, _, _ = correlated_domain
        store = domain.event_store.store
        group = store._load_correlation_group(corr_id)

        tree = _build_causation_tree_from_group(store, group, traces_by_message_id={})
        assert tree is not None
        assert tree.handler is None
        assert tree.duration_ms is None


# ---------------------------------------------------------------------------
# Tests: _sum_tree_duration
# ---------------------------------------------------------------------------


class TestSumTreeDuration:
    def test_sums_all_durations(self):
        child = CausationNode(
            message_id="c1",
            message_type="E",
            kind="EVENT",
            stream="s",
            time=None,
            global_position=2,
            duration_ms=10.0,
        )
        root = CausationNode(
            message_id="r1",
            message_type="C",
            kind="COMMAND",
            stream="s",
            time=None,
            global_position=1,
            duration_ms=5.5,
            children=[child],
        )
        assert _sum_tree_duration(root) == 15.5

    def test_handles_none_durations(self):
        child = CausationNode(
            message_id="c1",
            message_type="E",
            kind="EVENT",
            stream="s",
            time=None,
            global_position=2,
        )
        root = CausationNode(
            message_id="r1",
            message_type="C",
            kind="COMMAND",
            stream="s",
            time=None,
            global_position=1,
            children=[child],
        )
        assert _sum_tree_duration(root) == 0.0


# ---------------------------------------------------------------------------
# Tests: build_correlation_response includes total_duration_ms
# ---------------------------------------------------------------------------


class TestCorrelationResponseTotalDuration:
    def test_includes_total_duration_ms_key(self, correlated_domain):
        """Response includes total_duration_ms even when no trace data."""
        domain, corr_id, _, _ = correlated_domain

        result = build_correlation_response([domain], corr_id)
        assert result is not None
        assert "total_duration_ms" in result
        # No trace data available → None
        assert result["total_duration_ms"] is None

    def test_event_count_preserved(self, correlated_domain):
        domain, corr_id, _, _ = correlated_domain

        result = build_correlation_response([domain], corr_id)
        assert result is not None
        assert result["event_count"] == 3

    def test_tree_present_in_response(self, correlated_domain):
        domain, corr_id, _, _ = correlated_domain

        result = build_correlation_response([domain], corr_id)
        assert result is not None
        assert result["tree"] is not None
        tree = result["tree"]
        # Tree includes new fields
        assert "handler" in tree
        assert "duration_ms" in tree
        assert "delta_ms" in tree

    def test_returns_none_for_unknown_correlation(self, correlated_domain):
        domain, _, _, _ = correlated_domain
        result = build_correlation_response([domain], "nonexistent-corr-id")
        assert result is None


# ---------------------------------------------------------------------------
# Tests: _parse_time_ms edge cases (via _build_causation_tree_from_group)
# ---------------------------------------------------------------------------


class TestDeltaMsEdgeCases:
    def test_invalid_iso_string_produces_none_delta(self, correlated_domain):
        """Covers the ValueError/TypeError branch in _parse_time_ms."""
        domain, _, _, _ = correlated_domain
        store = domain.event_store.store

        group = [
            {
                "type": "Test.Root.v1",
                "stream_name": "test::x-1",
                "global_position": 1,
                "time": "not-a-valid-iso-timestamp",
                "metadata": {
                    "headers": {"id": "r1"},
                    "domain": {"kind": "COMMAND"},
                },
            },
            {
                "type": "Test.Child.v1",
                "stream_name": "test::x-1",
                "global_position": 2,
                "time": "also-not-valid",
                "metadata": {
                    "headers": {"id": "c1"},
                    "domain": {"kind": "EVENT", "causation_id": "r1"},
                },
            },
        ]
        tree = _build_causation_tree_from_group(store, group)
        assert tree is not None
        # Invalid timestamps → None parsed → delta_ms is None
        assert tree.delta_ms is None
        assert len(tree.children) > 0
        assert tree.children[0].delta_ms is None

    def test_non_string_non_datetime_time_returns_none(self, correlated_domain):
        """Covers the final return None in _parse_time_ms (e.g. int)."""
        domain, _, _, _ = correlated_domain
        store = domain.event_store.store

        group = [
            {
                "type": "Test.Root.v1",
                "stream_name": "test::x-1",
                "global_position": 1,
                "time": 12345,  # Not a datetime or string
                "metadata": {
                    "headers": {"id": "r1"},
                    "domain": {"kind": "COMMAND"},
                },
            },
            {
                "type": "Test.Child.v1",
                "stream_name": "test::x-1",
                "global_position": 2,
                "time": 67890,
                "metadata": {
                    "headers": {"id": "c1"},
                    "domain": {"kind": "EVENT", "causation_id": "r1"},
                },
            },
        ]
        tree = _build_causation_tree_from_group(store, group)
        assert tree is not None
        assert tree.delta_ms is None
        assert len(tree.children) > 0
        assert tree.children[0].delta_ms is None


# ---------------------------------------------------------------------------
# Tests: _load_traces_for_correlation
# ---------------------------------------------------------------------------


def _make_redis_stream_entry(trace_dict: dict) -> tuple:
    """Create a (stream_id, fields) tuple mimicking Redis XRANGE output."""
    return ("1234567890-0", {"data": json.dumps(trace_dict)})


class TestLoadTracesForCorrelation:
    def test_returns_empty_when_no_redis(self, correlated_domain):
        """Domains without Redis broker return empty traces."""
        domain, corr_id, _, _ = correlated_domain
        result = _load_traces_for_correlation([domain], corr_id)
        assert result == {}

    def test_loads_handler_completed_traces(self, correlated_domain):
        """Extracts handler and duration_ms from handler.completed entries."""
        domain, corr_id, _, _ = correlated_domain

        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            _make_redis_stream_entry(
                {
                    "event": "handler.completed",
                    "correlation_id": corr_id,
                    "message_id": "msg-root-cmd",
                    "handler": "RegisterUserHandler",
                    "duration_ms": 15.5,
                }
            ),
            _make_redis_stream_entry(
                {
                    "event": "handler.completed",
                    "correlation_id": corr_id,
                    "message_id": "msg-evt-registered",
                    "handler": "UserProjector",
                    "duration_ms": 8.2,
                }
            ),
        ]

        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis

        with patch.object(domain, "brokers") as mock_brokers:
            mock_brokers.get.return_value = mock_broker
            result = _load_traces_for_correlation([domain], corr_id)

        assert len(result) == 2
        assert result["msg-root-cmd"]["handler"] == "RegisterUserHandler"
        assert result["msg-root-cmd"]["duration_ms"] == 15.5
        assert result["msg-evt-registered"]["handler"] == "UserProjector"
        assert result["msg-evt-registered"]["duration_ms"] == 8.2

    def test_filters_by_correlation_id(self, correlated_domain):
        """Only traces matching the requested correlation_id are returned."""
        domain, corr_id, _, _ = correlated_domain

        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            _make_redis_stream_entry(
                {
                    "event": "handler.completed",
                    "correlation_id": corr_id,
                    "message_id": "msg-1",
                    "handler": "H1",
                    "duration_ms": 10.0,
                }
            ),
            _make_redis_stream_entry(
                {
                    "event": "handler.completed",
                    "correlation_id": "other-corr-id",
                    "message_id": "msg-2",
                    "handler": "H2",
                    "duration_ms": 20.0,
                }
            ),
        ]

        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis

        with patch.object(domain, "brokers") as mock_brokers:
            mock_brokers.get.return_value = mock_broker
            result = _load_traces_for_correlation([domain], corr_id)

        assert len(result) == 1
        assert "msg-1" in result
        assert "msg-2" not in result

    def test_ignores_non_handler_events(self, correlated_domain):
        """Only handler.completed and handler.failed are included."""
        domain, corr_id, _, _ = correlated_domain

        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            _make_redis_stream_entry(
                {
                    "event": "outbox.published",
                    "correlation_id": corr_id,
                    "message_id": "msg-1",
                    "handler": None,
                }
            ),
            _make_redis_stream_entry(
                {
                    "event": "handler.started",
                    "correlation_id": corr_id,
                    "message_id": "msg-2",
                    "handler": "H1",
                }
            ),
            _make_redis_stream_entry(
                {
                    "event": "handler.failed",
                    "correlation_id": corr_id,
                    "message_id": "msg-3",
                    "handler": "H3",
                    "duration_ms": 5.0,
                }
            ),
        ]

        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis

        with patch.object(domain, "brokers") as mock_brokers:
            mock_brokers.get.return_value = mock_broker
            result = _load_traces_for_correlation([domain], corr_id)

        assert len(result) == 1
        assert "msg-3" in result
        assert result["msg-3"]["handler"] == "H3"

    def test_coerces_duration_to_float(self, correlated_domain):
        """String or Decimal-like duration_ms values are coerced to float."""
        domain, corr_id, _, _ = correlated_domain

        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            _make_redis_stream_entry(
                {
                    "event": "handler.completed",
                    "correlation_id": corr_id,
                    "message_id": "msg-1",
                    "handler": "H1",
                    "duration_ms": "23.45",  # String from JSON
                }
            ),
        ]

        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis

        with patch.object(domain, "brokers") as mock_brokers:
            mock_brokers.get.return_value = mock_broker
            result = _load_traces_for_correlation([domain], corr_id)

        assert result["msg-1"]["duration_ms"] == 23.45
        assert isinstance(result["msg-1"]["duration_ms"], float)

    def test_invalid_duration_becomes_none(self, correlated_domain):
        """Non-parseable duration_ms becomes None."""
        domain, corr_id, _, _ = correlated_domain

        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            _make_redis_stream_entry(
                {
                    "event": "handler.completed",
                    "correlation_id": corr_id,
                    "message_id": "msg-1",
                    "handler": "H1",
                    "duration_ms": "not-a-number",
                }
            ),
        ]

        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis

        with patch.object(domain, "brokers") as mock_brokers:
            mock_brokers.get.return_value = mock_broker
            result = _load_traces_for_correlation([domain], corr_id)

        assert result["msg-1"]["duration_ms"] is None

    def test_skips_entries_without_data(self, correlated_domain):
        """Entries missing the 'data' field are silently skipped."""
        domain, corr_id, _, _ = correlated_domain

        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            ("1234567890-0", {}),  # No 'data' key
            _make_redis_stream_entry(
                {
                    "event": "handler.completed",
                    "correlation_id": corr_id,
                    "message_id": "msg-1",
                    "handler": "H1",
                    "duration_ms": 5.0,
                }
            ),
        ]

        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis

        with patch.object(domain, "brokers") as mock_brokers:
            mock_brokers.get.return_value = mock_broker
            result = _load_traces_for_correlation([domain], corr_id)

        assert len(result) == 1

    def test_handles_malformed_json_gracefully(self, correlated_domain):
        """Malformed JSON in trace entries is skipped without crashing."""
        domain, corr_id, _, _ = correlated_domain

        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            ("1234567890-0", {"data": "not-valid-json{{{"}),
            _make_redis_stream_entry(
                {
                    "event": "handler.completed",
                    "correlation_id": corr_id,
                    "message_id": "msg-1",
                    "handler": "H1",
                    "duration_ms": 5.0,
                }
            ),
        ]

        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis

        with patch.object(domain, "brokers") as mock_brokers:
            mock_brokers.get.return_value = mock_broker
            result = _load_traces_for_correlation([domain], corr_id)

        assert len(result) == 1

    def test_handles_bytes_data(self, correlated_domain):
        """Redis may return data as bytes — these should be decoded."""
        domain, corr_id, _, _ = correlated_domain

        trace_json = json.dumps(
            {
                "event": "handler.completed",
                "correlation_id": corr_id,
                "message_id": "msg-1",
                "handler": "H1",
                "duration_ms": 7.0,
            }
        )
        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            ("1234567890-0", {b"data": trace_json.encode("utf-8")}),
        ]

        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis

        with patch.object(domain, "brokers") as mock_brokers:
            mock_brokers.get.return_value = mock_broker
            result = _load_traces_for_correlation([domain], corr_id)

        assert len(result) == 1
        assert result["msg-1"]["handler"] == "H1"

    def test_xrange_failure_returns_empty(self, correlated_domain):
        """Redis XRANGE failure returns empty dict gracefully."""
        domain, corr_id, _, _ = correlated_domain

        mock_redis = MagicMock()
        mock_redis.xrange.side_effect = Exception("Redis down")

        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis

        with patch.object(domain, "brokers") as mock_brokers:
            mock_brokers.get.return_value = mock_broker
            result = _load_traces_for_correlation([domain], corr_id)

        assert result == {}

    def test_skips_entries_without_message_id(self, correlated_domain):
        """Trace entries missing message_id are skipped."""
        domain, corr_id, _, _ = correlated_domain

        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            _make_redis_stream_entry(
                {
                    "event": "handler.completed",
                    "correlation_id": corr_id,
                    # No message_id
                    "handler": "H1",
                    "duration_ms": 5.0,
                }
            ),
        ]

        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis

        with patch.object(domain, "brokers") as mock_brokers:
            mock_brokers.get.return_value = mock_broker
            result = _load_traces_for_correlation([domain], corr_id)

        assert len(result) == 0

    def test_none_duration_preserved(self, correlated_domain):
        """When duration_ms is absent from trace, None is stored."""
        domain, corr_id, _, _ = correlated_domain

        mock_redis = MagicMock()
        mock_redis.xrange.return_value = [
            _make_redis_stream_entry(
                {
                    "event": "handler.completed",
                    "correlation_id": corr_id,
                    "message_id": "msg-1",
                    "handler": "H1",
                    # No duration_ms
                }
            ),
        ]

        mock_broker = MagicMock()
        mock_broker.redis_instance = mock_redis

        with patch.object(domain, "brokers") as mock_brokers:
            mock_brokers.get.return_value = mock_broker
            result = _load_traces_for_correlation([domain], corr_id)

        assert result["msg-1"]["duration_ms"] is None
