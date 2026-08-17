"""Tests for the EventModeling slice-timeline generator.

Covers: generate_event_model_slice and generate_event_model_timeline —
the command -> aggregate -> event -> consumer slices, consumer
classification (read models vs automations), fact-event exclusion,
multi-slice ordering, and the empty/edge branches.
"""

import pytest

from protean.ir.generators.event_model import (
    generate_event_model_slice,
    generate_event_model_timeline,
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


def _event_handler(fqn: str, handlers: dict) -> dict:
    return {
        "element_type": "EVENT_HANDLER",
        "fqn": fqn,
        "name": fqn.rsplit(".", 1)[-1],
        "handlers": handlers,
        "subscription": {"config": {}, "profile": None, "type": None},
    }


def _process_manager(fqn: str, handlers: dict) -> dict:
    # Real PM IR keys each __type__ to a {methods, start, end, correlate} dict
    # (unlike event handlers / projectors, which key to a plain method list).
    # Accept a bare method list for brevity and wrap it in that shape.
    normalized: dict = {}
    for type_key, info in handlers.items():
        if isinstance(info, list):
            info = {"methods": info, "start": False, "end": False}
        normalized[type_key] = info
    return {
        "element_type": "PROCESS_MANAGER",
        "fqn": fqn,
        "name": fqn.rsplit(".", 1)[-1],
        "handlers": normalized,
    }


def _projection(projection_fqn: str, projectors: dict) -> dict:
    return {
        "projection": {
            "fqn": projection_fqn,
            "name": projection_fqn.rsplit(".", 1)[-1],
        },
        "projectors": projectors,
        "queries": {},
        "query_handlers": {},
    }


def _projector(fqn: str, projector_for: str, handlers: dict) -> dict:
    return {
        "element_type": "PROJECTOR",
        "fqn": fqn,
        "name": fqn.rsplit(".", 1)[-1],
        "projector_for": projector_for,
        "handlers": handlers,
    }


# ------------------------------------------------------------------
# Empty / missing data
# ------------------------------------------------------------------


class TestEmptyIR:
    def test_timeline_empty_clusters(self):
        assert generate_event_model_timeline(_ir()) == "flowchart LR"

    def test_timeline_missing_clusters_key(self):
        assert generate_event_model_timeline({}) == "flowchart LR"

    def test_slice_empty_ir(self):
        assert generate_event_model_slice({}, "app.Order") == "flowchart LR"

    def test_slice_unknown_cluster(self):
        clusters = {"app.Order": _cluster("app.Order")}
        result = generate_event_model_slice(_ir(clusters=clusters), "app.Missing")
        assert result == "flowchart LR"


# ------------------------------------------------------------------
# AC1: the headline slice (command -> event -> read model)
# ------------------------------------------------------------------


def _headline_ir() -> dict:
    """One command, one event, one projector that reads it."""
    clusters = {
        "app.Order": _cluster(
            "app.Order",
            commands={
                "app.PlaceOrder": _command("app.PlaceOrder", "App.PlaceOrder.v1"),
            },
            events={
                "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
            },
        ),
    }
    projections = {
        "app.OrderSummary": _projection(
            "app.OrderSummary",
            {
                "app.OrderSummaryProjector": _projector(
                    "app.OrderSummaryProjector",
                    "app.OrderSummary",
                    {"App.OrderPlaced.v1": ["on_order_placed"]},
                ),
            },
        ),
    }
    return _ir(clusters=clusters, projections=projections)


class TestHeadlineSlice:
    def test_mermaid_renders_all_nodes(self):
        result = generate_event_model_slice(_headline_ir(), "app.Order")
        assert result.startswith("flowchart LR")
        # Command (parallelogram), aggregate, event (stadium), read model
        assert "cmd_app_PlaceOrder[/PlaceOrder/]" in result
        assert "agg_app_Order[Order]" in result
        assert "evt_app_OrderPlaced([OrderPlaced])" in result
        # Read model: cylinder shape [(...)]
        assert (
            "rm_app_Order_app_OrderSummaryProjector"
            "[(OrderSummaryProjector → OrderSummary)]" in result
        )

    def test_mermaid_edges_left_to_right(self):
        result = generate_event_model_slice(_headline_ir(), "app.Order")
        assert "cmd_app_PlaceOrder --> agg_app_Order" in result
        assert "agg_app_Order --> evt_app_OrderPlaced" in result
        assert (
            "evt_app_OrderPlaced --> rm_app_Order_app_OrderSummaryProjector" in result
        )

    def test_timeline_contains_the_slice(self):
        result = generate_event_model_timeline(_headline_ir())
        assert "subgraph app_Order[Order]" in result
        assert "cmd_app_PlaceOrder --> agg_app_Order" in result
        assert (
            "evt_app_OrderPlaced --> rm_app_Order_app_OrderSummaryProjector" in result
        )


# ------------------------------------------------------------------
# Consumer classification: read models vs automations
# ------------------------------------------------------------------


class TestConsumerClassification:
    def test_event_handler_and_pm_render_as_automations(self):
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
                "app.FulfillmentPM": _process_manager(
                    "app.FulfillmentPM",
                    {"App.OrderPlaced.v1": ["on_order_placed"]},
                ),
            },
            "subscribers": {},
        }
        result = generate_event_model_slice(
            _ir(clusters=clusters, flows=flows), "app.Order"
        )
        # Automations: hexagon shape {{...}}
        assert "auto_app_Order_app_OrderNotifier{{OrderNotifier}}" in result
        assert "auto_app_Order_app_FulfillmentPM{{FulfillmentPM}}" in result
        assert "evt_app_OrderPlaced --> auto_app_Order_app_OrderNotifier" in result
        assert "evt_app_OrderPlaced --> auto_app_Order_app_FulfillmentPM" in result
        # An automation is not a read model
        assert "rm_app_Order" not in result

    def test_cross_cluster_event_handler_is_found(self):
        """An event handler in another cluster still consumes the event."""
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
            "app.Shipping": _cluster(
                "app.Shipping",
                event_handlers={
                    "app.ShippingHandler": _event_handler(
                        "app.ShippingHandler",
                        {"App.OrderPlaced.v1": ["schedule_shipment"]},
                    ),
                },
            ),
        }
        result = generate_event_model_slice(_ir(clusters=clusters), "app.Order")
        assert "auto_app_Order_app_ShippingHandler{{ShippingHandler}}" in result
        assert "evt_app_OrderPlaced --> auto_app_Order_app_ShippingHandler" in result

    def test_event_without_consumers_still_renders_the_chain(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                commands={
                    "app.PlaceOrder": _command("app.PlaceOrder", "App.PlaceOrder.v1"),
                },
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
        }
        result = generate_event_model_slice(_ir(clusters=clusters), "app.Order")
        assert "cmd_app_PlaceOrder --> agg_app_Order" in result
        assert "agg_app_Order --> evt_app_OrderPlaced" in result
        # No consumer nodes drawn
        assert "rm_app_Order" not in result
        assert "auto_app_Order" not in result

    def test_projector_consuming_two_events_is_drawn_once(self):
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
            "app.OrderSummary": _projection(
                "app.OrderSummary",
                {
                    "app.OrderSummaryProjector": _projector(
                        "app.OrderSummaryProjector",
                        "app.OrderSummary",
                        {
                            "App.OrderPlaced.v1": ["on_placed"],
                            "App.OrderCancelled.v1": ["on_cancelled"],
                        },
                    ),
                },
            ),
        }
        result = generate_event_model_slice(
            _ir(clusters=clusters, projections=projections), "app.Order"
        )
        # The read-model node is declared exactly once even though two
        # events feed it.
        node_decls = result.count(
            "rm_app_Order_app_OrderSummaryProjector[(OrderSummaryProjector → OrderSummary)]"
        )
        assert node_decls == 1
        # But both events draw an edge to it.
        assert (
            "evt_app_OrderPlaced --> rm_app_Order_app_OrderSummaryProjector" in result
        )
        assert (
            "evt_app_OrderCancelled --> rm_app_Order_app_OrderSummaryProjector"
            in result
        )

    def test_projector_without_projection_label_renders_bare(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
        }
        projections = {
            "app.OrphanGroup": _projection(
                "app.OrphanGroup",
                {
                    "app.OrphanProjector": _projector(
                        "app.OrphanProjector",
                        "",  # no projector_for target
                        {"App.OrderPlaced.v1": ["on_placed"]},
                    ),
                },
            ),
        }
        result = generate_event_model_slice(
            _ir(clusters=clusters, projections=projections), "app.Order"
        )
        assert "rm_app_Order_app_OrphanProjector[(OrphanProjector)]" in result
        assert "→" not in result


# ------------------------------------------------------------------
# Consumer shapes and process-manager lifecycle
# ------------------------------------------------------------------


class TestConsumerShapesAndLifecycle:
    def test_read_model_and_automation_have_distinct_shapes(self):
        """A read model is a cylinder; an automation is a hexagon."""
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
        projections = {
            "app.OrderSummary": _projection(
                "app.OrderSummary",
                {
                    "app.OrderSummaryProjector": _projector(
                        "app.OrderSummaryProjector",
                        "app.OrderSummary",
                        {"App.OrderPlaced.v1": ["on_placed"]},
                    ),
                },
            ),
        }
        result = generate_event_model_slice(
            _ir(clusters=clusters, projections=projections), "app.Order"
        )
        # Read model: cylinder [(...)]
        assert (
            "rm_app_Order_app_OrderSummaryProjector[(OrderSummaryProjector → OrderSummary)]"
            in result
        )
        # Automation: hexagon {{...}} — a different shape from the read model
        assert "auto_app_Order_app_OrderNotifier{{OrderNotifier}}" in result

    def test_process_manager_start_end_lifecycle_is_rendered(self):
        """A PM's start/end shows in its label and on the edge from the event."""
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                    "app.OrderShipped": _event(
                        "app.OrderShipped", "App.OrderShipped.v1"
                    ),
                },
            ),
        }
        flows = {
            "domain_services": {},
            "process_managers": {
                "app.FulfillmentPM": _process_manager(
                    "app.FulfillmentPM",
                    {
                        "App.OrderPlaced.v1": {
                            "methods": ["on_order_placed"],
                            "start": True,
                            "end": False,
                        },
                        "App.OrderShipped.v1": {
                            "methods": ["on_order_shipped"],
                            "start": False,
                            "end": True,
                        },
                    },
                ),
            },
            "subscribers": {},
        }
        result = generate_event_model_slice(
            _ir(clusters=clusters, flows=flows), "app.Order"
        )
        # The node label carries the whole lifecycle across both handlers.
        # The parentheses are Mermaid-special, so the label is double-quoted.
        assert (
            'auto_app_Order_app_FulfillmentPM{{"FulfillmentPM (start, end)"}}' in result
        )
        # Each triggering event edge is labelled with its own lifecycle role.
        assert (
            "evt_app_OrderPlaced -->|start| auto_app_Order_app_FulfillmentPM" in result
        )
        assert (
            "evt_app_OrderShipped -->|end| auto_app_Order_app_FulfillmentPM" in result
        )

    def test_process_manager_without_lifecycle_uses_a_plain_edge(self):
        """A PM with no start/end draws a bare label and an unlabelled edge."""
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
                "app.FulfillmentPM": _process_manager(
                    "app.FulfillmentPM",
                    {"App.OrderPlaced.v1": ["on_order_placed"]},
                ),
            },
            "subscribers": {},
        }
        result = generate_event_model_slice(
            _ir(clusters=clusters, flows=flows), "app.Order"
        )
        assert "auto_app_Order_app_FulfillmentPM{{FulfillmentPM}}" in result
        assert "evt_app_OrderPlaced --> auto_app_Order_app_FulfillmentPM" in result
        # No lifecycle edge label.
        assert "-->|" not in result


# ------------------------------------------------------------------
# Consumers that exist but do not handle the slice's events
# ------------------------------------------------------------------


class TestNonMatchingConsumers:
    def test_projector_not_handling_the_event_is_skipped(self):
        """A projector whose handlers miss the event is not drawn."""
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
        }
        projections = {
            "app.OtherSummary": _projection(
                "app.OtherSummary",
                {
                    "app.OtherProjector": _projector(
                        "app.OtherProjector",
                        "app.OtherSummary",
                        {"App.SomethingElse.v1": ["on_something_else"]},
                    ),
                },
            ),
        }
        result = generate_event_model_slice(
            _ir(clusters=clusters, projections=projections), "app.Order"
        )
        assert "agg_app_Order --> evt_app_OrderPlaced" in result
        assert "OtherProjector" not in result
        assert "rm_app_Order" not in result

    def test_event_handler_and_pm_not_handling_the_event_are_skipped(self):
        """An event handler and a PM whose handlers miss the event are not drawn."""
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
                event_handlers={
                    "app.OtherHandler": _event_handler(
                        "app.OtherHandler",
                        {"App.SomethingElse.v1": ["react"]},
                    ),
                },
            ),
        }
        flows = {
            "domain_services": {},
            "process_managers": {
                "app.OtherPM": _process_manager(
                    "app.OtherPM",
                    {"App.SomethingElse.v1": ["react"]},
                ),
            },
            "subscribers": {},
        }
        result = generate_event_model_slice(
            _ir(clusters=clusters, flows=flows), "app.Order"
        )
        assert "agg_app_Order --> evt_app_OrderPlaced" in result
        assert "OtherHandler" not in result
        assert "OtherPM" not in result
        assert "auto_app_Order" not in result

    def test_event_without_type_matches_no_consumers(self):
        """An event with an empty ``__type__`` renders but matches nothing.

        An empty event type is never a key in any ``handlers`` map, so the
        membership check in both consumer lookups skips every projector,
        event handler, and process manager even when all three are present.
        """
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", ""),
                },
                event_handlers={
                    "app.OrderNotifier": _event_handler(
                        "app.OrderNotifier",
                        {"App.OrderPlaced.v1": ["send_email"]},
                    ),
                },
            ),
        }
        projections = {
            "app.OrderSummary": _projection(
                "app.OrderSummary",
                {
                    "app.OrderSummaryProjector": _projector(
                        "app.OrderSummaryProjector",
                        "app.OrderSummary",
                        {"App.OrderPlaced.v1": ["on_order_placed"]},
                    ),
                },
            ),
        }
        flows = {
            "domain_services": {},
            "process_managers": {
                "app.FulfillmentPM": _process_manager(
                    "app.FulfillmentPM",
                    {"App.OrderPlaced.v1": ["on_order_placed"]},
                ),
            },
            "subscribers": {},
        }
        result = generate_event_model_slice(
            _ir(clusters=clusters, flows=flows, projections=projections), "app.Order"
        )
        # The event node still renders...
        assert "evt_app_OrderPlaced([OrderPlaced])" in result
        # ...but no consumer is matched.
        assert "rm_app_Order" not in result
        assert "auto_app_Order" not in result


# ------------------------------------------------------------------
# Fact events excluded
# ------------------------------------------------------------------


class TestFactEvents:
    def test_fact_event_absent_from_slice(self):
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
        result = generate_event_model_slice(_ir(clusters=clusters), "app.Order")
        assert "OrderPlaced" in result
        assert "_OrderFact" not in result


# ------------------------------------------------------------------
# Multi-slice ordering / determinism
# ------------------------------------------------------------------


class TestMultiSlice:
    @pytest.fixture()
    def two_cluster_ir(self):
        clusters = {
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
            ),
            "app.Order": _cluster(
                "app.Order",
                commands={
                    "app.PlaceOrder": _command("app.PlaceOrder", "App.PlaceOrder.v1"),
                },
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
        }
        return _ir(clusters=clusters)

    def test_two_slices_rendered(self, two_cluster_ir):
        result = generate_event_model_timeline(two_cluster_ir)
        assert "subgraph app_Order[Order]" in result
        assert "subgraph app_Payment[Payment]" in result

    def test_slices_in_sorted_order(self, two_cluster_ir):
        result = generate_event_model_timeline(two_cluster_ir)
        # app.Order sorts before app.Payment regardless of insertion order.
        assert result.index("subgraph app_Order") < result.index("subgraph app_Payment")

    def test_output_is_deterministic(self, two_cluster_ir):
        first = generate_event_model_timeline(two_cluster_ir)
        second = generate_event_model_timeline(two_cluster_ir)
        assert first == second


# ------------------------------------------------------------------
# Edge clusters: commands-only, events-only
# ------------------------------------------------------------------


class TestEdgeClusters:
    def test_commands_without_events(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                commands={
                    "app.PlaceOrder": _command("app.PlaceOrder", "App.PlaceOrder.v1"),
                },
            ),
        }
        result = generate_event_model_slice(_ir(clusters=clusters), "app.Order")
        assert "cmd_app_PlaceOrder --> agg_app_Order" in result
        # No event edges
        assert "--> evt_" not in result

    def test_events_without_commands(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
        }
        result = generate_event_model_slice(_ir(clusters=clusters), "app.Order")
        assert "agg_app_Order --> evt_app_OrderPlaced" in result
        # No command edges
        assert "--> agg_app_Order" not in result
