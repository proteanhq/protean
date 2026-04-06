"""Tests for the Event Flow View — D3 DAG visualization (#878).

Covers:
- domain-flows.js static asset serving
- Template includes the new script and filter toggles
- _build_flow_graph DAG extraction from IR
- Node type representation
- Cross-aggregate flow detection
- Filter toggle presence in HTML
"""

import pytest

from protean.server.observatory.routes.domain import _build_flow_graph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_agg_flow_graph(multi_agg_domain):
    """Build the flow graph from the multi-aggregate domain."""
    from protean.ir.builder import IRBuilder

    with multi_agg_domain.domain_context():
        ir = IRBuilder(multi_agg_domain).build()
    return _build_flow_graph(ir)


# ---------------------------------------------------------------------------
# Static Asset Tests
# ---------------------------------------------------------------------------


class TestDomainFlowsJS:
    def test_serves_flows_js(self, client):
        response = client.get("/static/js/domain-flows.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

    def test_flows_js_has_module(self, client):
        js = client.get("/static/js/domain-flows.js").text
        assert "DomainFlows" in js
        assert "render" in js

    def test_flows_js_has_destroy(self, client):
        js = client.get("/static/js/domain-flows.js").text
        assert "destroy" in js

    def test_flows_js_has_filter(self, client):
        js = client.get("/static/js/domain-flows.js").text
        assert "setFilter" in js

    def test_flows_js_has_zoom(self, client):
        js = client.get("/static/js/domain-flows.js").text
        assert "d3.zoom" in js

    def test_flows_js_has_node_styles(self, client):
        js = client.get("/static/js/domain-flows.js").text
        assert "NODE_STYLES" in js
        assert "command_handler" in js
        assert "event_handler" in js
        assert "process_manager" in js
        assert "projector" in js


# ---------------------------------------------------------------------------
# Template Tests
# ---------------------------------------------------------------------------


class TestDomainPageTemplate:
    def test_includes_flows_script(self, client):
        html = client.get("/domain").text
        assert "domain-flows.js" in html

    def test_has_filter_toggles(self, client):
        html = client.get("/domain").text
        assert 'data-flow-filter="command"' in html
        assert 'data-flow-filter="command_handler"' in html
        assert 'data-flow-filter="event_handler"' in html
        assert 'data-flow-filter="process_manager"' in html
        assert 'data-flow-filter="projector"' in html

    def test_has_flows_container(self, client):
        html = client.get("/domain").text
        assert 'id="dv-flows-container"' in html


# ---------------------------------------------------------------------------
# Flow Graph Extraction Tests
# ---------------------------------------------------------------------------


class TestBuildFlowGraph:
    def test_empty_ir_returns_empty_graph(self):
        result = _build_flow_graph({})
        assert result["nodes"] == []
        assert result["edges"] == []

    @pytest.mark.no_test_domain
    def test_single_aggregate_produces_aggregate_node(self):
        from protean import Domain
        from protean.core.aggregate import BaseAggregate
        from protean.fields import String
        from protean.ir.builder import IRBuilder

        domain = Domain(name="SingleAgg")

        @domain.aggregate
        class Product(BaseAggregate):
            name = String(required=True)

        domain.init(traverse=False)

        with domain.domain_context():
            ir = IRBuilder(domain).build()
        graph = _build_flow_graph(ir)

        agg_nodes = [n for n in graph["nodes"] if n["type"] == "aggregate"]
        assert len(agg_nodes) == 1
        assert agg_nodes[0]["name"] == "Product"

    def test_multi_agg_has_all_node_types(self, multi_agg_flow_graph):
        """Multi-aggregate domain should have commands, handlers, aggregates, events."""
        graph = multi_agg_flow_graph
        types_present = {n["type"] for n in graph["nodes"]}

        assert "aggregate" in types_present
        assert "command" in types_present
        assert "command_handler" in types_present
        assert "event" in types_present
        assert "event_handler" in types_present

    def test_multi_agg_has_edges(self, multi_agg_flow_graph):
        graph = multi_agg_flow_graph
        assert len(graph["edges"]) > 0

    def test_command_to_handler_edge(self, multi_agg_flow_graph):
        """PlaceOrder command should link to OrderCommandHandler."""
        graph = multi_agg_flow_graph
        cmd_edges = [e for e in graph["edges"] if e["type"] == "command"]
        assert len(cmd_edges) > 0, "Expected at least one command edge"

        # Verify the edge connects a command to a command handler
        cmd_ids = {n["id"] for n in graph["nodes"] if n["type"] == "command"}
        ch_ids = {n["id"] for n in graph["nodes"] if n["type"] == "command_handler"}
        for e in cmd_edges:
            assert e["source"] in cmd_ids
            assert e["target"] in ch_ids

    def test_handler_to_aggregate_edge(self, multi_agg_flow_graph):
        graph = multi_agg_flow_graph
        h2a_edges = [e for e in graph["edges"] if e["type"] == "handler_to_agg"]
        assert len(h2a_edges) > 0

    def test_aggregate_raises_event_edge(self, multi_agg_flow_graph):
        graph = multi_agg_flow_graph
        raise_edges = [e for e in graph["edges"] if e["type"] == "raises"]
        assert len(raise_edges) > 0

    def test_cross_aggregate_event_edge(self, multi_agg_flow_graph):
        """InventoryOrderHandler listens to OrderPlaced (cross-aggregate)."""
        graph = multi_agg_flow_graph
        event_edges = [e for e in graph["edges"] if e["type"] == "event"]
        cross_edges = [e for e in event_edges if e.get("cross_aggregate")]
        assert len(cross_edges) > 0, "Expected at least one cross-aggregate event edge"

    def test_nodes_have_cluster(self, multi_agg_flow_graph):
        """Aggregate-owned nodes should have a cluster field."""
        graph = multi_agg_flow_graph
        agg_owned = [
            n
            for n in graph["nodes"]
            if n["type"] in ("command", "event", "command_handler")
        ]
        for node in agg_owned:
            assert node.get("cluster"), f"Node {node['id']} missing cluster"

    def test_node_ids_are_unique(self, multi_agg_flow_graph):
        graph = multi_agg_flow_graph
        ids = [n["id"] for n in graph["nodes"]]
        assert len(ids) == len(set(ids)), "Duplicate node IDs found"


# ---------------------------------------------------------------------------
# API Integration Tests
# ---------------------------------------------------------------------------


class TestFlowGraphAPI:
    def test_ir_endpoint_includes_flow_graph(self, multi_agg_client):
        response = multi_agg_client.get("/api/domain/ir")
        assert response.status_code == 200
        data = response.json()
        assert "flow_graph" in data
        assert "nodes" in data["flow_graph"]
        assert "edges" in data["flow_graph"]

    def test_flow_graph_has_nodes(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        nodes = data["flow_graph"]["nodes"]
        assert len(nodes) > 0
        types_present = {n["type"] for n in nodes}
        assert "aggregate" in types_present

    def test_flow_graph_has_edges(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        edges = data["flow_graph"]["edges"]
        assert len(edges) > 0
