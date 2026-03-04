"""Tests for Observatory Event Store API endpoints and supporting functions.

Covers:
- routes/eventstore.py: collect_aggregate_stream_metadata,
  enrich_with_event_store_stats, collect_outbox_status, get_stream_instances,
  _build_eventstore_summary, create_eventstore_router
- templates/eventstore.html: structure and JS inclusion
- static/js/eventstore.js: file presence
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory
from protean.server.observatory.routes.eventstore import (
    _build_eventstore_summary,
    _extract_message_type,
    _extract_time,
    _serialize_aggregate,
    collect_aggregate_stream_metadata,
    collect_outbox_status,
    create_eventstore_router,
    enrich_with_event_store_stats,
    get_stream_instances,
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


def _make_mock_agg_cls(
    *,
    name="TestAggregate",
    stream_category=None,
    is_event_sourced=False,
):
    """Create a mock aggregate class with the given metadata."""
    cls = MagicMock()
    cls.__name__ = name

    meta = MagicMock()
    meta.stream_category = stream_category
    meta.is_event_sourced = is_event_sourced
    cls.meta_ = meta
    return cls


def _make_mock_domain_record(name, qualname, cls):
    """Create a mock DomainRecord."""
    record = MagicMock()
    record.name = name
    record.qualname = qualname
    record.cls = cls
    return record


def _make_mock_domain(*, name="TestDomain", aggregates=None):
    """Create a mock domain with the given aggregate registry."""
    domain = MagicMock()
    domain.name = name

    registry = MagicMock()
    registry.aggregates = aggregates or {}
    domain.registry = registry
    return domain


def _make_mock_message(*, time_val=None, msg_type=None):
    """Create a mock message with optional time and type."""
    msg = MagicMock()
    if time_val is not None:
        msg.time = time_val
    else:
        msg.time = None
        msg.metadata = MagicMock()
        msg.metadata.timestamp = None
    if msg_type is not None:
        msg.type = msg_type
    else:
        msg.type = None
    return msg


# ---------------------------------------------------------------------------
# _extract_time
# ---------------------------------------------------------------------------


class TestExtractTime:
    def test_extracts_time_attribute(self):
        msg = _make_mock_message(time_val="2024-01-01T00:00:00Z")
        assert _extract_time(msg) == "2024-01-01T00:00:00Z"

    def test_falls_back_to_metadata_timestamp(self):
        msg = MagicMock()
        msg.time = None
        msg.metadata = MagicMock()
        msg.metadata.timestamp = "2024-06-15T12:00:00Z"
        assert _extract_time(msg) == "2024-06-15T12:00:00Z"

    def test_returns_none_when_no_time(self):
        msg = MagicMock()
        msg.time = None
        msg.metadata = None
        assert _extract_time(msg) is None


# ---------------------------------------------------------------------------
# _extract_message_type
# ---------------------------------------------------------------------------


class TestExtractMessageType:
    def test_extracts_type_attribute(self):
        msg = _make_mock_message(msg_type="MyApp.OrderPlaced.v1")
        assert _extract_message_type(msg) == "MyApp.OrderPlaced.v1"

    def test_falls_back_to_class_name(self):

        class OrderPlaced:
            type = None

        msg = OrderPlaced()
        assert _extract_message_type(msg) == "OrderPlaced"

    def test_returns_none_for_dict(self):
        assert _extract_message_type({}) is None


# ---------------------------------------------------------------------------
# collect_aggregate_stream_metadata
# ---------------------------------------------------------------------------


class TestCollectAggregateStreamMetadata:
    def test_empty_domain(self):
        domain = _make_mock_domain()
        assert collect_aggregate_stream_metadata([domain]) == []

    def test_single_aggregate(self):
        agg_cls = _make_mock_agg_cls(
            name="Order",
            stream_category="test::order",
            is_event_sourced=False,
        )
        record = _make_mock_domain_record("Order", "myapp.Order", agg_cls)
        domain = _make_mock_domain(aggregates={"myapp.Order": record})

        result = collect_aggregate_stream_metadata([domain])
        assert len(result) == 1
        agg = result[0]
        assert agg["name"] == "Order"
        assert agg["qualname"] == "myapp.Order"
        assert agg["domain"] == "TestDomain"
        assert agg["stream_category"] == "test::order"
        assert agg["is_event_sourced"] is False
        assert agg["instance_count"] is None
        assert agg["head_position"] is None
        assert agg["_domain"] is domain

    def test_event_sourced_aggregate(self):
        agg_cls = _make_mock_agg_cls(
            name="Account",
            stream_category="test::account",
            is_event_sourced=True,
        )
        record = _make_mock_domain_record("Account", "myapp.Account", agg_cls)
        domain = _make_mock_domain(aggregates={"myapp.Account": record})

        result = collect_aggregate_stream_metadata([domain])
        assert result[0]["is_event_sourced"] is True

    def test_multiple_aggregates_across_domains(self):
        agg1 = _make_mock_agg_cls(name="Order", stream_category="test::order")
        agg2 = _make_mock_agg_cls(name="User", stream_category="test::user")
        d1 = _make_mock_domain(
            name="D1",
            aggregates={"a.Order": _make_mock_domain_record("Order", "a.Order", agg1)},
        )
        d2 = _make_mock_domain(
            name="D2",
            aggregates={"b.User": _make_mock_domain_record("User", "b.User", agg2)},
        )

        result = collect_aggregate_stream_metadata([d1, d2])
        assert len(result) == 2
        names = {a["name"] for a in result}
        assert names == {"Order", "User"}

    def test_aggregate_without_meta(self):
        cls = MagicMock()
        cls.__name__ = "NoMeta"
        cls.meta_ = None
        record = _make_mock_domain_record("NoMeta", "a.NoMeta", cls)
        domain = _make_mock_domain(aggregates={"a.NoMeta": record})

        result = collect_aggregate_stream_metadata([domain])
        assert len(result) == 1
        assert result[0]["stream_category"] is None
        assert result[0]["is_event_sourced"] is False


# ---------------------------------------------------------------------------
# enrich_with_event_store_stats
# ---------------------------------------------------------------------------


class TestEnrichWithEventStoreStats:
    def test_sets_instance_count(self):
        domain = MagicMock()
        store = MagicMock()
        store._stream_identifiers.return_value = ["id1", "id2", "id3"]
        store._stream_head_position.return_value = 42
        domain.event_store.store = store

        aggregates = [
            {
                "name": "Order",
                "stream_category": "test::order",
                "_domain": domain,
            }
        ]
        enrich_with_event_store_stats(aggregates)
        assert aggregates[0]["instance_count"] == 3

    def test_sets_head_position(self):
        domain = MagicMock()
        store = MagicMock()
        store._stream_identifiers.return_value = ["id1"]
        store._stream_head_position.return_value = 100
        domain.event_store.store = store

        aggregates = [
            {
                "name": "Order",
                "stream_category": "test::order",
                "_domain": domain,
            }
        ]
        enrich_with_event_store_stats(aggregates)
        assert aggregates[0]["head_position"] == 100

    def test_head_position_negative_one_becomes_none(self):
        domain = MagicMock()
        store = MagicMock()
        store._stream_identifiers.return_value = []
        store._stream_head_position.return_value = -1
        domain.event_store.store = store

        aggregates = [
            {
                "name": "Empty",
                "stream_category": "test::empty",
                "_domain": domain,
            }
        ]
        enrich_with_event_store_stats(aggregates)
        assert aggregates[0]["head_position"] is None

    def test_skips_aggregate_without_stream_category(self):
        aggregates = [
            {
                "name": "NoStream",
                "stream_category": None,
                "_domain": MagicMock(),
                "instance_count": None,
                "head_position": None,
            }
        ]
        enrich_with_event_store_stats(aggregates)
        assert aggregates[0]["instance_count"] is None

    def test_handles_exception_gracefully(self):
        domain = MagicMock()
        domain.domain_context.side_effect = Exception("DB error")

        aggregates = [
            {
                "name": "Broken",
                "stream_category": "test::broken",
                "_domain": domain,
                "instance_count": None,
                "head_position": None,
            }
        ]
        enrich_with_event_store_stats(aggregates)
        assert aggregates[0]["instance_count"] is None


# ---------------------------------------------------------------------------
# collect_outbox_status
# ---------------------------------------------------------------------------


class TestCollectOutboxStatus:
    def test_returns_counts(self):
        domain = MagicMock()
        domain.name = "TestDomain"
        outbox_repo = MagicMock()
        outbox_repo.count_by_status.return_value = {"pending": 5, "processing": 2}
        domain._get_outbox_repo.return_value = outbox_repo

        result = collect_outbox_status([domain])
        assert result["TestDomain"]["status"] == "ok"
        assert result["TestDomain"]["counts"]["pending"] == 5

    def test_handles_exception(self):
        domain = MagicMock()
        domain.name = "Broken"
        domain.domain_context.side_effect = Exception("Outbox error")

        result = collect_outbox_status([domain])
        assert result["Broken"]["status"] == "error"


# ---------------------------------------------------------------------------
# get_stream_instances
# ---------------------------------------------------------------------------


class TestGetStreamInstances:
    def test_no_instances(self):
        domain = MagicMock()
        store = MagicMock()
        store._stream_identifiers.return_value = []
        domain.event_store.store = store

        result = get_stream_instances(domain, "test::order")
        assert result == []

    def test_single_instance(self):
        domain = MagicMock()
        store = MagicMock()
        store._stream_identifiers.return_value = ["abc-123"]
        msg1 = _make_mock_message(
            time_val="2024-01-01T00:00:00Z", msg_type="OrderPlaced"
        )
        msg2 = _make_mock_message(
            time_val="2024-01-01T01:00:00Z", msg_type="OrderShipped"
        )
        store.read.return_value = [msg1, msg2]
        domain.event_store.store = store

        result = get_stream_instances(domain, "test::order")
        assert len(result) == 1
        inst = result[0]
        assert inst["instance_id"] == "abc-123"
        assert inst["event_count"] == 2
        assert inst["first_event_time"] == "2024-01-01T00:00:00Z"
        assert inst["last_event_time"] == "2024-01-01T01:00:00Z"
        assert inst["last_event_type"] == "OrderShipped"

    def test_multiple_instances(self):
        domain = MagicMock()
        store = MagicMock()
        store._stream_identifiers.return_value = ["id1", "id2"]
        msg = _make_mock_message(time_val="2024-01-01T00:00:00Z", msg_type="Evt")
        store.read.return_value = [msg]
        domain.event_store.store = store

        result = get_stream_instances(domain, "test::order")
        assert len(result) == 2

    def test_respects_limit(self):
        domain = MagicMock()
        store = MagicMock()
        store._stream_identifiers.return_value = ["id1", "id2", "id3", "id4", "id5"]
        msg = _make_mock_message(time_val="2024-01-01", msg_type="Evt")
        store.read.return_value = [msg]
        domain.event_store.store = store

        result = get_stream_instances(domain, "test::order", limit=2)
        assert len(result) == 2

    def test_skips_empty_streams(self):
        domain = MagicMock()
        store = MagicMock()
        store._stream_identifiers.return_value = ["id1"]
        store.read.return_value = []
        domain.event_store.store = store

        result = get_stream_instances(domain, "test::order")
        assert result == []

    def test_handles_read_exception(self):
        domain = MagicMock()
        store = MagicMock()
        store._stream_identifiers.return_value = ["id1"]
        store.read.side_effect = Exception("Read failed")
        domain.event_store.store = store

        result = get_stream_instances(domain, "test::order")
        assert result == []

    def test_handles_identifiers_exception(self):
        domain = MagicMock()
        domain.domain_context.side_effect = Exception("Store unavailable")

        result = get_stream_instances(domain, "test::order")
        assert result == []


# ---------------------------------------------------------------------------
# _build_eventstore_summary
# ---------------------------------------------------------------------------


class TestBuildEventstoreSummary:
    def test_empty_list(self):
        summary = _build_eventstore_summary([])
        assert summary["total_aggregates"] == 0
        assert summary["total_event_sourced"] == 0
        assert summary["total_instances"] == 0

    def test_with_data(self):
        aggregates = [
            {"name": "A", "is_event_sourced": True, "instance_count": 10},
            {"name": "B", "is_event_sourced": False, "instance_count": 20},
            {"name": "C", "is_event_sourced": True, "instance_count": None},
        ]
        summary = _build_eventstore_summary(aggregates)
        assert summary["total_aggregates"] == 3
        assert summary["total_event_sourced"] == 2
        assert summary["total_instances"] == 30

    def test_all_none_instance_counts(self):
        aggregates = [
            {"name": "A", "is_event_sourced": False, "instance_count": None},
        ]
        summary = _build_eventstore_summary(aggregates)
        assert summary["total_instances"] == 0


# ---------------------------------------------------------------------------
# _serialize_aggregate
# ---------------------------------------------------------------------------


class TestSerializeAggregate:
    def test_strips_internal_keys(self):
        agg = {
            "name": "Order",
            "stream_category": "test::order",
            "_domain": MagicMock(),
        }
        result = _serialize_aggregate(agg)
        assert "name" in result
        assert "stream_category" in result
        assert "_domain" not in result

    def test_preserves_all_public_keys(self):
        agg = {
            "name": "Order",
            "qualname": "myapp.Order",
            "domain": "TestDomain",
            "stream_category": "test::order",
            "is_event_sourced": True,
            "instance_count": 5,
            "head_position": 100,
            "_domain": MagicMock(),
        }
        result = _serialize_aggregate(agg)
        assert len(result) == 7  # All except _domain


# ---------------------------------------------------------------------------
# Endpoint: GET /eventstore/streams
# ---------------------------------------------------------------------------


class TestEventStoreStreamsEndpoint:
    def test_returns_200(self, client):
        response = client.get("/api/eventstore/streams")
        assert response.status_code == 200

    def test_response_has_correct_shape(self, client):
        response = client.get("/api/eventstore/streams")
        data = response.json()
        assert "aggregates" in data
        assert "summary" in data
        assert "outbox" in data
        assert isinstance(data["aggregates"], list)
        assert isinstance(data["summary"], dict)
        assert isinstance(data["outbox"], dict)

    def test_summary_has_required_fields(self, client):
        response = client.get("/api/eventstore/streams")
        summary = response.json()["summary"]
        assert "total_aggregates" in summary
        assert "total_event_sourced" in summary
        assert "total_instances" in summary


# ---------------------------------------------------------------------------
# Endpoint: GET /eventstore/streams/{stream_category}
# ---------------------------------------------------------------------------


class TestEventStoreStreamDetailEndpoint:
    def test_returns_404_for_unknown_stream(self, client):
        response = client.get("/api/eventstore/streams/nonexistent::stream")
        assert response.status_code == 404
        assert "not found" in response.json()["error"].lower()

    def test_returns_200_for_existing_stream(self, client, test_domain):
        """If the test domain has registered aggregates, we should be able
        to query one of them. Otherwise this verifies the endpoint shape."""
        # Get streams list first
        streams_resp = client.get("/api/eventstore/streams")
        aggregates = streams_resp.json()["aggregates"]

        if aggregates:
            stream_cat = aggregates[0]["stream_category"]
            if stream_cat:
                response = client.get(f"/api/eventstore/streams/{stream_cat}")
                assert response.status_code == 200
                data = response.json()
                assert "stream_category" in data
                assert "instances" in data
                assert "total" in data

    def test_detail_response_shape(self):
        """Test the shape using mocked domain."""
        from fastapi import FastAPI

        agg_cls = _make_mock_agg_cls(name="Order", stream_category="test::order")
        record = _make_mock_domain_record("Order", "myapp.Order", agg_cls)
        domain = _make_mock_domain(aggregates={"myapp.Order": record})

        # Mock event store
        store = MagicMock()
        store._stream_identifiers.return_value = []
        store._stream_head_position.return_value = -1
        domain.event_store.store = store

        router = create_eventstore_router([domain])
        app = FastAPI()
        app.include_router(router, prefix="/api")
        test_client = TestClient(app)

        response = test_client.get("/api/eventstore/streams/test::order")
        assert response.status_code == 200
        data = response.json()
        assert data["stream_category"] == "test::order"
        assert data["aggregate"] == "Order"
        assert isinstance(data["instances"], list)


# ---------------------------------------------------------------------------
# Template: eventstore.html
# ---------------------------------------------------------------------------


class TestEventStoreTemplate:
    def test_page_renders_200(self, client):
        response = client.get("/eventstore")
        assert response.status_code == 200

    def test_extends_base_template(self, client):
        response = client.get("/eventstore")
        html = response.text
        # Base template includes the nav sidebar
        assert "Observatory" in html

    def test_includes_eventstore_js(self, client):
        response = client.get("/eventstore")
        assert "eventstore.js" in response.text

    def test_has_summary_cards(self, client):
        response = client.get("/eventstore")
        html = response.text
        assert "summary-total-aggregates" in html
        assert "summary-event-sourced" in html
        assert "summary-total-instances" in html
        assert "summary-outbox-pending" in html

    def test_has_streams_table(self, client):
        response = client.get("/eventstore")
        assert "streams-tbody" in html if (html := response.text) else False

    def test_has_detail_panel(self, client):
        response = client.get("/eventstore")
        assert "stream-detail" in response.text

    def test_has_outbox_section(self, client):
        response = client.get("/eventstore")
        assert "outbox-content" in response.text

    def test_has_search_input(self, client):
        response = client.get("/eventstore")
        assert "stream-search" in response.text


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------


class TestEventStoreStaticFiles:
    def test_eventstore_js_served(self, client):
        response = client.get("/static/js/eventstore.js")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------


class TestEventStoreRouteWiring:
    def test_eventstore_routes_included(self, observatory):
        """Verify the eventstore routes are in the Observatory app."""
        routes = [r.path for r in observatory.app.routes]
        assert "/api/eventstore/streams" in routes

    def test_eventstore_detail_route_included(self, observatory):
        """Verify the stream detail route is included."""
        routes = [r.path for r in observatory.app.routes]
        assert "/api/eventstore/streams/{stream_category:path}" in routes

    def test_page_route_included(self, observatory):
        """Verify the page route exists."""
        routes = [r.path for r in observatory.app.routes]
        assert "/eventstore" in routes
