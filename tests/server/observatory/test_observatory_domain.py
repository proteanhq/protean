"""Tests for the Observatory Domain page and /api/domain/ir endpoint.

Covers:
- routes/pages.py: /domain page route
- routes/domain.py: /api/domain/ir API endpoint, IR→D3 graph transformation
- templates/domain.html: Template rendering
- base.html: Sidebar navigation entry for Domain
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory
from protean.server.observatory.routes.domain import (
    _build_event_to_agg_index,
    _build_graph,
    _build_links,
    _build_nodes,
    _build_stats,
    create_domain_router,
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


# ---------------------------------------------------------------------------
# Page Route Tests
# ---------------------------------------------------------------------------


class TestDomainPage:
    def test_returns_200(self, client):
        response = client.get("/domain")
        assert response.status_code == 200

    def test_returns_html(self, client):
        response = client.get("/domain")
        assert "text/html" in response.headers["content-type"]

    def test_extends_base_template(self, client):
        html = client.get("/domain").text
        assert "Observatory" in html
        assert "drawer" in html

    def test_contains_page_heading(self, client):
        html = client.get("/domain").text
        assert "Domain" in html

    def test_contains_stat_cards(self, client):
        html = client.get("/domain").text
        assert 'id="dv-stat-aggregates"' in html
        assert 'id="dv-stat-commands"' in html
        assert 'id="dv-stat-events"' in html
        assert 'id="dv-stat-process-managers"' in html
        assert 'id="dv-stat-projections"' in html

    def test_contains_view_tabs(self, client):
        html = client.get("/domain").text
        assert 'id="dv-tabs"' in html
        assert 'data-tab="topology"' in html
        assert 'data-tab="event-flows"' in html
        assert 'data-tab="process-managers"' in html

    def test_contains_panel_containers(self, client):
        html = client.get("/domain").text
        assert 'id="dv-panel-topology"' in html
        assert 'id="dv-panel-event-flows"' in html
        assert 'id="dv-panel-process-managers"' in html

    def test_contains_detail_panel(self, client):
        html = client.get("/domain").text
        assert 'id="dv-detail-panel"' in html
        assert 'id="dv-detail-title"' in html
        assert 'id="dv-detail-content"' in html

    def test_includes_domain_js(self, client):
        html = client.get("/domain").text
        assert "/static/js/domain.js" in html

    def test_domain_nav_is_active(self, client):
        html = client.get("/domain").text
        assert 'href="/domain"' in html


# ---------------------------------------------------------------------------
# Sidebar Navigation
# ---------------------------------------------------------------------------


class TestDomainSidebarNav:
    def test_domain_link_in_sidebar(self, client):
        """All pages should include the Domain nav link."""
        html = client.get("/").text
        assert 'href="/domain"' in html

    def test_domain_section_header(self, client):
        html = client.get("/").text
        # The sidebar has a "Domain" section header
        assert "Domain" in html

    def test_keyboard_shortcut_in_modal(self, client):
        html = client.get("/").text
        assert "Go to Domain" in html


class TestDomainKeyboardShortcut:
    def test_core_js_has_domain_shortcut(self, client):
        js = client.get("/static/js/core.js").text
        assert "'d': '/domain'" in js


# ---------------------------------------------------------------------------
# API Endpoint Tests
# ---------------------------------------------------------------------------


class TestDomainIREndpoint:
    def test_returns_200(self, client):
        response = client.get("/api/domain/ir")
        assert response.status_code == 200

    def test_returns_json(self, client):
        response = client.get("/api/domain/ir")
        assert "application/json" in response.headers["content-type"]

    def test_has_required_keys(self, client):
        data = client.get("/api/domain/ir").json()
        assert "nodes" in data
        assert "links" in data
        assert "clusters" in data
        assert "flows" in data
        assert "projections" in data
        assert "stats" in data

    def test_nodes_is_list(self, client):
        data = client.get("/api/domain/ir").json()
        assert isinstance(data["nodes"], list)

    def test_links_is_list(self, client):
        data = client.get("/api/domain/ir").json()
        assert isinstance(data["links"], list)

    def test_stats_has_aggregates_count(self, client):
        data = client.get("/api/domain/ir").json()
        assert "aggregates" in data["stats"]
        assert isinstance(data["stats"]["aggregates"], int)

    def test_stats_has_element_counts(self, client):
        data = client.get("/api/domain/ir").json()
        stats = data["stats"]
        for key in ("commands", "events", "aggregates", "projections"):
            assert key in stats


# ---------------------------------------------------------------------------
# Multi-Aggregate Domain Tests
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestMultiAggregateDomain:
    def test_returns_multiple_nodes(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        assert len(data["nodes"]) == 2

    def test_node_has_expected_fields(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        node = data["nodes"][0]
        assert "id" in node
        assert "name" in node
        assert "type" in node
        assert "fqn" in node
        assert "counts" in node

    def test_node_type_is_aggregate(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for node in data["nodes"]:
            assert node["type"] == "aggregate"

    def test_detects_cross_aggregate_links(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        links = data["links"]
        event_links = [lnk for lnk in links if lnk["type"] == "event"]
        assert len(event_links) >= 1

    def test_link_has_expected_fields(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        links = data["links"]
        if links:
            link = links[0]
            assert "source" in link
            assert "target" in link
            assert "type" in link
            assert "label" in link

    def test_stats_reflect_multi_aggregate(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        assert data["stats"]["aggregates"] == 2

    def test_clusters_keyed_by_fqn(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        assert len(data["clusters"]) == 2
        for key in data["clusters"]:
            assert "." in key  # FQN contains dots


# ---------------------------------------------------------------------------
# Unit Tests: Graph Transformation Functions
# ---------------------------------------------------------------------------


class TestBuildNodes:
    def test_empty_clusters(self):
        assert _build_nodes({}) == []

    def test_single_aggregate(self):
        clusters = {
            "app.Order": {
                "aggregate": {
                    "name": "Order",
                    "options": {"stream_category": "order"},
                },
                "commands": {"app.PlaceOrder": {}},
                "events": {"app.OrderPlaced": {}},
                "entities": {},
                "value_objects": {},
                "command_handlers": {},
                "event_handlers": {},
                "repositories": {},
                "application_services": {},
                "database_models": {},
            }
        }
        nodes = _build_nodes(clusters)
        assert len(nodes) == 1
        node = nodes[0]
        assert node["id"] == "app.Order"
        assert node["name"] == "Order"
        assert node["type"] == "aggregate"
        assert node["counts"]["commands"] == 1
        assert node["counts"]["events"] == 1


class TestBuildLinks:
    def test_empty_inputs(self):
        assert _build_links({}, {}, {}) == []

    def test_cross_aggregate_event_handler(self):
        clusters = {
            "app.Order": {
                "events": {
                    "app.OrderPlaced": {"__type__": "Order.OrderPlaced.v1"},
                },
                "event_handlers": {},
                "commands": {},
                "command_handlers": {},
                "entities": {},
                "value_objects": {},
                "repositories": {},
                "application_services": {},
                "database_models": {},
                "aggregate": {},
            },
            "app.Inventory": {
                "events": {},
                "event_handlers": {
                    "app.InventoryHandler": {
                        "handlers": {"Order.OrderPlaced.v1": ["on_order_placed"]},
                    },
                },
                "commands": {},
                "command_handlers": {},
                "entities": {},
                "value_objects": {},
                "repositories": {},
                "application_services": {},
                "database_models": {},
                "aggregate": {},
            },
        }
        eta = _build_event_to_agg_index(clusters)
        links = _build_links(clusters, {"process_managers": {}, "subscribers": {}}, eta)
        assert len(links) == 1
        link = links[0]
        assert link["source"] == "app.Order"
        assert link["target"] == "app.Inventory"
        assert link["type"] == "event"

    def test_skips_events_with_empty_type(self):
        """Events without __type__ should not be indexed."""
        clusters = {
            "app.Order": {
                "events": {
                    "app.SomeEvent": {"__type__": ""},
                    "app.OtherEvent": {},
                },
                "event_handlers": {},
                "aggregate": {},
            },
        }
        eta = _build_event_to_agg_index(clusters)
        links = _build_links(clusters, {"process_managers": {}}, eta)
        assert links == []

    def test_skips_same_aggregate_handler(self):
        """Handlers consuming events from their own aggregate are not links."""
        clusters = {
            "app.Order": {
                "events": {
                    "app.OrderPlaced": {"__type__": "Order.OrderPlaced.v1"},
                },
                "event_handlers": {
                    "app.OrderSelfHandler": {
                        "handlers": {"Order.OrderPlaced.v1": ["on_placed"]},
                    },
                },
                "aggregate": {},
            },
        }
        eta = _build_event_to_agg_index(clusters)
        links = _build_links(clusters, {"process_managers": {}}, eta)
        assert links == []

    def test_deduplicates_links(self):
        """Same cross-aggregate edge from multiple handlers should appear once."""
        clusters = {
            "app.Order": {
                "events": {
                    "app.OrderPlaced": {"__type__": "Order.OrderPlaced.v1"},
                },
                "event_handlers": {},
                "aggregate": {},
            },
            "app.Inventory": {
                "events": {},
                "event_handlers": {
                    "app.Handler1": {
                        "handlers": {"Order.OrderPlaced.v1": ["h1"]},
                    },
                    "app.Handler2": {
                        "handlers": {"Order.OrderPlaced.v1": ["h2"]},
                    },
                },
                "aggregate": {},
            },
        }
        eta = _build_event_to_agg_index(clusters)
        links = _build_links(clusters, {"process_managers": {}}, eta)
        assert len(links) == 1

    def test_process_manager_links(self):
        """PM spanning two aggregates should create a link between them."""
        clusters = {
            "app.Order": {
                "events": {
                    "app.OrderPlaced": {"__type__": "Order.OrderPlaced.v1"},
                },
                "event_handlers": {},
                "aggregate": {},
            },
            "app.Payment": {
                "events": {
                    "app.PaymentReceived": {"__type__": "Payment.PaymentReceived.v1"},
                },
                "event_handlers": {},
                "aggregate": {},
            },
        }
        flows = {
            "process_managers": {
                "app.fulfillment.FulfillmentProcess": {
                    "name": "FulfillmentProcess",
                    "handlers": {
                        "Order.OrderPlaced.v1": {"methods": ["on_order_placed"]},
                        "Payment.PaymentReceived.v1": {"methods": ["on_payment"]},
                    },
                },
            },
        }
        eta = _build_event_to_agg_index(clusters)
        links = _build_links(clusters, flows, eta)
        assert len(links) == 1
        link = links[0]
        assert link["type"] == "process_manager"
        assert link["label"] == "FulfillmentProcess"
        # Both aggregates should be in source/target
        assert {link["source"], link["target"]} == {"app.Order", "app.Payment"}

    def test_process_manager_single_aggregate_no_link(self):
        """PM touching only one aggregate should create no links."""
        clusters = {
            "app.Order": {
                "events": {
                    "app.OrderPlaced": {"__type__": "Order.OrderPlaced.v1"},
                },
                "event_handlers": {},
                "aggregate": {},
            },
        }
        flows = {
            "process_managers": {
                "app.OrderProcess": {
                    "name": "OrderProcess",
                    "handlers": {
                        "Order.OrderPlaced.v1": {"methods": ["on_placed"]},
                    },
                },
            },
        }
        eta = _build_event_to_agg_index(clusters)
        links = _build_links(clusters, flows, eta)
        assert links == []

    def test_pm_handler_unknown_event_ignored(self):
        """PM handler referencing unknown event type is safely ignored."""
        clusters = {
            "app.Order": {
                "events": {},
                "event_handlers": {},
                "aggregate": {},
            },
        }
        flows = {
            "process_managers": {
                "app.SomeProcess": {
                    "name": "SomeProcess",
                    "handlers": {
                        "Unknown.Event.v1": {"methods": ["on_unknown"]},
                    },
                },
            },
        }
        eta = _build_event_to_agg_index(clusters)
        links = _build_links(clusters, flows, eta)
        assert links == []


class TestBuildStats:
    def test_counts_from_elements_index(self):
        ir = {
            "elements": {
                "COMMAND": ["a", "b"],
                "EVENT": ["c"],
                "ENTITY": ["d"],
                "VALUE_OBJECT": ["e", "f", "g"],
            },
            "clusters": {"agg1": {}, "agg2": {}},
            "projections": {"proj1": {}},
        }
        stats = _build_stats(ir)
        assert stats["aggregates"] == 2
        assert stats["commands"] == 2
        assert stats["events"] == 1
        assert stats["entities"] == 1
        assert stats["projections"] == 1
        assert stats["value_objects"] == 3

    def test_empty_ir(self):
        stats = _build_stats({})
        assert stats["aggregates"] == 0
        assert stats["projections"] == 0


class TestBuildGraph:
    def test_returns_all_keys(self):
        ir = {
            "clusters": {},
            "flows": {},
            "projections": {},
            "elements": {},
        }
        graph = _build_graph(ir)
        assert set(graph.keys()) == {
            "nodes",
            "links",
            "clusters",
            "flows",
            "projections",
            "stats",
            "flow_graph",
            "pm_graphs",
        }


# ---------------------------------------------------------------------------
# Static Asset Tests
# ---------------------------------------------------------------------------


class TestDomainJSContent:
    def test_serves_domain_js(self, client):
        response = client.get("/static/js/domain.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

    def test_domain_js_fetches_api(self, client):
        js = client.get("/static/js/domain.js").text
        assert "/api/domain/ir" in js

    def test_domain_js_has_tab_switching(self, client):
        js = client.get("/static/js/domain.js").text
        assert "_switchTab" in js

    def test_domain_js_has_detail_panel(self, client):
        js = client.get("/static/js/domain.js").text
        assert "_showDetail" in js
        assert "DomainDetail" in js

    def test_domain_js_has_search_wiring(self, client):
        """domain.js should wire the search input to DomainFlows."""
        js = client.get("/static/js/domain.js").text
        assert "_wireSearch" in js
        assert "DomainFlows.setSearch" in js
        assert "DomainFlows.clearSearch" in js
        assert "DomainFlows.getNodes" in js
        assert "DomainFlows.onSearchChange" in js

    def test_domain_js_search_has_keyboard_nav(self, client):
        """Search should support arrow key navigation and Enter selection."""
        js = client.get("/static/js/domain.js").text
        assert "ArrowDown" in js
        assert "ArrowUp" in js
        assert "Escape" in js


# ---------------------------------------------------------------------------
# Router Factory Edge Cases
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestCreateDomainRouterEdgeCases:
    def test_empty_domains_returns_503(self):
        """Router with no domains returns 503 on /domain/ir."""
        app = FastAPI()
        app.include_router(create_domain_router([]), prefix="/api")
        client = TestClient(app)
        response = client.get("/api/domain/ir")
        assert response.status_code == 503
        assert response.json()["error"] == "Domain IR unavailable"

    def test_ir_build_failure_returns_503(self):
        """Router gracefully handles IR build failure."""
        mock_domain = MagicMock()
        mock_domain.name = "broken"
        mock_domain.domain_context.return_value.__enter__ = MagicMock(
            side_effect=RuntimeError("boom")
        )
        mock_domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)

        app = FastAPI()
        app.include_router(create_domain_router([mock_domain]), prefix="/api")
        client = TestClient(app)
        response = client.get("/api/domain/ir")
        assert response.status_code == 503
        assert response.json()["error"] == "Domain IR unavailable"
