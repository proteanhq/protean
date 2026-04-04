"""Tests for trace search and recent traces list endpoints.

Covers:
- GET /timeline/traces/recent — recent correlation chains with summaries
- GET /timeline/traces/search — search by aggregate_id, event_type,
  command_type, stream_category
- Helper functions: _group_by_correlation, _build_trace_summary,
  collect_recent_traces, search_traces
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.server.observatory import Observatory
from protean.server.observatory.routes.timeline import (
    _build_trace_summary,
    _group_by_correlation,
    collect_recent_traces,
    search_traces,
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


class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    total = String(required=True)


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    total = String(required=True)

    class Meta:
        is_event_sourced = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def trace_domain(tmp_path):
    """Domain with two aggregates and multiple correlation chains."""
    domain = Domain(name="TraceTests", root_path=str(tmp_path))
    domain._initialize()
    domain.register(User)
    domain.register(UserRegistered, part_of=User)
    domain.register(UserRenamed, part_of=User)
    domain.register(Order)
    domain.register(OrderPlaced, part_of=Order)
    domain.init(traverse=False)

    with domain.domain_context():
        user_id = str(uuid.uuid4())
        order_id = str(uuid.uuid4())
        user_stream = f"{User.meta_.stream_category}-{user_id}"
        order_stream = f"{Order.meta_.stream_category}-{order_id}"

        # Chain 1: User registration flow (corr-chain-A)
        domain.event_store.store._write(
            user_stream,
            "Test.RegisterUser.v1",
            {"user_id": user_id, "name": "Alice"},
            metadata={
                "headers": {
                    "id": "msg-a-cmd",
                    "type": "Test.RegisterUser.v1",
                    "stream": user_stream,
                    "time": "2026-04-01T10:00:00+00:00",
                },
                "domain": {
                    "kind": "COMMAND",
                    "correlation_id": "corr-chain-A",
                    "causation_id": None,
                    "stream_category": User.meta_.stream_category,
                },
            },
        )
        domain.event_store.store._write(
            user_stream,
            "Test.UserRegistered.v1",
            {"user_id": user_id, "name": "Alice"},
            metadata={
                "headers": {
                    "id": "msg-a-evt",
                    "type": "Test.UserRegistered.v1",
                    "stream": user_stream,
                },
                "domain": {
                    "kind": "EVENT",
                    "correlation_id": "corr-chain-A",
                    "causation_id": "msg-a-cmd",
                    "stream_category": User.meta_.stream_category,
                },
            },
        )

        # Chain 2: Order placement flow (corr-chain-B)
        domain.event_store.store._write(
            order_stream,
            "Test.PlaceOrder.v1",
            {"order_id": order_id, "total": "99.99"},
            metadata={
                "headers": {
                    "id": "msg-b-cmd",
                    "type": "Test.PlaceOrder.v1",
                    "stream": order_stream,
                    "time": "2026-04-01T11:00:00+00:00",
                },
                "domain": {
                    "kind": "COMMAND",
                    "correlation_id": "corr-chain-B",
                    "causation_id": None,
                    "stream_category": Order.meta_.stream_category,
                },
            },
        )
        domain.event_store.store._write(
            order_stream,
            "Test.OrderPlaced.v1",
            {"order_id": order_id, "total": "99.99"},
            metadata={
                "headers": {
                    "id": "msg-b-evt",
                    "type": "Test.OrderPlaced.v1",
                    "stream": order_stream,
                },
                "domain": {
                    "kind": "EVENT",
                    "correlation_id": "corr-chain-B",
                    "causation_id": "msg-b-cmd",
                    "stream_category": Order.meta_.stream_category,
                },
            },
        )

        # Chain 3: User rename (corr-chain-C) — shares user_id with chain A
        domain.event_store.store._write(
            user_stream,
            "Test.RenameUser.v1",
            {"user_id": user_id, "name": "Alice Smith"},
            metadata={
                "headers": {
                    "id": "msg-c-cmd",
                    "type": "Test.RenameUser.v1",
                    "stream": user_stream,
                    "time": "2026-04-01T12:00:00+00:00",
                },
                "domain": {
                    "kind": "COMMAND",
                    "correlation_id": "corr-chain-C",
                    "causation_id": None,
                    "stream_category": User.meta_.stream_category,
                },
            },
        )
        domain.event_store.store._write(
            user_stream,
            "Test.UserRenamed.v1",
            {"user_id": user_id, "name": "Alice Smith"},
            metadata={
                "headers": {
                    "id": "msg-c-evt",
                    "type": "Test.UserRenamed.v1",
                    "stream": user_stream,
                },
                "domain": {
                    "kind": "EVENT",
                    "correlation_id": "corr-chain-C",
                    "causation_id": "msg-c-cmd",
                    "stream_category": User.meta_.stream_category,
                },
            },
        )

        yield domain, user_id, order_id


@pytest.fixture
def trace_client(trace_domain):
    domain, _, _ = trace_domain
    obs = Observatory(domains=[domain])
    return TestClient(obs.app)


@pytest.fixture
def empty_domain(tmp_path):
    """Domain with no events."""
    domain = Domain(name="EmptyTests", root_path=str(tmp_path))
    domain._initialize()
    domain.register(User)
    domain.register(UserRegistered, part_of=User)
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain


# ---------------------------------------------------------------------------
# Tests: _group_by_correlation
# ---------------------------------------------------------------------------


class TestGroupByCorrelation:
    def test_groups_messages_by_correlation_id(self, trace_domain):
        domain, _, _ = trace_domain
        groups = _group_by_correlation([domain])

        assert len(groups) == 3
        assert "corr-chain-A" in groups
        assert "corr-chain-B" in groups
        assert "corr-chain-C" in groups

    def test_each_group_has_correct_count(self, trace_domain):
        domain, _, _ = trace_domain
        groups = _group_by_correlation([domain])

        assert len(groups["corr-chain-A"]) == 2
        assert len(groups["corr-chain-B"]) == 2
        assert len(groups["corr-chain-C"]) == 2

    def test_groups_sorted_by_global_position(self, trace_domain):
        domain, _, _ = trace_domain
        groups = _group_by_correlation([domain])

        for cid, grp in groups.items():
            positions = [msg.get("global_position", 0) for msg, _ in grp]
            assert positions == sorted(positions), f"Group {cid} not sorted"

    def test_returns_empty_for_empty_store(self, empty_domain):
        groups = _group_by_correlation([empty_domain])
        assert groups == {}

    def test_excludes_messages_without_correlation_id(self, trace_domain):
        domain, _, _ = trace_domain

        # Write a message without correlation_id
        domain.event_store.store._write(
            "tracetests::orphan-1",
            "Test.Orphan.v1",
            {"data": "orphan"},
            metadata={
                "headers": {"id": "msg-orphan"},
                "domain": {"kind": "EVENT"},
            },
        )

        groups = _group_by_correlation([domain])
        # Still only 3 chains — orphan excluded
        assert len(groups) == 3


# ---------------------------------------------------------------------------
# Tests: _build_trace_summary
# ---------------------------------------------------------------------------


class TestBuildTraceSummary:
    def test_builds_summary_with_correct_fields(self, trace_domain):
        domain, _, _ = trace_domain
        groups = _group_by_correlation([domain])

        summary = _build_trace_summary("corr-chain-A", groups["corr-chain-A"])

        assert summary["correlation_id"] == "corr-chain-A"
        assert summary["root_type"] == "Test.RegisterUser.v1"
        assert summary["event_count"] == 2
        assert summary["started_at"] is not None
        assert isinstance(summary["streams"], list)
        assert len(summary["streams"]) > 0

    def test_root_type_is_first_message_type(self, trace_domain):
        domain, _, _ = trace_domain
        groups = _group_by_correlation([domain])

        summary_b = _build_trace_summary("corr-chain-B", groups["corr-chain-B"])
        assert summary_b["root_type"] == "Test.PlaceOrder.v1"

    def test_streams_are_unique(self, trace_domain):
        domain, _, _ = trace_domain
        groups = _group_by_correlation([domain])

        # Chain A: both messages are in the same user stream
        summary = _build_trace_summary("corr-chain-A", groups["corr-chain-A"])
        assert len(summary["streams"]) == len(set(summary["streams"]))


# ---------------------------------------------------------------------------
# Tests: collect_recent_traces
# ---------------------------------------------------------------------------


class TestCollectRecentTraces:
    def test_returns_all_traces(self, trace_domain):
        domain, _, _ = trace_domain
        traces = collect_recent_traces([domain])

        assert len(traces) == 3

    def test_sorted_by_started_at_descending(self, trace_domain):
        domain, _, _ = trace_domain
        traces = collect_recent_traces([domain])

        started_times = [t["started_at"] for t in traces if t["started_at"]]
        assert len(started_times) > 0
        assert started_times == sorted(started_times, reverse=True)

    def test_respects_limit(self, trace_domain):
        domain, _, _ = trace_domain
        traces = collect_recent_traces([domain], limit=2)

        assert len(traces) == 2

    def test_returns_empty_for_no_events(self, empty_domain):
        traces = collect_recent_traces([empty_domain])
        assert traces == []

    def test_each_trace_has_required_fields(self, trace_domain):
        domain, _, _ = trace_domain
        traces = collect_recent_traces([domain])

        assert len(traces) > 0
        for trace in traces:
            assert "correlation_id" in trace
            assert "root_type" in trace
            assert "event_count" in trace
            assert "started_at" in trace
            assert "streams" in trace


# ---------------------------------------------------------------------------
# Tests: search_traces
# ---------------------------------------------------------------------------


class TestSearchTraces:
    def test_search_by_aggregate_id(self, trace_domain):
        domain, user_id, _ = trace_domain
        results = search_traces([domain], aggregate_id=user_id)

        # Chains A and C both contain messages for user_id
        assert len(results) == 2
        corr_ids = {r["correlation_id"] for r in results}
        assert "corr-chain-A" in corr_ids
        assert "corr-chain-C" in corr_ids

    def test_search_by_event_type(self, trace_domain):
        domain, _, _ = trace_domain
        results = search_traces([domain], event_type="Test.OrderPlaced.v1")

        assert len(results) == 1
        assert results[0]["correlation_id"] == "corr-chain-B"

    def test_search_by_command_type(self, trace_domain):
        domain, _, _ = trace_domain
        results = search_traces([domain], command_type="Test.RenameUser.v1")

        assert len(results) == 1
        assert results[0]["correlation_id"] == "corr-chain-C"

    def test_search_by_stream_category(self, trace_domain):
        domain, _, _ = trace_domain
        results = search_traces([domain], stream_category=User.meta_.stream_category)

        # Chains A and C are in user streams
        assert len(results) == 2
        corr_ids = {r["correlation_id"] for r in results}
        assert "corr-chain-A" in corr_ids
        assert "corr-chain-C" in corr_ids

    def test_search_by_order_stream_category(self, trace_domain):
        domain, _, _ = trace_domain
        results = search_traces([domain], stream_category=Order.meta_.stream_category)

        assert len(results) == 1
        assert results[0]["correlation_id"] == "corr-chain-B"

    def test_search_respects_limit(self, trace_domain):
        domain, user_id, _ = trace_domain
        results = search_traces([domain], aggregate_id=user_id, limit=1)

        assert len(results) == 1

    def test_search_returns_empty_for_no_match(self, trace_domain):
        domain, _, _ = trace_domain
        results = search_traces([domain], event_type="NonExistent.Type.v1")

        assert results == []

    def test_search_returns_empty_for_empty_store(self, empty_domain):
        results = search_traces([empty_domain], event_type="Test.UserRegistered.v1")
        assert results == []

    def test_search_raises_valueerror_without_params(self, trace_domain):
        domain, _, _ = trace_domain
        with pytest.raises(ValueError, match="At least one search parameter"):
            search_traces([domain])


# ---------------------------------------------------------------------------
# Tests: _extract_correlation_id edge cases
# ---------------------------------------------------------------------------


class TestExtractCorrelationId:
    def test_returns_none_for_missing_metadata(self):
        from protean.server.observatory.routes.timeline import _extract_correlation_id

        assert _extract_correlation_id({}) is None

    def test_returns_none_for_non_dict_metadata(self):
        from protean.server.observatory.routes.timeline import _extract_correlation_id

        assert _extract_correlation_id({"metadata": "not-a-dict"}) is None

    def test_returns_none_for_missing_domain(self):
        from protean.server.observatory.routes.timeline import _extract_correlation_id

        assert _extract_correlation_id({"metadata": {"headers": {}}}) is None

    def test_returns_none_for_non_dict_domain(self):
        from protean.server.observatory.routes.timeline import _extract_correlation_id

        assert _extract_correlation_id({"metadata": {"domain": "not-a-dict"}}) is None

    def test_extracts_correlation_id(self):
        from protean.server.observatory.routes.timeline import _extract_correlation_id

        msg = {"metadata": {"domain": {"correlation_id": "corr-123"}}}
        assert _extract_correlation_id(msg) == "corr-123"


# ---------------------------------------------------------------------------
# Tests: _group_by_correlation edge cases
# ---------------------------------------------------------------------------


class TestGroupByCorrelationEdgeCases:
    def test_excludes_snapshot_messages(self, trace_domain):
        domain, _, _ = trace_domain

        # Write a snapshot message
        domain.event_store.store._write(
            "tracetests:snapshot-user-1",
            "SNAPSHOT",
            {"data": "snapshot"},
            metadata={
                "headers": {"id": "msg-snap"},
                "domain": {"kind": "EVENT", "correlation_id": "corr-snap"},
            },
        )

        groups = _group_by_correlation([domain])
        # Snapshot excluded — corr-snap should not appear
        assert "corr-snap" not in groups

    def test_handles_broken_domain_gracefully(self, trace_domain):
        from unittest.mock import MagicMock

        domain, _, _ = trace_domain

        broken = MagicMock()
        broken.domain_context.side_effect = Exception("broken")
        broken.event_store.store.conn_info = {"database_uri": "broken://unique"}

        # Should still return groups from the working domain
        groups = _group_by_correlation([domain, broken])
        assert len(groups) == 3


# ---------------------------------------------------------------------------
# Tests: _build_trace_summary edge cases
# ---------------------------------------------------------------------------


class TestBuildTraceSummaryEdgeCases:
    def test_handles_non_dict_metadata(self):
        group = [
            (
                {
                    "type": "Test.Cmd.v1",
                    "stream_name": "test::x-1",
                    "global_position": 1,
                    "metadata": "not-a-dict",
                },
                "test",
            )
        ]
        summary = _build_trace_summary("corr-1", group)
        assert summary["root_type"] == "Test.Cmd.v1"

    def test_handles_non_dict_headers(self):
        group = [
            (
                {
                    "type": "Test.Cmd.v1",
                    "stream_name": "test::x-1",
                    "global_position": 1,
                    "metadata": {"headers": "not-a-dict"},
                },
                "test",
            )
        ]
        summary = _build_trace_summary("corr-1", group)
        assert summary["root_type"] == "Test.Cmd.v1"

    def test_falls_back_to_headers_type(self):
        group = [
            (
                {
                    "stream_name": "test::x-1",
                    "global_position": 1,
                    "metadata": {"headers": {"type": "Hdr.Type.v1"}},
                },
                "test",
            )
        ]
        summary = _build_trace_summary("corr-1", group)
        assert summary["root_type"] == "Hdr.Type.v1"

    def test_datetime_time_produces_isoformat(self):
        from datetime import datetime, timezone

        dt = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
        group = [
            (
                {
                    "type": "Test.Cmd.v1",
                    "stream_name": "test::x-1",
                    "global_position": 1,
                    "time": dt,
                    "metadata": {},
                },
                "test",
            )
        ]
        summary = _build_trace_summary("corr-1", group)
        assert summary["started_at"] == "2026-04-01T12:00:00+00:00"

    def test_falls_back_to_headers_time(self):
        group = [
            (
                {
                    "type": "Test.Cmd.v1",
                    "stream_name": "test::x-1",
                    "global_position": 1,
                    "metadata": {"headers": {"time": "2026-04-01T10:00:00+00:00"}},
                },
                "test",
            )
        ]
        summary = _build_trace_summary("corr-1", group)
        assert summary["started_at"] == "2026-04-01T10:00:00+00:00"


# ---------------------------------------------------------------------------
# Tests: API endpoints
# ---------------------------------------------------------------------------


class TestRecentTracesEndpoint:
    def test_returns_200_with_traces(self, trace_client):
        resp = trace_client.get("/api/timeline/traces/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert "traces" in data
        assert "count" in data
        assert data["count"] == 3
        assert len(data["traces"]) == 3

    def test_respects_limit_param(self, trace_client):
        resp = trace_client.get("/api/timeline/traces/recent?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert len(data["traces"]) == 1

    def test_trace_summary_shape(self, trace_client):
        resp = trace_client.get("/api/timeline/traces/recent")
        data = resp.json()
        assert len(data["traces"]) > 0
        trace = data["traces"][0]
        assert "correlation_id" in trace
        assert "root_type" in trace
        assert "event_count" in trace
        assert "started_at" in trace
        assert "streams" in trace

    def test_empty_store_returns_empty_list(self, tmp_path):
        domain = Domain(name="EmptyAPI", root_path=str(tmp_path))
        domain._initialize()
        domain.init(traverse=False)
        with domain.domain_context():
            obs = Observatory(domains=[domain])
            client = TestClient(obs.app)
            resp = client.get("/api/timeline/traces/recent")
            assert resp.status_code == 200
            data = resp.json()
            assert data["traces"] == []
            assert data["count"] == 0


class TestSearchTracesEndpoint:
    def test_search_by_event_type(self, trace_client):
        resp = trace_client.get(
            "/api/timeline/traces/search?event_type=Test.OrderPlaced.v1"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["traces"][0]["correlation_id"] == "corr-chain-B"

    def test_search_by_aggregate_id(self, trace_domain, trace_client):
        _, user_id, _ = trace_domain
        resp = trace_client.get(f"/api/timeline/traces/search?aggregate_id={user_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_search_by_command_type(self, trace_client):
        resp = trace_client.get(
            "/api/timeline/traces/search?command_type=Test.PlaceOrder.v1"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_search_by_stream_category(self, trace_domain, trace_client):
        domain, _, _ = trace_domain
        cat = Order.meta_.stream_category
        resp = trace_client.get(f"/api/timeline/traces/search?stream_category={cat}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_search_no_params_returns_400(self, trace_client):
        resp = trace_client.get("/api/timeline/traces/search")
        assert resp.status_code == 400
        data = resp.json()
        assert "detail" in data

    def test_search_no_results_returns_empty(self, trace_client):
        resp = trace_client.get(
            "/api/timeline/traces/search?event_type=NonExistent.Type.v1"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["traces"] == []
        assert data["count"] == 0

    def test_search_respects_limit(self, trace_domain, trace_client):
        _, user_id, _ = trace_domain
        resp = trace_client.get(
            f"/api/timeline/traces/search?aggregate_id={user_id}&limit=1"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1


class TestTraceRouteWiring:
    def test_recent_traces_route_included(self, trace_client):
        resp = trace_client.get("/api/timeline/traces/recent")
        assert resp.status_code == 200

    def test_search_traces_route_included(self, trace_client):
        resp = trace_client.get(
            "/api/timeline/traces/search?event_type=Test.OrderPlaced.v1"
        )
        assert resp.status_code == 200
