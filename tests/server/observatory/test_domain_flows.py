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


@pytest.fixture
def rich_domain():
    """Domain with process managers, projectors, and fact events."""
    from protean import Domain
    from protean.core.aggregate import BaseAggregate
    from protean.core.command import BaseCommand
    from protean.core.command_handler import BaseCommandHandler
    from protean.core.event import BaseEvent
    from protean.core.event_handler import BaseEventHandler
    from protean.core.projection import BaseProjection
    from protean.core.projector import BaseProjector, on
    from protean.fields import DateTime, Float, Identifier, String
    from protean.utils.mixins import handle

    domain = Domain(name="RichDomain")

    @domain.aggregate
    class Order(BaseAggregate):
        customer_id = Identifier(required=True)
        status = String(default="draft")

        def place(self):
            self.raise_(OrderPlaced(order_id=self.id, customer_id=self.customer_id))

    @domain.event(part_of=Order)
    class OrderPlaced(BaseEvent):
        order_id = Identifier(required=True)
        customer_id = Identifier(required=True)

    @domain.command(part_of=Order)
    class PlaceOrder(BaseCommand):
        order_id = Identifier(required=True)
        customer_id = Identifier(required=True)

    @domain.command_handler(part_of=Order)
    class OrderCommandHandler(BaseCommandHandler):
        @handle(PlaceOrder)
        def handle_place_order(self, command):
            pass

    @domain.aggregate
    class Shipment(BaseAggregate):
        order_id = Identifier(required=True)
        status = String(default="pending")

    @domain.event(part_of=Shipment)
    class ShipmentDispatched(BaseEvent):
        shipment_id = Identifier(required=True)

    @domain.event_handler(part_of=Shipment, stream_category="order")
    class ShipmentOrderHandler(BaseEventHandler):
        @handle(OrderPlaced)
        def on_order_placed(self, event):
            pass

    # Process manager spanning Order and Shipment
    @domain.process_manager(stream_categories=["order", "shipment"])
    class OrderFulfillment:
        order_id = Identifier(required=True)
        status = String(default="started")

        @handle(OrderPlaced, start=True, correlate="order_id")
        def handle_order_placed(self, event):
            self.order_id = event.order_id

        @handle(ShipmentDispatched, end=True, correlate="order_id")
        def handle_shipment_dispatched(self, event):
            pass

    # Projection + Projector
    @domain.projection
    class OrderSummary(BaseProjection):
        order_id = Identifier(identifier=True)
        customer_id = String()
        placed_at = DateTime()
        total = Float()

    class OrderSummaryProjector(BaseProjector):
        @on(OrderPlaced)
        def on_order_placed(self, event):
            pass

    domain.register(
        OrderSummaryProjector, projector_for=OrderSummary, aggregates=[Order]
    )

    domain.init(traverse=False)
    return domain


@pytest.fixture
def rich_flow_graph(rich_domain):
    """Build the flow graph from the rich domain."""
    from protean.ir.builder import IRBuilder

    with rich_domain.domain_context():
        ir = IRBuilder(rich_domain).build()
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

    def test_flows_js_has_search_api(self, client):
        """Module should export search methods."""
        js = client.get("/static/js/domain-flows.js").text
        assert "setSearch:" in js
        assert "clearSearch:" in js
        assert "getNodes:" in js
        assert "onSearchChange:" in js

    def test_flows_js_has_pinned_state(self, client):
        """Search uses a pinned node ID for persistent highlighting."""
        js = client.get("/static/js/domain-flows.js").text
        assert "_pinnedNodeId" in js

    def test_flows_js_has_zoom_to_connected(self, client):
        """Search should zoom to the connected subgraph."""
        js = client.get("/static/js/domain-flows.js").text
        assert "_zoomToConnected" in js

    def test_flows_js_has_focal_class(self, client):
        """Searched node gets a distinct 'focal' class."""
        js = client.get("/static/js/domain-flows.js").text
        assert "dv-flow-focal" in js

    def test_flows_js_reset_button_clears_search(self, client):
        """Reset button should call clearSearch(), not just _fitToView()."""
        js = client.get("/static/js/domain-flows.js").text
        # The reset button click handler should invoke clearSearch
        assert "clearSearch()" in js

    def test_flows_js_hover_guards_pinned(self, client):
        """Mouse hover should be suppressed when search is pinned."""
        js = client.get("/static/js/domain-flows.js").text
        assert "if (!_pinnedNodeId) _highlightPath" in js

    def test_flows_js_node_click_toggles_search(self, client):
        """Clicking a node should pin/unpin search."""
        js = client.get("/static/js/domain-flows.js").text
        assert "event.stopPropagation" in js
        assert "_pinnedNodeId === d.id" in js

    def test_flows_js_cluster_band_layout(self, client):
        """Layout should use globally consistent cluster bands."""
        js = client.get("/static/js/domain-flows.js").text
        assert "clusterMaxRows" in js
        assert "clusterYStart" in js


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

    def test_has_search_input(self, client):
        """Event flows tab should have a search input."""
        html = client.get("/domain").text
        assert 'id="dv-flow-search"' in html
        assert 'placeholder="Search elements..."' in html

    def test_has_search_clear_button(self, client):
        html = client.get("/domain").text
        assert 'id="dv-flow-search-clear"' in html

    def test_has_search_dropdown(self, client):
        html = client.get("/domain").text
        assert 'id="dv-flow-search-results"' in html

    def test_search_dropdown_starts_hidden(self, client):
        """Search dropdown should be hidden by default."""
        html = client.get("/domain").text
        # The dropdown <ul> should have 'hidden' class
        assert "dv-search-dropdown hidden" in html


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

    def test_process_manager_node(self, rich_flow_graph):
        """Process manager should appear as a node."""
        graph = rich_flow_graph
        pm_nodes = [n for n in graph["nodes"] if n["type"] == "process_manager"]
        assert len(pm_nodes) == 1
        assert pm_nodes[0]["name"] == "OrderFulfillment"

    def test_process_manager_edges(self, rich_flow_graph):
        """PM should have event edges from the events it handles."""
        graph = rich_flow_graph
        pm_node = [n for n in graph["nodes"] if n["type"] == "process_manager"][0]
        pm_edges = [e for e in graph["edges"] if e["target"] == pm_node["id"]]
        assert len(pm_edges) >= 2, (
            "PM should have edges from OrderPlaced and ShipmentDispatched"
        )

        # Check start/end lifecycle annotations
        start_edges = [e for e in pm_edges if e.get("start")]
        end_edges = [e for e in pm_edges if e.get("end")]
        assert len(start_edges) >= 1, "PM should have at least one start edge"
        assert len(end_edges) >= 1, "PM should have at least one end edge"

    def test_projector_node(self, rich_flow_graph):
        """Projector should appear as a node with projection name."""
        graph = rich_flow_graph
        proj_nodes = [n for n in graph["nodes"] if n["type"] == "projector"]
        assert len(proj_nodes) == 1
        assert proj_nodes[0].get("projection") == "OrderSummary"

    def test_projector_edge(self, rich_flow_graph):
        """Projector should have a projection-type edge from the event it handles."""
        graph = rich_flow_graph
        proj_edges = [e for e in graph["edges"] if e["type"] == "projection"]
        assert len(proj_edges) >= 1

        proj_node_ids = {n["id"] for n in graph["nodes"] if n["type"] == "projector"}
        for e in proj_edges:
            assert e["target"] in proj_node_ids

    @pytest.mark.no_test_domain
    def test_fact_events_excluded(self):
        """Fact events should not produce nodes or edges."""
        from protean import Domain
        from protean.core.aggregate import BaseAggregate
        from protean.core.event import BaseEvent
        from protean.fields import Identifier, String
        from protean.ir.builder import IRBuilder

        domain = Domain(name="FactTest")

        @domain.aggregate(fact_events=True)
        class Account(BaseAggregate):
            name = String(required=True)

        @domain.event(part_of=Account)
        class AccountOpened(BaseEvent):
            account_id = Identifier(required=True)

        domain.init(traverse=False)

        with domain.domain_context():
            ir = IRBuilder(domain).build()
        graph = _build_flow_graph(ir)

        # Only non-fact events should be present
        evt_nodes = [n for n in graph["nodes"] if n["type"] == "event"]
        for n in evt_nodes:
            assert "Fact" not in n["name"], f"Fact event node found: {n['name']}"

        # The explicit AccountOpened should be present (it's not a fact event)
        # but fact events auto-generated by fact_events=True should not
        agg_nodes = [n for n in graph["nodes"] if n["type"] == "aggregate"]
        assert len(agg_nodes) == 1

    def test_event_handler_cross_aggregate_flag(self, rich_flow_graph):
        """Event handler edges should have the cross_aggregate flag.
        PM and projector edges use different types and don't carry this flag."""
        graph = rich_flow_graph
        eh_ids = {n["id"] for n in graph["nodes"] if n["type"] == "event_handler"}
        eh_event_edges = [
            e for e in graph["edges"] if e["type"] == "event" and e["target"] in eh_ids
        ]
        assert len(eh_event_edges) > 0, "Expected event handler edges"

        for e in eh_event_edges:
            assert "cross_aggregate" in e

    def test_rich_domain_all_node_types(self, rich_flow_graph):
        """Rich domain should have all 7 node types."""
        graph = rich_flow_graph
        types_present = {n["type"] for n in graph["nodes"]}
        expected = {
            "aggregate",
            "command",
            "command_handler",
            "event",
            "event_handler",
            "process_manager",
            "projector",
        }
        assert expected.issubset(types_present), (
            f"Missing types: {expected - types_present}"
        )

    def test_rich_domain_all_edge_types(self, rich_flow_graph):
        """Rich domain should have all edge types."""
        graph = rich_flow_graph
        edge_types = {e["type"] for e in graph["edges"]}
        expected = {"command", "handler_to_agg", "raises", "event", "projection"}
        assert expected.issubset(edge_types), (
            f"Missing edge types: {expected - edge_types}"
        )


# ---------------------------------------------------------------------------
# Edge-case tests (synthetic IR) — cover partial branches
# ---------------------------------------------------------------------------


class TestFlowGraphEdgeCases:
    """Tests using hand-crafted IR dicts to cover defensive branches."""

    def _minimal_cluster(self, **overrides):
        base = {
            "aggregate": {"name": "Agg", "options": {}},
            "commands": {},
            "events": {},
            "command_handlers": {},
            "event_handlers": {},
            "entities": {},
            "value_objects": {},
            "repositories": {},
            "application_services": {},
            "database_models": {},
        }
        base.update(overrides)
        return base

    def test_handler_references_unknown_command_type(self):
        """Command handler referencing a __type__ not in any cluster's commands."""
        ir = {
            "clusters": {
                "app.Order": self._minimal_cluster(
                    command_handlers={
                        "app.OrderHandler": {
                            "handlers": {"Unknown.Cmd.v1": ["do_it"]},
                        }
                    },
                ),
            },
            "flows": {"process_managers": {}},
            "projections": {},
            "elements": {},
        }
        graph = _build_flow_graph(ir)
        cmd_edges = [e for e in graph["edges"] if e["type"] == "command"]
        assert len(cmd_edges) == 0, "No command edge for unknown type"
        # handler_to_agg edge should still exist
        h2a = [e for e in graph["edges"] if e["type"] == "handler_to_agg"]
        assert len(h2a) == 1

    def test_event_handler_references_unknown_event_type(self):
        """Event handler referencing a __type__ not in any cluster's events."""
        ir = {
            "clusters": {
                "app.Order": self._minimal_cluster(
                    event_handlers={
                        "app.OrderEH": {
                            "handlers": {"Unknown.Evt.v1": ["handle_it"]},
                        }
                    },
                ),
            },
            "flows": {"process_managers": {}},
            "projections": {},
            "elements": {},
        }
        graph = _build_flow_graph(ir)
        event_edges = [e for e in graph["edges"] if e["type"] == "event"]
        assert len(event_edges) == 0

    def test_pm_references_unknown_event_type(self):
        """Process manager handler referencing an unknown event __type__."""
        ir = {
            "clusters": {"app.Order": self._minimal_cluster()},
            "flows": {
                "process_managers": {
                    "app.Fulfillment": {
                        "name": "Fulfillment",
                        "handlers": {
                            "Unknown.Evt.v1": {
                                "methods": ["handle"],
                                "start": True,
                                "end": False,
                                "correlate": "id",
                            },
                        },
                        "stream_categories": [],
                    }
                }
            },
            "projections": {},
            "elements": {},
        }
        graph = _build_flow_graph(ir)
        pm_nodes = [n for n in graph["nodes"] if n["type"] == "process_manager"]
        assert len(pm_nodes) == 1
        # No edges from PM since event type is unknown
        pm_edges = [e for e in graph["edges"] if e["target"] == pm_nodes[0]["id"]]
        assert len(pm_edges) == 0

    def test_projector_references_unknown_event_type(self):
        """Projector handler referencing an unknown event __type__."""
        ir = {
            "clusters": {"app.Order": self._minimal_cluster()},
            "flows": {"process_managers": {}},
            "projections": {
                "app.Summary": {
                    "projectors": {
                        "app.SummaryProjector": {
                            "projector_for": "app.Summary",
                            "handlers": {"Unknown.Evt.v1": ["on_it"]},
                        }
                    }
                }
            },
            "elements": {},
        }
        graph = _build_flow_graph(ir)
        proj_nodes = [n for n in graph["nodes"] if n["type"] == "projector"]
        assert len(proj_nodes) == 1
        proj_edges = [e for e in graph["edges"] if e["type"] == "projection"]
        assert len(proj_edges) == 0

    def test_duplicate_node_ids_are_deduplicated(self):
        """_add_node should skip if node ID already exists."""
        ir = {
            "clusters": {
                "app.Order": self._minimal_cluster(
                    events={
                        "app.OrderPlaced": {
                            "__type__": "Order.OrderPlaced.v1",
                            "is_fact_event": False,
                        },
                    },
                    event_handlers={
                        # EH in same cluster listening to same-cluster event
                        "app.OrderEH": {
                            "handlers": {"Order.OrderPlaced.v1": ["handle"]},
                        }
                    },
                ),
                # Second cluster also has an event handler for the same event
                "app.Inventory": self._minimal_cluster(
                    **{
                        "aggregate": {"name": "Inventory", "options": {}},
                        "event_handlers": {
                            "app.InvEH": {
                                "handlers": {"Order.OrderPlaced.v1": ["on_placed"]},
                            }
                        },
                    }
                ),
            },
            "flows": {"process_managers": {}},
            "projections": {},
            "elements": {},
        }
        graph = _build_flow_graph(ir)
        # OrderPlaced event node should appear exactly once
        evt_nodes = [n for n in graph["nodes"] if n["id"] == "app.OrderPlaced"]
        assert len(evt_nodes) == 1

        # Both event handler edges should exist
        event_edges = [e for e in graph["edges"] if e["type"] == "event"]
        assert len(event_edges) == 2

        # One should be cross-aggregate, one same-aggregate
        cross = [e for e in event_edges if e.get("cross_aggregate")]
        same = [e for e in event_edges if not e.get("cross_aggregate")]
        assert len(cross) == 1
        assert len(same) == 1


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
