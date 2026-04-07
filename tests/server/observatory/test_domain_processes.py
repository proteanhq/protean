"""Tests for Process Manager State Machine View and Domain Stats (#879).

Covers:
- domain-processes.js static asset serving
- Template includes the new script
- _build_pm_graphs state machine extraction from IR
- _build_stats with handler and diagnostics counts
- Stats bar HTML includes new stat elements
- Graceful handling of domain with no process managers
- PM expand/collapse header presence
"""

import pytest

from protean.server.observatory.routes.domain import (
    _build_event_to_agg_index,
    _build_graph,
    _build_pm_graphs,
    _build_stats,
    _state_label_from_event,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pm_domain():
    """Domain with process managers for state machine testing."""
    from protean import Domain
    from protean.core.aggregate import BaseAggregate
    from protean.core.event import BaseEvent
    from protean.fields import Identifier, String
    from protean.utils.mixins import handle

    domain = Domain(name="PMDomain")

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

    @domain.event(part_of=Order)
    class OrderConfirmed(BaseEvent):
        order_id = Identifier(required=True)

    @domain.aggregate
    class Shipment(BaseAggregate):
        order_id = Identifier(required=True)
        status = String(default="pending")

    @domain.event(part_of=Shipment)
    class ShipmentDispatched(BaseEvent):
        shipment_id = Identifier(required=True)

    @domain.process_manager(stream_categories=["order", "shipment"])
    class OrderFulfillment:
        order_id = Identifier(required=True)
        status = String(default="started")

        @handle(OrderPlaced, start=True, correlate="order_id")
        def handle_order_placed(self, event):
            self.order_id = event.order_id

        @handle(OrderConfirmed, correlate="order_id")
        def handle_order_confirmed(self, event):
            pass

        @handle(ShipmentDispatched, end=True, correlate="order_id")
        def handle_shipment_dispatched(self, event):
            pass

    domain.init(traverse=False)
    return domain


@pytest.fixture
def pm_ir(pm_domain):
    """Build IR from the PM domain."""
    from protean.ir.builder import IRBuilder

    with pm_domain.domain_context():
        return IRBuilder(pm_domain).build()


@pytest.fixture
def pm_graphs(pm_ir):
    """Build PM graphs from the PM domain IR."""
    flows = pm_ir.get("flows", {})
    clusters = pm_ir.get("clusters", {})
    event_to_agg = _build_event_to_agg_index(clusters)
    return _build_pm_graphs(flows, event_to_agg)


@pytest.fixture
def full_graph(pm_ir):
    """Build the full D3 graph from the PM domain IR."""
    return _build_graph(pm_ir)


# ---------------------------------------------------------------------------
# Static Asset Tests
# ---------------------------------------------------------------------------


class TestDomainProcessesJS:
    def test_serves_processes_js(self, client):
        response = client.get("/static/js/domain-processes.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

    def test_processes_js_has_module(self, client):
        js = client.get("/static/js/domain-processes.js").text
        assert "DomainProcesses" in js
        assert "render" in js

    def test_processes_js_has_destroy(self, client):
        js = client.get("/static/js/domain-processes.js").text
        assert "destroy" in js

    def test_processes_js_has_state_machine_rendering(self, client):
        js = client.get("/static/js/domain-processes.js").text
        assert "_renderStateMachine" in js
        assert "_renderStates" in js
        assert "_renderTransitions" in js


# ---------------------------------------------------------------------------
# Template Tests
# ---------------------------------------------------------------------------


class TestDomainPageTemplateProcessManagers:
    def test_includes_processes_script(self, client):
        html = client.get("/domain").text
        assert "domain-processes.js" in html

    def test_has_pm_container(self, client):
        html = client.get("/domain").text
        assert 'id="dv-pm-container"' in html

    def test_has_pm_tab(self, client):
        html = client.get("/domain").text
        assert 'data-tab="process-managers"' in html

    def test_has_handlers_stat(self, client):
        html = client.get("/domain").text
        assert 'id="dv-stat-handlers"' in html

    def test_has_diagnostics_stat(self, client):
        html = client.get("/domain").text
        assert 'id="dv-stat-diagnostics"' in html


# ---------------------------------------------------------------------------
# State Label Derivation
# ---------------------------------------------------------------------------


class TestStateLabelFromEvent:
    def test_camel_case_with_version(self):
        assert _state_label_from_event("OrderPlaced.v1") == "Order Placed"

    def test_camel_case_without_version(self):
        assert _state_label_from_event("ShipmentDispatched") == "Shipment Dispatched"

    def test_single_word(self):
        assert _state_label_from_event("Placed.v1") == "Placed"

    def test_empty_string(self):
        assert _state_label_from_event("") == ""

    def test_multi_version(self):
        assert _state_label_from_event("OrderPlaced.v2") == "Order Placed"


# ---------------------------------------------------------------------------
# PM Graph Extraction Tests
# ---------------------------------------------------------------------------


class TestBuildPMGraphs:
    def test_empty_flows_returns_empty_list(self):
        result = _build_pm_graphs({}, {})
        assert result == []

    def test_no_process_managers_returns_empty_list(self):
        result = _build_pm_graphs({"process_managers": {}}, {})
        assert result == []

    # Note: synthetic IR tests below pass {} for event_to_agg since they
    # don't need aggregate detection (no clusters defined).

    @pytest.mark.no_test_domain
    def test_pm_graph_has_expected_fields(self, pm_graphs):
        assert len(pm_graphs) == 1
        pm = pm_graphs[0]
        assert "fqn" in pm
        assert "name" in pm
        assert "states" in pm
        assert "transitions" in pm
        assert "aggregates" in pm
        assert "stream_categories" in pm

    @pytest.mark.no_test_domain
    def test_pm_graph_name(self, pm_graphs):
        assert pm_graphs[0]["name"] == "OrderFulfillment"

    @pytest.mark.no_test_domain
    def test_pm_has_start_state(self, pm_graphs):
        states = pm_graphs[0]["states"]
        start_states = [s for s in states if s["type"] == "start"]
        assert len(start_states) == 1
        assert start_states[0]["id"] == "initial"
        assert start_states[0]["label"] == "Initial"

    @pytest.mark.no_test_domain
    def test_pm_has_end_state(self, pm_graphs):
        states = pm_graphs[0]["states"]
        end_states = [s for s in states if s["type"] == "end"]
        assert len(end_states) == 1
        assert end_states[0]["id"] == "completed"
        assert end_states[0]["label"] == "Completed"

    @pytest.mark.no_test_domain
    def test_pm_has_intermediate_states(self, pm_graphs):
        states = pm_graphs[0]["states"]
        mid_states = [s for s in states if s["type"] == "intermediate"]
        assert len(mid_states) >= 1

    @pytest.mark.no_test_domain
    def test_pm_has_transitions(self, pm_graphs):
        transitions = pm_graphs[0]["transitions"]
        assert len(transitions) >= 3  # start, mid, end transitions

    @pytest.mark.no_test_domain
    def test_pm_transition_from_initial(self, pm_graphs):
        transitions = pm_graphs[0]["transitions"]
        from_initial = [t for t in transitions if t["source"] == "initial"]
        assert len(from_initial) >= 1

    @pytest.mark.no_test_domain
    def test_pm_transition_to_completed(self, pm_graphs):
        transitions = pm_graphs[0]["transitions"]
        to_completed = [t for t in transitions if t["target"] == "completed"]
        assert len(to_completed) >= 1

    @pytest.mark.no_test_domain
    def test_pm_transition_has_event_label(self, pm_graphs):
        transitions = pm_graphs[0]["transitions"]
        for t in transitions:
            assert "event" in t
            assert len(t["event"]) > 0

    @pytest.mark.no_test_domain
    def test_pm_transition_has_methods(self, pm_graphs):
        transitions = pm_graphs[0]["transitions"]
        for t in transitions:
            assert "methods" in t

    @pytest.mark.no_test_domain
    def test_pm_aggregates_detected(self, pm_graphs):
        aggs = pm_graphs[0]["aggregates"]
        assert len(aggs) >= 2  # Order and Shipment

    @pytest.mark.no_test_domain
    def test_pm_stream_categories(self, pm_graphs):
        cats = pm_graphs[0]["stream_categories"]
        assert len(cats) == 2
        # Stream categories include domain prefix (e.g. "pmdomain::order")
        cat_suffixes = [c.split("::")[-1] for c in cats]
        assert "order" in cat_suffixes
        assert "shipment" in cat_suffixes

    def test_pm_with_no_handlers(self):
        """PM with empty handlers should produce empty states/transitions."""
        flows = {
            "process_managers": {
                "app.EmptyPM": {
                    "name": "EmptyPM",
                    "handlers": {},
                    "stream_categories": [],
                }
            }
        }
        result = _build_pm_graphs(flows, {})
        assert len(result) == 1
        pm = result[0]
        assert pm["name"] == "EmptyPM"
        assert pm["states"] == []
        assert pm["transitions"] == []

    def test_pm_start_only(self):
        """PM with only a start handler produces initial + one intermediate state."""
        flows = {
            "process_managers": {
                "app.StartOnly": {
                    "name": "StartOnly",
                    "handlers": {
                        "Order.OrderPlaced.v1": {
                            "start": True,
                            "end": False,
                            "methods": ["handle_placed"],
                            "correlate": "order_id",
                        }
                    },
                    "stream_categories": ["order"],
                }
            }
        }
        result = _build_pm_graphs(flows, {})
        pm = result[0]
        assert len(pm["states"]) == 2  # initial + after:OrderPlaced
        state_types = {s["type"] for s in pm["states"]}
        assert "start" in state_types
        assert "intermediate" in state_types

    def test_pm_start_and_end_same_event(self):
        """PM where a single handler is both start and end."""
        flows = {
            "process_managers": {
                "app.OneShot": {
                    "name": "OneShot",
                    "handlers": {
                        "Order.OrderPlaced.v1": {
                            "start": True,
                            "end": True,
                            "methods": ["handle_placed"],
                            "correlate": "order_id",
                        }
                    },
                    "stream_categories": [],
                }
            }
        }
        result = _build_pm_graphs(flows, {})
        pm = result[0]
        state_ids = {s["id"] for s in pm["states"]}
        assert "initial" in state_ids
        assert "completed" in state_ids
        # Single transition from initial to completed
        assert len(pm["transitions"]) == 1
        assert pm["transitions"][0]["source"] == "initial"
        assert pm["transitions"][0]["target"] == "completed"


# ---------------------------------------------------------------------------
# Stats Tests
# ---------------------------------------------------------------------------


class TestBuildStatsEnhanced:
    def test_stats_has_handlers_count(self):
        ir = {
            "elements": {
                "COMMAND_HANDLER": ["a", "b"],
                "EVENT_HANDLER": ["c"],
                "PROCESS_MANAGER": ["d"],
            },
            "clusters": {},
            "projections": {},
        }
        stats = _build_stats(ir)
        assert stats["handlers"] == 4  # 2 + 1 + 1

    def test_stats_has_diagnostics_count(self):
        ir = {
            "elements": {},
            "clusters": {},
            "projections": {},
            "diagnostics": [
                {"code": "W001", "level": "WARNING"},
                {"code": "E001", "level": "ERROR"},
            ],
        }
        stats = _build_stats(ir)
        assert stats["diagnostics"] == 2

    def test_stats_diagnostics_zero_when_no_key(self):
        ir = {"elements": {}, "clusters": {}, "projections": {}}
        stats = _build_stats(ir)
        assert stats["diagnostics"] == 0

    def test_stats_diagnostics_zero_when_empty(self):
        ir = {"elements": {}, "clusters": {}, "projections": {}, "diagnostics": []}
        stats = _build_stats(ir)
        assert stats["diagnostics"] == 0


# ---------------------------------------------------------------------------
# Full Graph Integration Tests
# ---------------------------------------------------------------------------


class TestPMGraphInFullGraph:
    @pytest.mark.no_test_domain
    def test_full_graph_includes_pm_graphs(self, full_graph):
        assert "pm_graphs" in full_graph

    @pytest.mark.no_test_domain
    def test_full_graph_pm_graphs_non_empty(self, full_graph):
        assert len(full_graph["pm_graphs"]) == 1

    @pytest.mark.no_test_domain
    def test_full_graph_stats_has_handlers(self, full_graph):
        assert "handlers" in full_graph["stats"]

    @pytest.mark.no_test_domain
    def test_full_graph_stats_has_diagnostics(self, full_graph):
        assert "diagnostics" in full_graph["stats"]


# ---------------------------------------------------------------------------
# API Integration Tests
# ---------------------------------------------------------------------------


class TestPMGraphAPI:
    def test_ir_endpoint_includes_pm_graphs(self, multi_agg_client):
        response = multi_agg_client.get("/api/domain/ir")
        assert response.status_code == 200
        data = response.json()
        assert "pm_graphs" in data

    def test_ir_endpoint_stats_has_handlers(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        assert "handlers" in data["stats"]

    def test_ir_endpoint_stats_has_diagnostics(self, multi_agg_client):
        data = multi_agg_client.get("/api/domain/ir").json()
        assert "diagnostics" in data["stats"]


# ---------------------------------------------------------------------------
# CSS Tests
# ---------------------------------------------------------------------------


class TestPMCSS:
    def test_css_has_pm_styles(self, client):
        css = client.get("/static/css/observatory.css").text
        assert ".dv-pm-card" in css
        assert ".dv-pm-header" in css
        assert ".dv-pm-body" in css
        assert ".dv-pm-state-label" in css
        assert ".dv-pm-transition" in css
        assert ".dv-pm-chevron" in css
