"""Tests for Observatory Event Flows API endpoints and supporting functions.

Covers:
- routes/flows.py: get_cached_ir, ir_to_graph, causation_node_to_dict,
  _find_element_by_fqn, create_flows_router
- templates/flows.html: structure and JS inclusion
- static/js/flows.js: file presence
"""

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from protean.server.observatory import Observatory
from protean.server.observatory.routes.flows import (
    _find_element_by_fqn,
    _short_name,
    causation_node_to_dict,
    clear_ir_cache,
    create_flows_router,
    get_cached_ir,
    ir_to_graph,
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


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the IR cache before and after each test."""
    clear_ir_cache()
    yield
    clear_ir_cache()


def _sample_ir() -> dict:
    """Return a minimal but realistic IR dict for testing."""
    return {
        "clusters": {
            "myapp.Order": {
                "aggregate": {
                    "element_type": "AGGREGATE",
                    "fqn": "myapp.Order",
                    "name": "Order",
                    "options": {"stream_category": "test::order"},
                },
                "commands": {
                    "myapp.PlaceOrder": {
                        "__type__": "MyApp.PlaceOrder.v1",
                        "element_type": "COMMAND",
                        "fqn": "myapp.PlaceOrder",
                        "name": "PlaceOrder",
                    }
                },
                "events": {
                    "myapp.OrderPlaced": {
                        "__type__": "MyApp.OrderPlaced.v1",
                        "element_type": "EVENT",
                        "fqn": "myapp.OrderPlaced",
                        "name": "OrderPlaced",
                    }
                },
                "command_handlers": {
                    "myapp.OrderCommandHandler": {
                        "element_type": "COMMAND_HANDLER",
                        "fqn": "myapp.OrderCommandHandler",
                        "name": "OrderCommandHandler",
                        "handlers": {
                            "MyApp.PlaceOrder.v1": ["handle_place_order"],
                        },
                    }
                },
                "event_handlers": {
                    "myapp.OrderEventHandler": {
                        "element_type": "EVENT_HANDLER",
                        "fqn": "myapp.OrderEventHandler",
                        "name": "OrderEventHandler",
                        "handlers": {
                            "MyApp.OrderPlaced.v1": ["on_order_placed"],
                        },
                    }
                },
                "entities": {},
                "value_objects": {},
                "repositories": {},
                "application_services": {},
                "database_models": {},
            }
        },
        "flows": {
            "domain_services": {},
            "process_managers": {
                "myapp.ShippingProcess": {
                    "element_type": "PROCESS_MANAGER",
                    "fqn": "myapp.ShippingProcess",
                    "name": "ShippingProcess",
                    "handlers": {
                        "MyApp.OrderPlaced.v1": {
                            "methods": ["on_order_placed"],
                            "start": True,
                            "end": False,
                        }
                    },
                }
            },
            "subscribers": {
                "myapp.ExternalSubscriber": {
                    "element_type": "SUBSCRIBER",
                    "fqn": "myapp.ExternalSubscriber",
                    "name": "ExternalSubscriber",
                }
            },
        },
        "projections": {
            "myapp.OrderView": {
                "projection": {
                    "element_type": "PROJECTION",
                    "fqn": "myapp.OrderView",
                    "name": "OrderView",
                },
                "projectors": {
                    "myapp.OrderProjector": {
                        "element_type": "PROJECTOR",
                        "fqn": "myapp.OrderProjector",
                        "name": "OrderProjector",
                        "handlers": {
                            "MyApp.OrderPlaced.v1": ["on_order_placed"],
                        },
                    }
                },
                "queries": {},
                "query_handlers": {},
            }
        },
        "elements": {},
        "contracts": {},
        "diagnostics": [],
        "domain": {"name": "test"},
    }


@dataclass
class MockCausationNode:
    """Mock CausationNode for testing."""

    message_id: str
    message_type: str
    kind: str
    stream: str
    time: str | None
    global_position: int | None
    children: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# _short_name
# ---------------------------------------------------------------------------


class TestShortName:
    def test_three_part_type(self):
        assert _short_name("MyApp.OrderPlaced.v1") == "OrderPlaced"

    def test_two_part_type(self):
        assert _short_name("OrderPlaced.v1") == "OrderPlaced"

    def test_single_part(self):
        assert _short_name("OrderPlaced") == "OrderPlaced"

    def test_empty_string(self):
        assert _short_name("") == ""


# ---------------------------------------------------------------------------
# get_cached_ir
# ---------------------------------------------------------------------------


class TestGetCachedIR:
    def test_caches_ir(self):
        domain = MagicMock()
        domain.name = "test"
        domain.to_ir.return_value = {"clusters": {}}

        result1 = get_cached_ir(domain)
        result2 = get_cached_ir(domain)

        assert result1 is result2
        domain.to_ir.assert_called_once()

    def test_different_domains_cached_separately(self):
        domain1 = MagicMock()
        domain1.name = "d1"
        domain1.to_ir.return_value = {"clusters": {"a": {}}}

        domain2 = MagicMock()
        domain2.name = "d2"
        domain2.to_ir.return_value = {"clusters": {"b": {}}}

        r1 = get_cached_ir(domain1)
        r2 = get_cached_ir(domain2)

        assert r1 != r2
        domain1.to_ir.assert_called_once()
        domain2.to_ir.assert_called_once()


class TestClearIRCache:
    def test_clear_allows_refetch(self):
        domain = MagicMock()
        domain.name = "test"
        domain.to_ir.return_value = {"clusters": {}}

        get_cached_ir(domain)
        clear_ir_cache()
        get_cached_ir(domain)

        assert domain.to_ir.call_count == 2


# ---------------------------------------------------------------------------
# ir_to_graph
# ---------------------------------------------------------------------------


class TestIRToGraph:
    def test_empty_ir(self):
        graph = ir_to_graph({})
        assert graph == {"nodes": [], "edges": [], "clusters": []}

    def test_extracts_aggregate_nodes(self):
        ir = _sample_ir()
        graph = ir_to_graph(ir)
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "myapp.Order" in node_ids

    def test_extracts_command_nodes(self):
        ir = _sample_ir()
        graph = ir_to_graph(ir)
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "MyApp.PlaceOrder.v1" in node_ids

    def test_extracts_event_nodes(self):
        ir = _sample_ir()
        graph = ir_to_graph(ir)
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "MyApp.OrderPlaced.v1" in node_ids

    def test_extracts_handler_nodes(self):
        ir = _sample_ir()
        graph = ir_to_graph(ir)
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "myapp.OrderCommandHandler" in node_ids
        assert "myapp.OrderEventHandler" in node_ids

    def test_extracts_pm_nodes(self):
        ir = _sample_ir()
        graph = ir_to_graph(ir)
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "myapp.ShippingProcess" in node_ids

    def test_extracts_subscriber_nodes(self):
        ir = _sample_ir()
        graph = ir_to_graph(ir)
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "myapp.ExternalSubscriber" in node_ids

    def test_extracts_projector_and_projection_nodes(self):
        ir = _sample_ir()
        graph = ir_to_graph(ir)
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "myapp.OrderProjector" in node_ids
        assert "myapp.OrderView" in node_ids

    def test_handles_edges(self):
        ir = _sample_ir()
        graph = ir_to_graph(ir)
        edge_pairs = {(e["source"], e["target"]) for e in graph["edges"]}
        # Command → command handler
        assert ("MyApp.PlaceOrder.v1", "myapp.OrderCommandHandler") in edge_pairs
        # Event → event handler
        assert ("MyApp.OrderPlaced.v1", "myapp.OrderEventHandler") in edge_pairs
        # Event → PM
        assert ("MyApp.OrderPlaced.v1", "myapp.ShippingProcess") in edge_pairs
        # Event → projector
        assert ("MyApp.OrderPlaced.v1", "myapp.OrderProjector") in edge_pairs
        # Projector → projection
        assert ("myapp.OrderProjector", "myapp.OrderView") in edge_pairs

    def test_filters_edges_with_missing_nodes(self):
        ir = {
            "clusters": {
                "myapp.Order": {
                    "aggregate": {"fqn": "myapp.Order", "name": "Order"},
                    "commands": {},
                    "events": {},
                    "command_handlers": {
                        "myapp.CH": {
                            "fqn": "myapp.CH",
                            "name": "CH",
                            "handlers": {
                                "NonExistent.Type.v1": ["handle"],
                            },
                        }
                    },
                    "event_handlers": {},
                    "entities": {},
                    "value_objects": {},
                    "repositories": {},
                    "application_services": {},
                    "database_models": {},
                }
            },
            "flows": {"domain_services": {}, "process_managers": {}, "subscribers": {}},
            "projections": {},
        }
        graph = ir_to_graph(ir)
        # The edge from NonExistent.Type.v1 → myapp.CH should be filtered out
        # because NonExistent.Type.v1 is not a node
        for e in graph["edges"]:
            assert e["source"] != "NonExistent.Type.v1"

    def test_clusters_list(self):
        ir = _sample_ir()
        graph = ir_to_graph(ir)
        assert "Order" in graph["clusters"]

    def test_node_types_correct(self):
        ir = _sample_ir()
        graph = ir_to_graph(ir)
        types_by_id = {n["id"]: n["type"] for n in graph["nodes"]}
        assert types_by_id["myapp.Order"] == "aggregate"
        assert types_by_id["MyApp.PlaceOrder.v1"] == "command"
        assert types_by_id["MyApp.OrderPlaced.v1"] == "event"
        assert types_by_id["myapp.OrderCommandHandler"] == "command_handler"
        assert types_by_id["myapp.ShippingProcess"] == "process_manager"

    def test_node_aggregate_attribute(self):
        ir = _sample_ir()
        graph = ir_to_graph(ir)
        cmd_node = next(n for n in graph["nodes"] if n["id"] == "MyApp.PlaceOrder.v1")
        assert cmd_node.get("aggregate") == "Order"

    def test_domain_service_nodes(self):
        ir = {
            "clusters": {},
            "flows": {
                "domain_services": {
                    "myapp.OrderService": {
                        "element_type": "DOMAIN_SERVICE",
                        "fqn": "myapp.OrderService",
                        "name": "OrderService",
                    }
                },
                "process_managers": {},
                "subscribers": {},
            },
            "projections": {},
        }
        graph = ir_to_graph(ir)
        node_ids = {n["id"] for n in graph["nodes"]}
        assert "myapp.OrderService" in node_ids

    def test_skip_dollar_any_handlers(self):
        ir = {
            "clusters": {
                "myapp.Order": {
                    "aggregate": {"fqn": "myapp.Order", "name": "Order"},
                    "commands": {},
                    "events": {},
                    "command_handlers": {},
                    "event_handlers": {
                        "myapp.EH": {
                            "fqn": "myapp.EH",
                            "name": "EH",
                            "handlers": {
                                "$any": ["handle"],
                                "MyApp.OrderPlaced.v1": ["on_placed"],
                            },
                        }
                    },
                    "entities": {},
                    "value_objects": {},
                    "repositories": {},
                    "application_services": {},
                    "database_models": {},
                }
            },
            "flows": {"domain_services": {}, "process_managers": {}, "subscribers": {}},
            "projections": {},
        }
        graph = ir_to_graph(ir)
        # No edge from "$any" to the handler
        for e in graph["edges"]:
            assert e["source"] != "$any"


# ---------------------------------------------------------------------------
# causation_node_to_dict
# ---------------------------------------------------------------------------


class TestCausationNodeToDict:
    def test_leaf_node(self):
        node = MockCausationNode(
            message_id="abc-123",
            message_type="MyApp.OrderPlaced.v1",
            kind="EVENT",
            stream="order-123",
            time="2024-01-01T00:00:00Z",
            global_position=1,
        )
        result = causation_node_to_dict(node)
        assert result["message_id"] == "abc-123"
        assert result["message_type"] == "MyApp.OrderPlaced.v1"
        assert result["kind"] == "EVENT"
        assert result["stream"] == "order-123"
        assert result["time"] == "2024-01-01T00:00:00Z"
        assert result["global_position"] == 1
        assert result["children"] == []

    def test_nested_tree(self):
        child = MockCausationNode(
            message_id="def-456",
            message_type="MyApp.OrderPlaced.v1",
            kind="EVENT",
            stream="order-456",
            time=None,
            global_position=2,
        )
        root = MockCausationNode(
            message_id="abc-123",
            message_type="MyApp.PlaceOrder.v1",
            kind="COMMAND",
            stream="order-cmd-123",
            time="2024-01-01T00:00:00Z",
            global_position=1,
            children=[child],
        )
        result = causation_node_to_dict(root)
        assert len(result["children"]) == 1
        assert result["children"][0]["message_id"] == "def-456"
        assert result["children"][0]["kind"] == "EVENT"

    def test_none_children(self):
        node = MockCausationNode(
            message_id="abc",
            message_type="T",
            kind="EVENT",
            stream="s",
            time=None,
            global_position=None,
            children=None,
        )
        result = causation_node_to_dict(node)
        assert result["children"] == []


# ---------------------------------------------------------------------------
# _find_element_by_fqn
# ---------------------------------------------------------------------------


class TestFindElementByFqn:
    def test_find_aggregate(self):
        ir = _sample_ir()
        result = _find_element_by_fqn(ir, "myapp.Order")
        assert result is not None
        assert result["name"] == "Order"

    def test_find_command(self):
        ir = _sample_ir()
        result = _find_element_by_fqn(ir, "myapp.PlaceOrder")
        assert result is not None
        assert result["name"] == "PlaceOrder"

    def test_find_event(self):
        ir = _sample_ir()
        result = _find_element_by_fqn(ir, "myapp.OrderPlaced")
        assert result is not None
        assert result["name"] == "OrderPlaced"

    def test_find_command_handler(self):
        ir = _sample_ir()
        result = _find_element_by_fqn(ir, "myapp.OrderCommandHandler")
        assert result is not None
        assert result["name"] == "OrderCommandHandler"

    def test_find_process_manager(self):
        ir = _sample_ir()
        result = _find_element_by_fqn(ir, "myapp.ShippingProcess")
        assert result is not None
        assert result["name"] == "ShippingProcess"

    def test_find_subscriber(self):
        ir = _sample_ir()
        result = _find_element_by_fqn(ir, "myapp.ExternalSubscriber")
        assert result is not None
        assert result["name"] == "ExternalSubscriber"

    def test_find_projection(self):
        ir = _sample_ir()
        result = _find_element_by_fqn(ir, "myapp.OrderView")
        assert result is not None
        assert result["name"] == "OrderView"

    def test_find_projector(self):
        ir = _sample_ir()
        result = _find_element_by_fqn(ir, "myapp.OrderProjector")
        assert result is not None
        assert result["name"] == "OrderProjector"

    def test_not_found(self):
        ir = _sample_ir()
        result = _find_element_by_fqn(ir, "nonexistent.Element")
        assert result is None

    def test_empty_ir(self):
        result = _find_element_by_fqn({}, "anything")
        assert result is None


# ---------------------------------------------------------------------------
# Endpoint: /api/flows/graph
# ---------------------------------------------------------------------------


class TestFlowsGraphEndpoint:
    def test_returns_graph_shape(self, client):
        resp = client.get("/api/flows/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert "clusters" in data
        assert isinstance(data["nodes"], list)
        assert isinstance(data["edges"], list)
        assert isinstance(data["clusters"], list)

    def test_handles_ir_exception(self):
        domain = MagicMock()
        domain.name = "broken"
        domain.to_ir.side_effect = Exception("IR build failed")

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)
        resp = c.get("/api/flows/graph")
        assert resp.status_code == 200
        data = resp.json()
        # Should still return valid structure even on error
        assert data["nodes"] == []
        assert data["edges"] == []


# ---------------------------------------------------------------------------
# Endpoint: /api/flows/trace/{correlation_id}
# ---------------------------------------------------------------------------


class TestFlowsTraceEndpoint:
    def test_not_found(self, client):
        resp = client.get("/api/flows/trace/nonexistent-correlation-id")
        assert resp.status_code == 404
        data = resp.json()
        assert "error" in data

    def test_returns_tree(self):
        mock_tree = MockCausationNode(
            message_id="abc-123",
            message_type="MyApp.PlaceOrder.v1",
            kind="COMMAND",
            stream="order-cmd",
            time="2024-01-01T00:00:00Z",
            global_position=1,
        )

        domain = MagicMock()
        domain.name = "test"
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.event_store.store.build_causation_tree.return_value = mock_tree

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)
        resp = c.get("/api/flows/trace/test-correlation-id")
        assert resp.status_code == 200
        data = resp.json()
        assert "tree" in data
        assert data["tree"]["message_id"] == "abc-123"
        assert data["tree"]["kind"] == "COMMAND"

    def test_handles_exception(self):
        domain = MagicMock()
        domain.name = "test"
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.event_store.store.build_causation_tree.side_effect = Exception("fail")

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)
        resp = c.get("/api/flows/trace/test-id")
        assert resp.status_code == 404

    def test_tree_returns_none(self):
        domain = MagicMock()
        domain.name = "test"
        domain.domain_context.return_value.__enter__ = MagicMock(return_value=None)
        domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        domain.event_store.store.build_causation_tree.return_value = None

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)
        resp = c.get("/api/flows/trace/test-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Endpoint: /api/flows/element/{fqn}
# ---------------------------------------------------------------------------


class TestFlowsElementEndpoint:
    def test_not_found(self):
        domain = MagicMock()
        domain.name = "test"
        domain.to_ir.return_value = _sample_ir()

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)
        resp = c.get("/api/flows/element/nonexistent.Element")
        assert resp.status_code == 404

    def test_returns_element(self):
        domain = MagicMock()
        domain.name = "test"
        domain.to_ir.return_value = _sample_ir()

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)
        resp = c.get("/api/flows/element/myapp.PlaceOrder")
        assert resp.status_code == 200
        data = resp.json()
        assert "element" in data
        assert data["element"]["name"] == "PlaceOrder"

    def test_handles_ir_exception(self):
        domain = MagicMock()
        domain.name = "broken"
        domain.to_ir.side_effect = Exception("IR error")

        obs = Observatory(domains=[domain])
        c = TestClient(obs.app)
        resp = c.get("/api/flows/element/myapp.Order")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Template: flows.html
# ---------------------------------------------------------------------------


class TestFlowsTemplate:
    def test_renders_page(self, client):
        resp = client.get("/flows")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_includes_graph_container(self, client):
        resp = client.get("/flows")
        html = resp.text
        assert 'id="flow-graph"' in html

    def test_includes_cluster_filter(self, client):
        resp = client.get("/flows")
        html = resp.text
        assert 'id="cluster-filter"' in html

    def test_includes_trace_search(self, client):
        resp = client.get("/flows")
        html = resp.text
        assert 'id="trace-search"' in html

    def test_includes_causation_tree_container(self, client):
        resp = client.get("/flows")
        html = resp.text
        assert 'id="causation-tree"' in html

    def test_includes_node_detail_panel(self, client):
        resp = client.get("/flows")
        html = resp.text
        assert 'id="node-detail"' in html

    def test_includes_flows_js(self, client):
        resp = client.get("/flows")
        html = resp.text
        assert "/static/js/flows.js" in html

    def test_zoom_controls(self, client):
        resp = client.get("/flows")
        html = resp.text
        assert 'id="zoom-in"' in html
        assert 'id="zoom-out"' in html
        assert 'id="zoom-reset"' in html


# ---------------------------------------------------------------------------
# Static: flows.js
# ---------------------------------------------------------------------------


class TestFlowsStaticFiles:
    def test_flows_js_exists(self, client):
        resp = client.get("/static/js/flows.js")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Route Wiring
# ---------------------------------------------------------------------------


class TestFlowsRouteWiring:
    def test_create_flows_router_returns_router(self):
        router = create_flows_router([])
        assert hasattr(router, "routes")

    def test_flows_routes_present(self):
        domain = MagicMock()
        domain.name = "test"
        router = create_flows_router([domain])
        paths = [r.path for r in router.routes]
        assert "/flows/graph" in paths
        assert "/flows/trace/{correlation_id}" in paths
        assert "/flows/element/{fqn:path}" in paths

    def test_api_router_includes_flows_routes(self, client):
        """Verify flows routes are wired into the Observatory app."""
        resp = client.get("/api/flows/graph")
        assert resp.status_code == 200
