"""Tests for the Domain Topology D3 force-directed graph (#876).

Covers:
- domain-topology.js static asset serving
- domain.js integration with DomainTopology module
- Template includes the new script
- Graph data shape supports force-directed rendering
- Multi-aggregate and single-aggregate scenarios
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory
from protean.server.observatory.routes.domain import (
    _build_event_to_agg_index,
    _build_links,
    _build_nodes,
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
# Single-aggregate domain fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def single_agg_domain():
    """Domain with a single aggregate (no cross-aggregate links)."""
    from protean import Domain
    from protean.core.aggregate import BaseAggregate
    from protean.core.event import BaseEvent
    from protean.fields import Identifier, String

    domain = Domain(name="SingleAgg")

    @domain.aggregate
    class Product(BaseAggregate):
        name = String(required=True)

    @domain.event(part_of=Product)
    class ProductCreated(BaseEvent):
        product_id = Identifier(required=True)

    domain.init(traverse=False)
    return domain


@pytest.fixture
def single_agg_client(single_agg_domain):
    obs = Observatory(domains=[single_agg_domain])
    return TestClient(obs.app)


# ---------------------------------------------------------------------------
# Static Asset Tests
# ---------------------------------------------------------------------------


class TestDomainTopologyJS:
    def test_serves_topology_js(self, client):
        response = client.get("/static/js/domain-topology.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

    def test_topology_js_has_render(self, client):
        js = client.get("/static/js/domain-topology.js").text
        assert "DomainTopology" in js
        assert "render" in js

    def test_topology_js_has_destroy(self, client):
        js = client.get("/static/js/domain-topology.js").text
        assert "destroy" in js

    def test_topology_js_has_force_simulation(self, client):
        js = client.get("/static/js/domain-topology.js").text
        assert "forceSimulation" in js

    def test_topology_js_has_zoom(self, client):
        js = client.get("/static/js/domain-topology.js").text
        assert "d3.zoom" in js

    def test_topology_js_has_drag(self, client):
        js = client.get("/static/js/domain-topology.js").text
        assert "d3.drag" in js

    def test_topology_js_has_minimap(self, client):
        js = client.get("/static/js/domain-topology.js").text
        assert "minimap" in js.lower()

    def test_topology_js_has_legend(self, client):
        js = client.get("/static/js/domain-topology.js").text
        assert "_renderLegend" in js

    def test_topology_js_has_highlight(self, client):
        js = client.get("/static/js/domain-topology.js").text
        assert "_highlightConnected" in js


# ---------------------------------------------------------------------------
# Template Integration Tests
# ---------------------------------------------------------------------------


class TestDomainTemplateIntegration:
    def test_includes_topology_js(self, client):
        html = client.get("/domain").text
        assert "/static/js/domain-topology.js" in html

    def test_topology_js_before_domain_js(self, client):
        """domain-topology.js must load before domain.js (dependency order)."""
        html = client.get("/domain").text
        topo_pos = html.index("domain-topology.js")
        domain_pos = html.index("domain.js")
        assert topo_pos < domain_pos

    def test_topology_container_exists(self, client):
        html = client.get("/domain").text
        assert 'id="dv-topology-container"' in html


class TestDomainJSIntegration:
    def test_domain_js_delegates_to_topology(self, client):
        """domain.js should call DomainTopology.render, not render cards."""
        js = client.get("/static/js/domain.js").text
        assert "DomainTopology.render" in js

    def test_domain_js_topology_not_placeholder(self, client):
        """Topology section should delegate to DomainTopology, not use card grid."""
        js = client.get("/static/js/domain.js").text
        assert "DomainTopology.render" in js
        # The placeholder comment should be gone
        assert "D3 force-directed graph in #876" not in js


# ---------------------------------------------------------------------------
# CSS Tests
# ---------------------------------------------------------------------------


class TestTopologyCSS:
    def test_css_has_topology_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-topology-svg" in css

    def test_css_has_node_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-node" in css
        assert ".dv-card" in css

    def test_css_has_link_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-link" in css
        assert ".dv-link--event" in css
        assert ".dv-link--process_manager" in css

    def test_css_has_dimmed_highlighted_states(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-dimmed" in css
        assert ".dv-highlighted" in css

    def test_css_has_minimap_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-minimap" in css
        assert ".dv-minimap-viewport" in css

    def test_css_has_legend_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-legend" in css

    def test_css_has_arch_badge_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-arch-badge--es" in css
        assert ".dv-arch-badge--cqrs" in css


# ---------------------------------------------------------------------------
# Graph Data Shape Tests (for D3 force-directed consumption)
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestGraphDataForForceLayout:
    """Verify the /api/domain/ir response provides data suitable for
    D3 force-directed layout (nodes with id, links with source/target)."""

    def test_nodes_have_id_for_force_layout(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for node in data["nodes"]:
            assert "id" in node, "Each node needs an 'id' for d3.forceLink"

    def test_links_reference_node_ids(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        node_ids = {n["id"] for n in data["nodes"]}
        for link in data["links"]:
            assert link["source"] in node_ids, (
                f"Link source {link['source']} not in node ids"
            )
            assert link["target"] in node_ids, (
                f"Link target {link['target']} not in node ids"
            )

    def test_nodes_have_display_fields(self, multi_agg_client):
        """Nodes should have name, counts, stream_category, is_event_sourced."""
        data = multi_agg_client.get("/api/domain/ir").json()
        for node in data["nodes"]:
            assert "name" in node
            assert "counts" in node
            assert "stream_category" in node
            assert "is_event_sourced" in node

    def test_links_have_type_and_label(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        for link in data["links"]:
            assert "type" in link
            assert link["type"] in ("event", "process_manager")
            assert "label" in link


# ---------------------------------------------------------------------------
# Single-Aggregate Rendering
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestSingleAggregateGraph:
    def test_single_aggregate_returns_one_node(self, single_agg_client):
        data = single_agg_client.get("/api/domain/ir").json()
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["name"] == "Product"

    def test_single_aggregate_no_links(self, single_agg_client):
        data = single_agg_client.get("/api/domain/ir").json()
        assert len(data["links"]) == 0


# ---------------------------------------------------------------------------
# Edge Extraction Logic (unit tests)
# ---------------------------------------------------------------------------


class TestEdgeExtractionForTopology:
    """Unit tests for the cross-aggregate edge detection that feeds the
    force-directed graph. Complements test_observatory_domain.py::TestBuildLinks
    with topology-specific edge cases."""

    def test_multiple_event_types_between_same_aggregates(self):
        """Multiple events from A->B should produce multiple distinct links."""
        clusters = {
            "app.Order": {
                "events": {
                    "app.OrderPlaced": {"__type__": "Order.OrderPlaced.v1"},
                    "app.OrderShipped": {"__type__": "Order.OrderShipped.v1"},
                },
                "event_handlers": {},
                "aggregate": {},
            },
            "app.Inventory": {
                "events": {},
                "event_handlers": {
                    "app.InventoryHandler": {
                        "handlers": {
                            "Order.OrderPlaced.v1": ["on_placed"],
                            "Order.OrderShipped.v1": ["on_shipped"],
                        },
                    },
                },
                "aggregate": {},
            },
        }
        eta = _build_event_to_agg_index(clusters)
        links = _build_links(clusters, {"process_managers": {}}, eta)
        assert len(links) == 2
        sources = {lnk["source"] for lnk in links}
        targets = {lnk["target"] for lnk in links}
        assert sources == {"app.Order"}
        assert targets == {"app.Inventory"}

    def test_three_way_pm_creates_three_links(self):
        """Process manager spanning 3 aggregates creates 3 undirected edges."""
        clusters = {
            "app.A": {
                "events": {"app.AEvt": {"__type__": "A.AEvt.v1"}},
                "event_handlers": {},
                "aggregate": {},
            },
            "app.B": {
                "events": {"app.BEvt": {"__type__": "B.BEvt.v1"}},
                "event_handlers": {},
                "aggregate": {},
            },
            "app.C": {
                "events": {"app.CEvt": {"__type__": "C.CEvt.v1"}},
                "event_handlers": {},
                "aggregate": {},
            },
        }
        flows = {
            "process_managers": {
                "app.BigProcess": {
                    "name": "BigProcess",
                    "handlers": {
                        "A.AEvt.v1": {"methods": ["on_a"]},
                        "B.BEvt.v1": {"methods": ["on_b"]},
                        "C.CEvt.v1": {"methods": ["on_c"]},
                    },
                },
            },
        }
        eta = _build_event_to_agg_index(clusters)
        links = _build_links(clusters, flows, eta)
        pm_links = [lnk for lnk in links if lnk["type"] == "process_manager"]
        assert len(pm_links) == 3
        pairs = {(lnk["source"], lnk["target"]) for lnk in pm_links}
        assert ("app.A", "app.B") in pairs
        assert ("app.A", "app.C") in pairs
        assert ("app.B", "app.C") in pairs

    def test_nodes_contain_element_counts(self):
        """Nodes should contain counts for commands, events, etc."""
        clusters = {
            "app.Order": {
                "aggregate": {"name": "Order", "options": {}},
                "commands": {"app.PlaceOrder": {}, "app.CancelOrder": {}},
                "events": {"app.OrderPlaced": {}},
                "entities": {"app.LineItem": {}},
                "value_objects": {},
                "command_handlers": {},
                "event_handlers": {},
                "repositories": {},
                "application_services": {},
                "database_models": {},
            },
        }
        nodes = _build_nodes(clusters)
        assert len(nodes) == 1
        counts = nodes[0]["counts"]
        assert counts["commands"] == 2
        assert counts["events"] == 1
        assert counts["entities"] == 1

    def test_event_sourced_flag_on_node(self):
        """is_event_sourced should be passed through from aggregate options."""
        clusters = {
            "app.Account": {
                "aggregate": {
                    "name": "Account",
                    "options": {"is_event_sourced": True, "stream_category": "account"},
                },
                "commands": {},
                "events": {},
                "entities": {},
                "value_objects": {},
                "command_handlers": {},
                "event_handlers": {},
                "repositories": {},
                "application_services": {},
                "database_models": {},
            },
        }
        nodes = _build_nodes(clusters)
        assert nodes[0]["is_event_sourced"] is True
        assert nodes[0]["stream_category"] == "account"


# ---------------------------------------------------------------------------
# Empty Domain Graceful Handling
# ---------------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestEmptyDomainTopology:
    def test_empty_domain_returns_503(self):
        """Router with no domains returns 503 on /domain/ir."""
        app = FastAPI()
        app.include_router(create_domain_router([]), prefix="/api")
        client = TestClient(app)
        response = client.get("/api/domain/ir")
        assert response.status_code == 503

    def test_empty_nodes_and_links(self):
        """An empty clusters dict should produce zero nodes and links."""
        nodes = _build_nodes({})
        links = _build_links({}, {"process_managers": {}}, {})
        assert nodes == []
        assert links == []
