"""Tests for Observatory Event Store API endpoints and supporting functions.

Tests for:
- routes/eventstore.py: collect_aggregate_stream_metadata,
  enrich_with_event_store_stats, collect_outbox_status,
  _build_eventstore_summary, create_eventstore_router
- templates/eventstore.html: structure and JS inclusion
- static/js/eventstore.js: file presence
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Identifier, String
from protean.server.observatory import Observatory
from protean.server.observatory.routes.eventstore import (
    _build_eventstore_summary,
    _serialize_aggregate,
    collect_aggregate_stream_metadata,
    collect_outbox_status,
    create_eventstore_router,
    enrich_with_event_store_stats,
)
from protean.utils import fqn
from tests.server.observatory.conftest import route_paths

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def observatory(test_domain):
    return Observatory(domains=[test_domain])


@pytest.fixture
def client(observatory):
    return TestClient(observatory.app)


def _new_domain(name="TestDomain"):
    """A fresh domain with an outbox, so outbox counts can be read."""
    return Domain(
        name=name,
        config={
            "enable_outbox": True,
            "server": {"default_subscription_type": "stream"},
        },
    )


def _register_order(domain, **options):
    """Register a fresh Order aggregate that raises OrderPlaced."""

    class Order(BaseAggregate):
        name = String()

        def place(self):
            self.raise_(OrderPlaced(order_id=self.id))

    class OrderPlaced(BaseEvent):
        order_id = Identifier(required=True)

    domain.register(Order, **options)
    domain.register(OrderPlaced, part_of=Order)
    return Order


def _register_plain(domain, cls_name, **options):
    """Register a fresh aggregate class named ``cls_name``."""
    agg_cls = type(cls_name, (BaseAggregate,), {"name": String()})
    domain.register(agg_cls, **options)
    return agg_cls


def _place_orders(domain, order_cls, count):
    """Persist ``count`` orders, each raising one OrderPlaced event."""
    with domain.domain_context():
        for i in range(count):
            order = order_cls(name=f"order-{i}")
            order.place()
            domain.repository_for(order_cls).add(order)


@pytest.fixture
def order_domain():
    domain = _new_domain()
    order_cls = _register_order(domain, stream_category="test::order")
    domain.init(traverse=False)
    return domain, order_cls


# ---------------------------------------------------------------------------
# collect_aggregate_stream_metadata
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCollectAggregateStreamMetadata:
    def test_empty_domain(self):
        domain = _new_domain()
        domain.init(traverse=False)
        assert collect_aggregate_stream_metadata([domain]) == []

    def test_single_aggregate(self, order_domain):
        domain, order_cls = order_domain
        result = collect_aggregate_stream_metadata([domain])
        assert len(result) == 1
        agg = result[0]
        assert agg["name"] == "Order"
        assert agg["qualname"] == fqn(order_cls)
        assert agg["domain"] == "TestDomain"
        assert agg["stream_category"] == "testdomain::test::order"
        assert agg["is_event_sourced"] is False
        assert agg["instance_count"] is None
        assert agg["head_position"] is None
        assert agg["_domain"] is domain

    def test_event_sourced_aggregate(self):
        domain = _new_domain()
        _register_plain(domain, "Account", event_sourced=True)
        domain.init(traverse=False)

        result = collect_aggregate_stream_metadata([domain])
        assert result[0]["is_event_sourced"] is True

    def test_multiple_aggregates_across_domains(self):
        d1 = _new_domain(name="D1")
        _register_order(d1)
        d1.init(traverse=False)
        d2 = _new_domain(name="D2")
        _register_plain(d2, "User")
        d2.init(traverse=False)

        result = collect_aggregate_stream_metadata([d1, d2])
        assert len(result) == 2
        names = {a["name"] for a in result}
        assert names == {"Order", "User"}

    def test_aggregate_without_meta(self, order_domain, monkeypatch):
        # Every registered aggregate class has meta_, so it is removed here.
        domain, order_cls = order_domain
        monkeypatch.setattr(order_cls, "meta_", None)

        result = collect_aggregate_stream_metadata([domain])
        assert len(result) == 1
        assert result[0]["stream_category"] is None
        assert result[0]["is_event_sourced"] is False


# ---------------------------------------------------------------------------
# enrich_with_event_store_stats
# ---------------------------------------------------------------------------


class TestEnrichWithEventStoreStats:
    @pytest.mark.no_test_domain
    def test_sets_instance_count_and_head_position(self, order_domain):
        domain, order_cls = order_domain
        # An event in another category first, so the head position (a global
        # position) differs from the number of order instances.
        with domain.domain_context():
            domain.event_store.store._write(
                "testdomain::customer-1", "CustomerRegistered", {}
            )
        _place_orders(domain, order_cls, 3)
        aggregates = collect_aggregate_stream_metadata([domain])

        enrich_with_event_store_stats(aggregates)
        assert aggregates[0]["instance_count"] == 3
        # The store numbers messages from 1, so the last order event is at 4.
        assert aggregates[0]["head_position"] == 4

    @pytest.mark.no_test_domain
    def test_head_position_negative_one_becomes_none(self, order_domain):
        domain, _ = order_domain
        aggregates = collect_aggregate_stream_metadata([domain])

        enrich_with_event_store_stats(aggregates)
        assert aggregates[0]["instance_count"] == 0
        assert aggregates[0]["head_position"] is None

    def test_skips_aggregate_without_stream_category(self, test_domain):
        aggregates = [
            {
                "name": "NoStream",
                "stream_category": None,
                "_domain": test_domain,
                "instance_count": None,
                "head_position": None,
            }
        ]
        enrich_with_event_store_stats(aggregates)
        assert aggregates[0]["instance_count"] is None

    @pytest.mark.no_test_domain
    def test_handles_exception_gracefully(self):
        # A domain that has not run init() has no event store to query.
        aggregates = [
            {
                "name": "Broken",
                "stream_category": "test::broken",
                "_domain": Domain(name="Uninitialized"),
                "instance_count": None,
                "head_position": None,
            }
        ]
        enrich_with_event_store_stats(aggregates)
        assert aggregates[0]["instance_count"] is None
        assert aggregates[0]["head_position"] is None


# ---------------------------------------------------------------------------
# collect_outbox_status
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCollectOutboxStatus:
    def test_returns_counts(self, order_domain):
        domain, order_cls = order_domain
        _place_orders(domain, order_cls, 5)

        result = collect_outbox_status([domain])
        assert result["TestDomain"]["status"] == "ok"
        assert result["TestDomain"]["counts"]["pending"] == 5
        assert result["TestDomain"]["counts"]["processing"] == 0

    def test_handles_exception(self):
        # A domain that has not run init() has no outbox repository.
        result = collect_outbox_status([Domain(name="Broken")])
        assert result["Broken"]["status"] == "error"


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
    def test_strips_internal_keys_and_preserves_public_keys(self, test_domain):
        agg = {
            "name": "Order",
            "qualname": "myapp.Order",
            "domain": "TestDomain",
            "stream_category": "test::order",
            "is_event_sourced": True,
            "instance_count": 5,
            "head_position": 100,
            "_domain": test_domain,
        }
        result = _serialize_aggregate(agg)
        assert "_domain" not in result
        assert len(result) == 7
        assert result == {k: v for k, v in agg.items() if k != "_domain"}


# ---------------------------------------------------------------------------
# Endpoint: GET /eventstore/streams
# ---------------------------------------------------------------------------


class TestEventStoreStreamsEndpoint:
    def test_response_has_correct_shape(self, client):
        response = client.get("/api/eventstore/streams")
        assert response.status_code == 200
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
# Template: eventstore.html
# ---------------------------------------------------------------------------


class TestEventStoreTemplate:
    def test_extends_base_template(self, client):
        response = client.get("/eventstore")
        assert response.status_code == 200
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
        assert "streams-tbody" in response.text

    def test_has_outbox_table(self, client):
        response = client.get("/eventstore")
        assert "outbox-tbody" in response.text

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
        routes = route_paths(observatory.app.routes)
        assert "/api/eventstore/streams" in routes

    def test_page_route_included(self, observatory):
        """Verify the page route exists."""
        routes = route_paths(observatory.app.routes)
        assert "/eventstore" in routes


# ---------------------------------------------------------------------------
# Endpoint: a failure while adding event store stats
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestEventStoreStreamsEndpointEnrichException:
    def test_enrich_exception_does_not_break_endpoint(self, order_domain):
        """When adding event store stats raises, the endpoint still lists
        the aggregates, without counts."""
        domain, _ = order_domain
        router = create_eventstore_router([domain])
        app = FastAPI()
        app.include_router(router, prefix="/api")
        test_client = TestClient(app)

        with patch(
            "protean.server.observatory.routes.eventstore.enrich_with_event_store_stats",
            side_effect=Exception("unexpected enrich error"),
        ):
            response = test_client.get("/api/eventstore/streams")
        assert response.status_code == 200
        data = response.json()
        assert [a["name"] for a in data["aggregates"]] == ["Order"]
        assert data["aggregates"][0]["instance_count"] is None
        assert data["summary"]["total_aggregates"] == 1
        assert data["outbox"]["TestDomain"]["status"] == "ok"
