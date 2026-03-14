"""Tests for Observatory Timeline API endpoints and supporting functions.

Covers:
- routes/timeline.py: collect_all_events, find_event_by_id,
  collect_timeline_stats, create_timeline_router
- Helper functions: _serialize_message, _serialize_message_detail,
  _extract_stream_category, _extract_kind, _extract_event_type,
  _extract_aggregate_id
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.server.observatory import Observatory
from protean.server.observatory.routes.timeline import (
    _extract_aggregate_id,
    _extract_event_type,
    _extract_kind,
    _extract_message_id,
    _extract_stream_category,
    _serialize_message,
    _serialize_message_detail,
    collect_all_events,
    collect_timeline_stats,
    create_timeline_router,
    find_event_by_id,
)

# All tests in this module use standalone in-memory domains
# so they don't need the observatory conftest's Redis-dependent test_domain.
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

    @classmethod
    def register(cls, user_id: str, name: str) -> User:
        user = cls(user_id=user_id, name=name)
        user.raise_(UserRegistered(user_id=user_id, name=name))
        return user

    def rename(self, name: str) -> None:
        self.name = name
        self.raise_(UserRenamed(user_id=self.user_id, name=name))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def timeline_domain(tmp_path):
    """Create a standalone domain with in-memory adapters for timeline tests."""
    domain = Domain(name="TimelineTests", root_path=str(tmp_path))
    domain._initialize()
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain


@pytest.fixture
def observatory(timeline_domain):
    return Observatory(domains=[timeline_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


@pytest.fixture
def event_domain(tmp_path):
    """Create a domain with event-sourced aggregate and in-memory adapters."""
    domain = Domain(name="TimelineTests", root_path=str(tmp_path))
    domain._initialize()

    domain.register(User)
    domain.register(UserRegistered, part_of=User)
    domain.register(UserRenamed, part_of=User)
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain


@pytest.fixture
def domain_with_events(event_domain):
    """Populate the event domain's event store with test events."""
    user1_id = str(uuid.uuid4())
    user2_id = str(uuid.uuid4())

    user1 = User.register(user1_id, "Alice")
    user2 = User.register(user2_id, "Bob")

    event_domain.event_store.store.append(user1._events[0])
    event_domain.event_store.store.append(user2._events[0])

    # Add a rename event for user1
    user1.rename("Alice Smith")
    event_domain.event_store.store.append(user1._events[-1])

    return event_domain, user1_id, user2_id


@pytest.fixture
def observatory_with_events(domain_with_events):
    domain, _, _ = domain_with_events
    return Observatory(domains=[domain])


@pytest.fixture
def client_with_events(observatory_with_events):
    return TestClient(observatory_with_events.app)


# ---------------------------------------------------------------------------
# _serialize_message
# ---------------------------------------------------------------------------


class TestSerializeMessage:
    def test_basic_serialization(self):
        raw_msg = {
            "type": "Test.UserRegistered.v1",
            "stream_name": "test::user-123",
            "global_position": 5,
            "position": 0,
            "time": "2025-01-01T00:00:00",
            "metadata": {
                "headers": {
                    "id": "msg-001",
                    "type": "Test.UserRegistered.v1",
                    "stream": "test::user-123",
                    "time": "2025-01-01T00:00:00",
                },
                "domain": {
                    "kind": "EVENT",
                    "correlation_id": "corr-001",
                    "causation_id": None,
                },
                "event_store": {
                    "global_position": 5,
                    "position": 0,
                },
            },
        }
        result = _serialize_message(raw_msg, "TestDomain")

        assert result["message_id"] == "msg-001"
        assert result["type"] == "Test.UserRegistered.v1"
        assert result["stream"] == "test::user-123"
        assert result["kind"] == "EVENT"
        assert result["global_position"] == 5
        assert result["position"] == 0
        assert result["correlation_id"] == "corr-001"
        assert result["causation_id"] is None
        assert result["domain"] == "TestDomain"

    def test_handles_missing_metadata(self):
        raw_msg = {"type": "SomeEvent", "global_position": 1}
        result = _serialize_message(raw_msg, "TestDomain")

        assert result["type"] == "SomeEvent"
        assert result["message_id"] is None
        assert result["domain"] == "TestDomain"

    def test_handles_non_dict_metadata(self):
        raw_msg = {"type": "SomeEvent", "metadata": "invalid"}
        result = _serialize_message(raw_msg, "TestDomain")
        assert result["message_id"] is None


class TestSerializeMessageDetail:
    def test_includes_data_and_metadata(self):
        raw_msg = {
            "type": "Test.UserRegistered.v1",
            "stream_name": "test::user-123",
            "global_position": 5,
            "position": 0,
            "time": "2025-01-01T00:00:00",
            "data": {"user_id": "123", "name": "Alice"},
            "metadata": {
                "headers": {"id": "msg-001"},
                "domain": {"kind": "EVENT"},
            },
        }
        result = _serialize_message_detail(raw_msg, "TestDomain")

        assert result["data"] == {"user_id": "123", "name": "Alice"}
        assert result["metadata"] == raw_msg["metadata"]
        assert result["message_id"] == "msg-001"

    def test_defaults_for_missing_data(self):
        raw_msg = {"type": "SomeEvent"}
        result = _serialize_message_detail(raw_msg, "D")
        assert result["data"] == {}
        assert result["metadata"] == {}


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


class TestExtractMessageId:
    def test_extracts_from_headers(self):
        msg = {"metadata": {"headers": {"id": "abc-123"}}}
        assert _extract_message_id(msg) == "abc-123"

    def test_returns_none_for_missing(self):
        assert _extract_message_id({}) is None
        assert _extract_message_id({"metadata": "bad"}) is None
        assert _extract_message_id({"metadata": {"headers": "bad"}}) is None


class TestExtractStreamCategory:
    def test_from_domain_meta(self):
        msg = {"metadata": {"domain": {"stream_category": "test::user"}}}
        assert _extract_stream_category(msg) == "test::user"

    def test_from_stream_name(self):
        msg = {"stream_name": "test::user-abc123", "metadata": {}}
        assert _extract_stream_category(msg) == "test::user"

    def test_returns_empty_for_missing(self):
        assert _extract_stream_category({}) == ""


class TestExtractKind:
    def test_extracts_event(self):
        msg = {"metadata": {"domain": {"kind": "EVENT"}}}
        assert _extract_kind(msg) == "EVENT"

    def test_extracts_command(self):
        msg = {"metadata": {"domain": {"kind": "COMMAND"}}}
        assert _extract_kind(msg) == "COMMAND"

    def test_returns_none_for_missing(self):
        assert _extract_kind({}) is None


class TestExtractEventType:
    def test_extracts_type(self):
        msg = {"type": "Test.UserRegistered.v1"}
        assert _extract_event_type(msg) == "Test.UserRegistered.v1"

    def test_returns_none_for_missing(self):
        assert _extract_event_type({}) is None


class TestExtractAggregateId:
    def test_from_stream_name(self):
        msg = {"stream_name": "test::user-abc123"}
        assert _extract_aggregate_id(msg) == "abc123"

    def test_from_headers_stream(self):
        msg = {"metadata": {"headers": {"stream": "test::user-xyz"}}}
        assert _extract_aggregate_id(msg) == "xyz"

    def test_returns_none_without_dash(self):
        msg = {"stream_name": "all"}
        assert _extract_aggregate_id(msg) is None

    def test_returns_none_for_missing(self):
        assert _extract_aggregate_id({}) is None


# ---------------------------------------------------------------------------
# collect_all_events
# ---------------------------------------------------------------------------


class TestCollectAllEvents:
    def test_returns_events(self, domain_with_events):
        domain, user1_id, user2_id = domain_with_events
        events, cursor = collect_all_events([domain])
        assert len(events) == 3

    def test_respects_limit(self, domain_with_events):
        domain, _, _ = domain_with_events
        events, cursor = collect_all_events([domain], limit=2)
        assert len(events) == 2
        assert cursor is not None

    def test_cursor_pagination(self, domain_with_events):
        domain, _, _ = domain_with_events
        # Get first 2 events
        page1, cursor1 = collect_all_events([domain], limit=2)
        assert len(page1) == 2
        assert cursor1 is not None

        # Get remaining events using cursor
        page2, cursor2 = collect_all_events([domain], cursor=cursor1, limit=2)
        assert len(page2) == 1
        assert cursor2 is None

    def test_desc_order(self, domain_with_events):
        domain, _, _ = domain_with_events
        events, _ = collect_all_events([domain], order="desc")
        positions = [e["global_position"] for e in events]
        assert positions == sorted(positions, reverse=True)

    def test_desc_cursor_pagination(self, domain_with_events):
        domain, _, _ = domain_with_events
        # Get first 2 events in descending order
        page1, cursor1 = collect_all_events([domain], order="desc", limit=2)
        assert len(page1) == 2
        assert cursor1 is not None
        # Desc cursor should be less than the last position
        assert cursor1 == page1[-1]["global_position"] - 1

        # Follow cursor for remaining events
        page2, cursor2 = collect_all_events(
            [domain], order="desc", cursor=cursor1, limit=2
        )
        assert len(page2) == 1
        assert cursor2 is None

    def test_filter_by_event_type(self, domain_with_events):
        domain, _, _ = domain_with_events
        events, _ = collect_all_events(
            [domain], event_type=UserRenamed.__type__
        )
        assert len(events) == 1
        assert events[0]["type"] == UserRenamed.__type__

    def test_filter_by_kind(self, domain_with_events):
        domain, _, _ = domain_with_events
        events, _ = collect_all_events([domain], kind="EVENT")
        assert len(events) == 3  # All are events

    def test_filter_by_aggregate_id(self, domain_with_events):
        domain, user1_id, _ = domain_with_events
        events, _ = collect_all_events([domain], aggregate_id=user1_id)
        assert len(events) == 2  # UserRegistered + UserRenamed

    def test_excludes_snapshots(self, domain_with_events):
        domain, user1_id, _ = domain_with_events
        # Write a snapshot to the event store
        domain.event_store.store._write(
            f"{User.meta_.stream_category}:snapshot-{user1_id}",
            "SNAPSHOT",
            {"user_id": user1_id, "name": "Alice Smith"},
        )

        # Snapshots should not appear in the timeline
        events, _ = collect_all_events([domain])
        assert len(events) == 3  # Only the 3 real events
        for event in events:
            assert event["type"] != "SNAPSHOT"

    def test_handles_broken_domain_gracefully(self):
        domain = MagicMock()
        domain.name = "Broken"
        domain.domain_context.side_effect = Exception("Store unavailable")

        events, cursor = collect_all_events([domain])
        assert events == []
        assert cursor is None

    def test_returns_empty_when_no_events(self, event_domain):
        events, cursor = collect_all_events([event_domain])
        assert events == []
        assert cursor is None


# ---------------------------------------------------------------------------
# find_event_by_id
# ---------------------------------------------------------------------------


class TestFindEventById:
    def test_finds_existing_event(self, domain_with_events):
        domain, _, _ = domain_with_events
        # First get all events to find a message ID
        events, _ = collect_all_events([domain])
        msg_id = events[0]["message_id"]

        result = find_event_by_id([domain], msg_id)
        assert result is not None
        assert result["message_id"] == msg_id
        assert "data" in result
        assert "metadata" in result

    def test_returns_none_for_missing(self, domain_with_events):
        domain, _, _ = domain_with_events
        result = find_event_by_id([domain], "nonexistent-id")
        assert result is None

    def test_handles_broken_domain_gracefully(self):
        domain = MagicMock()
        domain.name = "Broken"
        domain.domain_context.side_effect = Exception("Store unavailable")

        result = find_event_by_id([domain], "any-id")
        assert result is None


# ---------------------------------------------------------------------------
# collect_timeline_stats
# ---------------------------------------------------------------------------


class TestCollectTimelineStats:
    def test_empty_domain(self, event_domain):
        stats = collect_timeline_stats([event_domain])
        assert stats["total_events"] == 0
        assert stats["last_event_time"] is None
        assert stats["active_streams"] == 0
        assert stats["events_per_minute"] is None

    def test_with_events(self, domain_with_events):
        domain, _, _ = domain_with_events
        stats = collect_timeline_stats([domain])
        assert stats["total_events"] == 3
        assert stats["last_event_time"] is not None
        assert stats["active_streams"] >= 1

    def test_handles_broken_domain_gracefully(self):
        domain = MagicMock()
        domain.name = "Broken"
        domain.domain_context.side_effect = Exception("Store unavailable")

        stats = collect_timeline_stats([domain])
        assert stats["total_events"] == 0


# ---------------------------------------------------------------------------
# Endpoint: GET /timeline/events
# ---------------------------------------------------------------------------


class TestTimelineEventsEndpoint:
    def test_returns_200_empty(self, client):
        response = client.get("/api/timeline/events")
        assert response.status_code == 200

    def test_response_shape(self, client):
        response = client.get("/api/timeline/events")
        data = response.json()
        assert "events" in data
        assert "next_cursor" in data
        assert "count" in data
        assert isinstance(data["events"], list)

    def test_returns_events(self, client_with_events):
        response = client_with_events.get("/api/timeline/events")
        data = response.json()
        assert data["count"] == 3
        assert len(data["events"]) == 3

    def test_pagination(self, client_with_events):
        response = client_with_events.get("/api/timeline/events?limit=2")
        data = response.json()
        assert data["count"] == 2
        assert data["next_cursor"] is not None

        # Follow cursor
        response2 = client_with_events.get(
            f"/api/timeline/events?cursor={data['next_cursor']}&limit=2"
        )
        data2 = response2.json()
        assert data2["count"] == 1
        assert data2["next_cursor"] is None

    def test_desc_order(self, client_with_events):
        response = client_with_events.get("/api/timeline/events?order=desc")
        data = response.json()
        positions = [e["global_position"] for e in data["events"]]
        assert positions == sorted(positions, reverse=True)

    def test_filter_by_kind(self, client_with_events):
        response = client_with_events.get("/api/timeline/events?kind=EVENT")
        data = response.json()
        assert data["count"] == 3

    def test_invalid_kind_rejected(self, client_with_events):
        response = client_with_events.get("/api/timeline/events?kind=INVALID")
        assert response.status_code == 422

    def test_invalid_order_rejected(self, client_with_events):
        response = client_with_events.get("/api/timeline/events?order=random")
        assert response.status_code == 422

    def test_limit_enforced(self, client_with_events):
        response = client_with_events.get("/api/timeline/events?limit=300")
        assert response.status_code == 422

    def test_negative_cursor_rejected(self, client_with_events):
        response = client_with_events.get("/api/timeline/events?cursor=-1")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Endpoint: GET /timeline/events/{message_id}
# ---------------------------------------------------------------------------


class TestTimelineEventDetailEndpoint:
    def test_returns_event_detail(self, client_with_events):
        # Get a message ID first
        response = client_with_events.get("/api/timeline/events?limit=1")
        msg_id = response.json()["events"][0]["message_id"]

        response = client_with_events.get(f"/api/timeline/events/{msg_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["message_id"] == msg_id
        assert "data" in data
        assert "metadata" in data

    def test_returns_404_for_missing(self, client_with_events):
        response = client_with_events.get("/api/timeline/events/nonexistent")
        assert response.status_code == 404
        assert response.json()["detail"] == "Event not found"


# ---------------------------------------------------------------------------
# Endpoint: GET /timeline/stats
# ---------------------------------------------------------------------------


class TestTimelineStatsEndpoint:
    def test_returns_200(self, client):
        response = client.get("/api/timeline/stats")
        assert response.status_code == 200

    def test_response_shape(self, client):
        response = client.get("/api/timeline/stats")
        data = response.json()
        assert "total_events" in data
        assert "last_event_time" in data
        assert "active_streams" in data
        assert "events_per_minute" in data

    def test_with_events(self, client_with_events):
        response = client_with_events.get("/api/timeline/stats")
        data = response.json()
        assert data["total_events"] == 3
        assert data["active_streams"] >= 1


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


class TestTimelineRouteWiring:
    def test_timeline_routes_included(self, observatory):
        routes = [r.path for r in observatory.app.routes]
        assert "/api/timeline/events" in routes
        assert "/api/timeline/events/{message_id}" in routes
        assert "/api/timeline/stats" in routes


# ---------------------------------------------------------------------------
# create_timeline_router isolation
# ---------------------------------------------------------------------------


class TestCreateTimelineRouterStandalone:
    def test_router_functions_with_mock_domain(self):
        """The router factory works without a real domain when no events exist."""
        domain = MagicMock()
        domain.name = "MockDomain"
        domain.domain_context.side_effect = Exception("No store")

        router = create_timeline_router([domain])
        app = FastAPI()
        app.include_router(router, prefix="/api")
        test_client = TestClient(app)

        response = test_client.get("/api/timeline/events")
        assert response.status_code == 200
        assert response.json()["events"] == []

        response = test_client.get("/api/timeline/stats")
        assert response.status_code == 200
        assert response.json()["total_events"] == 0

        response = test_client.get("/api/timeline/events/some-id")
        assert response.status_code == 404
