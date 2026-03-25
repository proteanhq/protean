"""Tests for the event flow diagram generator.

Covers: generate_event_flow_diagram, cluster subgraphs, command/event
node shapes, handler edges, process managers, projectors, and edge cases.
"""

import pytest

from protean.ir.generators.events import (
    generate_cluster_event_flow,
    generate_downstream_consumers_diagram,
    generate_event_flow_diagram,
)


# ------------------------------------------------------------------
# Fixtures — composable IR builders
# ------------------------------------------------------------------


def _cluster(
    fqn: str,
    *,
    commands: dict | None = None,
    events: dict | None = None,
    command_handlers: dict | None = None,
    event_handlers: dict | None = None,
) -> dict:
    """Build a minimal cluster dict."""
    return {
        "aggregate": {
            "fqn": fqn,
            "name": fqn.rsplit(".", 1)[-1],
            "fields": {
                "id": {"kind": "auto", "type": "Auto", "identifier": True},
            },
            "identity_field": "id",
            "invariants": {"pre": [], "post": []},
            "options": {"is_event_sourced": False, "fact_events": False},
        },
        "entities": {},
        "value_objects": {},
        "commands": commands or {},
        "events": events or {},
        "command_handlers": command_handlers or {},
        "event_handlers": event_handlers or {},
        "repositories": {},
        "application_services": {},
        "database_models": {},
    }


def _ir(
    clusters: dict | None = None,
    flows: dict | None = None,
    projections: dict | None = None,
) -> dict:
    return {
        "clusters": clusters or {},
        "flows": flows
        or {"domain_services": {}, "process_managers": {}, "subscribers": {}},
        "projections": projections or {},
    }


def _command(fqn: str, type_str: str) -> dict:
    return {
        "__type__": type_str,
        "__version__": 1,
        "element_type": "COMMAND",
        "fqn": fqn,
        "name": fqn.rsplit(".", 1)[-1],
        "fields": {},
    }


def _event(fqn: str, type_str: str, *, is_fact_event: bool = False) -> dict:
    return {
        "__type__": type_str,
        "__version__": 1,
        "element_type": "EVENT",
        "fqn": fqn,
        "name": fqn.rsplit(".", 1)[-1],
        "fields": {},
        "is_fact_event": is_fact_event,
        "published": True,
    }


def _command_handler(fqn: str, handlers: dict) -> dict:
    return {
        "element_type": "COMMAND_HANDLER",
        "fqn": fqn,
        "name": fqn.rsplit(".", 1)[-1],
        "handlers": handlers,
        "subscription": {"config": {}, "profile": None, "type": None},
    }


def _event_handler(fqn: str, handlers: dict) -> dict:
    return {
        "element_type": "EVENT_HANDLER",
        "fqn": fqn,
        "name": fqn.rsplit(".", 1)[-1],
        "handlers": handlers,
        "subscription": {"config": {}, "profile": None, "type": None},
    }


# ------------------------------------------------------------------
# Empty / missing data
# ------------------------------------------------------------------


class TestEmptyIR:
    def test_empty_clusters(self):
        result = generate_event_flow_diagram(_ir())
        assert result == "flowchart LR"

    def test_missing_clusters_key(self):
        result = generate_event_flow_diagram({})
        assert result == "flowchart LR"


# ------------------------------------------------------------------
# Subgraph rendering
# ------------------------------------------------------------------


class TestSubgraphs:
    def test_single_cluster_subgraph(self):
        clusters = {
            "app.Order": _cluster("app.Order"),
        }
        result = generate_event_flow_diagram(_ir(clusters=clusters))
        assert "subgraph app_Order[Order]" in result
        assert "end" in result

    def test_aggregate_node_inside_subgraph(self):
        clusters = {
            "app.Order": _cluster("app.Order"),
        }
        result = generate_event_flow_diagram(_ir(clusters=clusters))
        assert "agg_app_Order[Order]" in result

    def test_multiple_subgraphs(self):
        clusters = {
            "app.Order": _cluster("app.Order"),
            "app.Payment": _cluster("app.Payment"),
        }
        result = generate_event_flow_diagram(_ir(clusters=clusters))
        assert "subgraph app_Order" in result
        assert "subgraph app_Payment" in result


# ------------------------------------------------------------------
# Command nodes (parallelogram shape)
# ------------------------------------------------------------------


class TestCommandNodes:
    def test_command_parallelogram_shape(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                commands={
                    "app.PlaceOrder": _command("app.PlaceOrder", "App.PlaceOrder.v1"),
                },
            ),
        }
        result = generate_event_flow_diagram(_ir(clusters=clusters))
        assert "cmd_app_PlaceOrder[/PlaceOrder/]" in result


# ------------------------------------------------------------------
# Event nodes (stadium/rounded shape)
# ------------------------------------------------------------------


class TestEventNodes:
    def test_event_rounded_shape(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
        }
        result = generate_event_flow_diagram(_ir(clusters=clusters))
        assert "evt_app_OrderPlaced([OrderPlaced])" in result

    def test_fact_events_excluded(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                    "app._OrderFact": _event(
                        "app._OrderFact", "App._OrderFact.v1", is_fact_event=True
                    ),
                },
            ),
        }
        result = generate_event_flow_diagram(_ir(clusters=clusters))
        assert "OrderPlaced" in result
        assert "_OrderFact" not in result


# ------------------------------------------------------------------
# Command handler edges: cmd -> handler -> aggregate
# ------------------------------------------------------------------


class TestCommandHandlerEdges:
    @pytest.fixture()
    def ir_with_handler(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                commands={
                    "app.PlaceOrder": _command("app.PlaceOrder", "App.PlaceOrder.v1"),
                },
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
                command_handlers={
                    "app.OrderCommandHandler": _command_handler(
                        "app.OrderCommandHandler",
                        {"App.PlaceOrder.v1": ["handle_place_order"]},
                    ),
                },
            ),
        }
        return _ir(clusters=clusters)

    def test_command_to_handler_edge(self, ir_with_handler):
        result = generate_event_flow_diagram(ir_with_handler)
        assert "cmd_app_PlaceOrder --> hdlr_app_OrderCommandHandler" in result

    def test_handler_to_aggregate_edge(self, ir_with_handler):
        result = generate_event_flow_diagram(ir_with_handler)
        assert "hdlr_app_OrderCommandHandler --> agg_app_Order" in result

    def test_aggregate_to_event_edge(self, ir_with_handler):
        result = generate_event_flow_diagram(ir_with_handler)
        assert "agg_app_Order --> evt_app_OrderPlaced" in result


# ------------------------------------------------------------------
# Event handler nodes and edges
# ------------------------------------------------------------------


class TestEventHandlers:
    def test_event_handler_rendered(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
                event_handlers={
                    "app.NotificationHandler": _event_handler(
                        "app.NotificationHandler",
                        {"App.OrderPlaced.v1": ["send_email"]},
                    ),
                },
            ),
        }
        result = generate_event_flow_diagram(_ir(clusters=clusters))
        assert "eh_app_NotificationHandler[NotificationHandler]" in result

    def test_event_to_handler_edge(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
                event_handlers={
                    "app.NotificationHandler": _event_handler(
                        "app.NotificationHandler",
                        {"App.OrderPlaced.v1": ["send_email"]},
                    ),
                },
            ),
        }
        result = generate_event_flow_diagram(_ir(clusters=clusters))
        assert "evt_app_OrderPlaced --> eh_app_NotificationHandler" in result


# ------------------------------------------------------------------
# Process managers
# ------------------------------------------------------------------


class TestProcessManagers:
    @pytest.fixture()
    def ir_with_pm(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
            "app.Payment": _cluster(
                "app.Payment",
                events={
                    "app.PaymentConfirmed": _event(
                        "app.PaymentConfirmed", "App.PaymentConfirmed.v1"
                    ),
                    "app.PaymentFailed": _event(
                        "app.PaymentFailed", "App.PaymentFailed.v1"
                    ),
                },
            ),
        }
        flows = {
            "domain_services": {},
            "process_managers": {
                "app.FulfillmentPM": {
                    "element_type": "PROCESS_MANAGER",
                    "fqn": "app.FulfillmentPM",
                    "name": "FulfillmentPM",
                    "handlers": {
                        "App.OrderPlaced.v1": {
                            "correlate": "order_id",
                            "start": True,
                            "end": False,
                            "methods": ["on_order_placed"],
                        },
                        "App.PaymentConfirmed.v1": {
                            "correlate": "order_id",
                            "start": False,
                            "end": False,
                            "methods": ["on_payment_confirmed"],
                        },
                        "App.PaymentFailed.v1": {
                            "correlate": "order_id",
                            "start": False,
                            "end": True,
                            "methods": ["on_payment_failed"],
                        },
                    },
                }
            },
            "subscribers": {},
        }
        return _ir(clusters=clusters, flows=flows)

    def test_pm_node_with_lifecycle(self, ir_with_pm):
        result = generate_event_flow_diagram(ir_with_pm)
        # Should have start and end annotations
        assert "start, end" in result
        assert "FulfillmentPM" in result

    def test_pm_start_edge_label(self, ir_with_pm):
        result = generate_event_flow_diagram(ir_with_pm)
        assert "evt_app_OrderPlaced -->|start|" in result

    def test_pm_end_edge_label(self, ir_with_pm):
        result = generate_event_flow_diagram(ir_with_pm)
        assert "evt_app_PaymentFailed -->|end|" in result

    def test_pm_plain_edge(self, ir_with_pm):
        result = generate_event_flow_diagram(ir_with_pm)
        assert "evt_app_PaymentConfirmed --> pm_app_FulfillmentPM" in result

    def test_pm_without_lifecycle(self):
        """PM with no start/end handlers should have plain label."""
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
        }
        flows = {
            "domain_services": {},
            "process_managers": {
                "app.SimplePM": {
                    "element_type": "PROCESS_MANAGER",
                    "fqn": "app.SimplePM",
                    "name": "SimplePM",
                    "handlers": {
                        "App.OrderPlaced.v1": {
                            "correlate": "order_id",
                            "start": False,
                            "end": False,
                            "methods": ["on_order_placed"],
                        },
                    },
                }
            },
            "subscribers": {},
        }
        result = generate_event_flow_diagram(_ir(clusters=clusters, flows=flows))
        assert "pm_app_SimplePM[SimplePM]" in result
        assert "-->|" not in result  # No edge labels


# ------------------------------------------------------------------
# Projectors
# ------------------------------------------------------------------


class TestProjectors:
    @pytest.fixture()
    def ir_with_projector(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                    "app.OrderCancelled": _event(
                        "app.OrderCancelled", "App.OrderCancelled.v1"
                    ),
                },
            ),
        }
        projections = {
            "app.OrderDashboard": {
                "projection": {
                    "fqn": "app.OrderDashboard",
                    "name": "OrderDashboard",
                },
                "projectors": {
                    "app.OrderDashboardProjector": {
                        "element_type": "PROJECTOR",
                        "fqn": "app.OrderDashboardProjector",
                        "name": "OrderDashboardProjector",
                        "projector_for": "app.OrderDashboard",
                        "handlers": {
                            "App.OrderPlaced.v1": ["on_order_placed"],
                            "App.OrderCancelled.v1": ["on_order_cancelled"],
                        },
                    }
                },
                "queries": {},
                "query_handlers": {},
            }
        }
        return _ir(clusters=clusters, projections=projections)

    def test_projector_node_with_projection_label(self, ir_with_projector):
        result = generate_event_flow_diagram(ir_with_projector)
        # Label should show "ProjectorName → ProjectionName"
        assert "OrderDashboardProjector" in result
        assert "OrderDashboard" in result

    def test_event_to_projector_edges(self, ir_with_projector):
        result = generate_event_flow_diagram(ir_with_projector)
        assert "evt_app_OrderPlaced --> proj_app_OrderDashboardProjector" in result
        assert "evt_app_OrderCancelled --> proj_app_OrderDashboardProjector" in result


# ------------------------------------------------------------------
# Full integration test with example IR
# ------------------------------------------------------------------


class TestFullIntegration:
    @pytest.fixture()
    def ordering_ir(self):
        """A small but complete ordering domain IR."""
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                commands={
                    "app.PlaceOrder": _command("app.PlaceOrder", "App.PlaceOrder.v1"),
                    "app.CancelOrder": _command(
                        "app.CancelOrder", "App.CancelOrder.v1"
                    ),
                },
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                    "app.OrderCancelled": _event(
                        "app.OrderCancelled", "App.OrderCancelled.v1"
                    ),
                },
                command_handlers={
                    "app.OrderCommandHandler": _command_handler(
                        "app.OrderCommandHandler",
                        {
                            "App.PlaceOrder.v1": ["handle_place"],
                            "App.CancelOrder.v1": ["handle_cancel"],
                        },
                    ),
                },
                event_handlers={
                    "app.OrderNotifier": _event_handler(
                        "app.OrderNotifier",
                        {"App.OrderPlaced.v1": ["send_confirmation"]},
                    ),
                },
            ),
            "app.Payment": _cluster(
                "app.Payment",
                commands={
                    "app.ConfirmPayment": _command(
                        "app.ConfirmPayment", "App.ConfirmPayment.v1"
                    ),
                },
                events={
                    "app.PaymentConfirmed": _event(
                        "app.PaymentConfirmed", "App.PaymentConfirmed.v1"
                    ),
                },
                command_handlers={
                    "app.PaymentHandler": _command_handler(
                        "app.PaymentHandler",
                        {"App.ConfirmPayment.v1": ["handle_confirm"]},
                    ),
                },
            ),
        }
        flows = {
            "domain_services": {},
            "process_managers": {
                "app.FulfillmentPM": {
                    "element_type": "PROCESS_MANAGER",
                    "fqn": "app.FulfillmentPM",
                    "name": "FulfillmentPM",
                    "handlers": {
                        "App.OrderPlaced.v1": {
                            "correlate": "order_id",
                            "start": True,
                            "end": False,
                            "methods": ["on_order_placed"],
                        },
                        "App.PaymentConfirmed.v1": {
                            "correlate": "order_id",
                            "start": False,
                            "end": True,
                            "methods": ["on_payment_confirmed"],
                        },
                    },
                }
            },
            "subscribers": {},
        }
        projections = {
            "app.OrderDashboard": {
                "projection": {
                    "fqn": "app.OrderDashboard",
                    "name": "OrderDashboard",
                },
                "projectors": {
                    "app.DashboardProjector": {
                        "element_type": "PROJECTOR",
                        "fqn": "app.DashboardProjector",
                        "name": "DashboardProjector",
                        "projector_for": "app.OrderDashboard",
                        "handlers": {
                            "App.OrderPlaced.v1": ["on_order_placed"],
                            "App.PaymentConfirmed.v1": ["on_payment_confirmed"],
                        },
                    }
                },
                "queries": {},
                "query_handlers": {},
            }
        }
        return _ir(clusters=clusters, flows=flows, projections=projections)

    def test_starts_with_flowchart(self, ordering_ir):
        result = generate_event_flow_diagram(ordering_ir)
        assert result.startswith("flowchart LR")

    def test_both_subgraphs_present(self, ordering_ir):
        result = generate_event_flow_diagram(ordering_ir)
        assert "subgraph app_Order" in result
        assert "subgraph app_Payment" in result

    def test_all_commands_present(self, ordering_ir):
        result = generate_event_flow_diagram(ordering_ir)
        assert "PlaceOrder" in result
        assert "CancelOrder" in result
        assert "ConfirmPayment" in result

    def test_all_events_present(self, ordering_ir):
        result = generate_event_flow_diagram(ordering_ir)
        assert "OrderPlaced" in result
        assert "OrderCancelled" in result
        assert "PaymentConfirmed" in result

    def test_pm_connected(self, ordering_ir):
        result = generate_event_flow_diagram(ordering_ir)
        assert "FulfillmentPM" in result
        assert "pm_app_FulfillmentPM" in result

    def test_projector_connected(self, ordering_ir):
        result = generate_event_flow_diagram(ordering_ir)
        assert "DashboardProjector" in result

    def test_event_handler_connected(self, ordering_ir):
        result = generate_event_flow_diagram(ordering_ir)
        assert "OrderNotifier" in result
        assert "evt_app_OrderPlaced --> eh_app_OrderNotifier" in result


# ------------------------------------------------------------------
# Per-cluster event flow
# ------------------------------------------------------------------


class TestClusterEventFlow:
    def test_empty_ir(self):
        result = generate_cluster_event_flow({}, "app.Order")
        assert result == "flowchart TD"

    def test_unknown_cluster(self):
        clusters = {"app.Order": _cluster("app.Order")}
        result = generate_cluster_event_flow(_ir(clusters=clusters), "app.Missing")
        assert result == "flowchart TD"

    def test_single_cluster_flow(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                commands={
                    "app.PlaceOrder": _command("app.PlaceOrder", "App.PlaceOrder.v1"),
                },
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
                command_handlers={
                    "app.OrderCH": _command_handler(
                        "app.OrderCH",
                        {"App.PlaceOrder.v1": ["handle_place"]},
                    ),
                },
            ),
        }
        result = generate_cluster_event_flow(_ir(clusters=clusters), "app.Order")
        assert result.startswith("flowchart TD")
        assert "subgraph app_Order" in result
        assert "PlaceOrder" in result
        assert "OrderPlaced" in result
        assert "cmd_app_PlaceOrder --> hdlr_app_OrderCH" in result
        assert "agg_app_Order --> evt_app_OrderPlaced" in result

    def test_does_not_include_other_clusters(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                commands={
                    "app.PlaceOrder": _command("app.PlaceOrder", "App.PlaceOrder.v1"),
                },
            ),
            "app.Payment": _cluster(
                "app.Payment",
                commands={
                    "app.ConfirmPayment": _command(
                        "app.ConfirmPayment", "App.ConfirmPayment.v1"
                    ),
                },
            ),
        }
        result = generate_cluster_event_flow(_ir(clusters=clusters), "app.Order")
        assert "Order" in result
        assert "Payment" not in result

    def test_does_not_include_downstream_consumers(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
                event_handlers={
                    "app.OrderNotifier": _event_handler(
                        "app.OrderNotifier",
                        {"App.OrderPlaced.v1": ["send_email"]},
                    ),
                },
            ),
        }
        flows = {
            "domain_services": {},
            "process_managers": {
                "app.FulfillmentPM": {
                    "element_type": "PROCESS_MANAGER",
                    "fqn": "app.FulfillmentPM",
                    "name": "FulfillmentPM",
                    "handlers": {
                        "App.OrderPlaced.v1": {
                            "correlate": "order_id",
                            "start": True,
                            "end": False,
                            "methods": ["on_order_placed"],
                        },
                    },
                }
            },
            "subscribers": {},
        }
        result = generate_cluster_event_flow(
            _ir(clusters=clusters, flows=flows), "app.Order"
        )
        # Cluster flow should NOT include event handlers or PMs
        assert "OrderNotifier" not in result
        assert "FulfillmentPM" not in result


# ------------------------------------------------------------------
# Downstream consumers diagram
# ------------------------------------------------------------------


class TestDownstreamConsumers:
    def test_empty_ir(self):
        result = generate_downstream_consumers_diagram({})
        assert result == "flowchart LR"

    def test_no_downstream(self):
        clusters = {"app.Order": _cluster("app.Order")}
        result = generate_downstream_consumers_diagram(_ir(clusters=clusters))
        assert result == "flowchart LR"

    def test_event_handlers_included(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
                event_handlers={
                    "app.OrderNotifier": _event_handler(
                        "app.OrderNotifier",
                        {"App.OrderPlaced.v1": ["send_email"]},
                    ),
                },
            ),
        }
        result = generate_downstream_consumers_diagram(_ir(clusters=clusters))
        assert "OrderNotifier" in result
        assert "evt_app_OrderPlaced --> eh_app_OrderNotifier" in result

    def test_process_managers_included(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
        }
        flows = {
            "domain_services": {},
            "process_managers": {
                "app.FulfillmentPM": {
                    "element_type": "PROCESS_MANAGER",
                    "fqn": "app.FulfillmentPM",
                    "name": "FulfillmentPM",
                    "handlers": {
                        "App.OrderPlaced.v1": {
                            "correlate": "order_id",
                            "start": True,
                            "end": False,
                            "methods": ["on_order_placed"],
                        },
                    },
                }
            },
            "subscribers": {},
        }
        result = generate_downstream_consumers_diagram(
            _ir(clusters=clusters, flows=flows)
        )
        assert "FulfillmentPM" in result
        assert "|start|" in result

    def test_projectors_included(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
        }
        projections = {
            "app.OrderDashboard": {
                "projection": {
                    "fqn": "app.OrderDashboard",
                    "name": "OrderDashboard",
                },
                "projectors": {
                    "app.DashboardProjector": {
                        "element_type": "PROJECTOR",
                        "fqn": "app.DashboardProjector",
                        "name": "DashboardProjector",
                        "projector_for": "app.OrderDashboard",
                        "handlers": {
                            "App.OrderPlaced.v1": ["on_order_placed"],
                        },
                    }
                },
                "queries": {},
                "query_handlers": {},
            }
        }
        result = generate_downstream_consumers_diagram(
            _ir(clusters=clusters, projections=projections)
        )
        assert "DashboardProjector" in result
        assert "evt_app_OrderPlaced --> proj_app_DashboardProjector" in result

    def test_does_not_include_cluster_command_flow(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                commands={
                    "app.PlaceOrder": _command("app.PlaceOrder", "App.PlaceOrder.v1"),
                },
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
                command_handlers={
                    "app.OrderCH": _command_handler(
                        "app.OrderCH",
                        {"App.PlaceOrder.v1": ["handle_place"]},
                    ),
                },
                event_handlers={
                    "app.OrderNotifier": _event_handler(
                        "app.OrderNotifier",
                        {"App.OrderPlaced.v1": ["send_email"]},
                    ),
                },
            ),
        }
        result = generate_downstream_consumers_diagram(_ir(clusters=clusters))
        # Should NOT include command flow
        assert "PlaceOrder" not in result
        assert "OrderCH" not in result
        # Should include event handler in a subgraph
        assert "OrderNotifier" in result
        assert "Event Handlers" in result

    def test_all_consumer_types_together(self):
        """All three consumer types appear with subgraphs in one diagram."""
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
                event_handlers={
                    "app.OrderNotifier": _event_handler(
                        "app.OrderNotifier",
                        {"App.OrderPlaced.v1": ["send_email"]},
                    ),
                },
            ),
        }
        flows = {
            "domain_services": {},
            "process_managers": {
                "app.FulfillmentPM": {
                    "element_type": "PROCESS_MANAGER",
                    "fqn": "app.FulfillmentPM",
                    "name": "FulfillmentPM",
                    "handlers": {
                        "App.OrderPlaced.v1": {
                            "correlate": "order_id",
                            "start": True,
                            "end": True,
                            "methods": ["on_order_placed"],
                        },
                    },
                }
            },
            "subscribers": {},
        }
        projections = {
            "app.Dashboard": {
                "projectors": {
                    "app.DashProjector": {
                        "element_type": "PROJECTOR",
                        "fqn": "app.DashProjector",
                        "name": "DashProjector",
                        "projector_for": "app.Dashboard",
                        "handlers": {
                            "App.OrderPlaced.v1": ["on_placed"],
                        },
                    }
                },
            }
        }
        result = generate_downstream_consumers_diagram(
            _ir(clusters=clusters, flows=flows, projections=projections)
        )
        # All three subgraphs present
        assert "Event Handlers" in result
        assert "Process Managers" in result
        assert "Projectors" in result
        # Event nodes pre-declared with short labels
        assert "OrderPlaced" in result
        # Lifecycle labels on PM edges
        assert "|start, end|" in result
        # Projector target label
        assert "Dashboard" in result

    def test_pm_plain_edge_in_downstream(self):
        """PM without lifecycle markers has plain edges."""
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
        }
        flows = {
            "domain_services": {},
            "process_managers": {
                "app.SimplePM": {
                    "element_type": "PROCESS_MANAGER",
                    "fqn": "app.SimplePM",
                    "name": "SimplePM",
                    "handlers": {
                        "App.OrderPlaced.v1": {
                            "correlate": "order_id",
                            "start": False,
                            "end": False,
                            "methods": ["on_placed"],
                        },
                    },
                }
            },
            "subscribers": {},
        }
        result = generate_downstream_consumers_diagram(
            _ir(clusters=clusters, flows=flows)
        )
        assert "SimplePM" in result
        assert "-->|" not in result  # No lifecycle labels
