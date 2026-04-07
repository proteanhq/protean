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
