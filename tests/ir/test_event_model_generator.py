"""Tests for the EventModeling slice-timeline generator.

Covers: generate_event_model_slice and generate_event_model_timeline —
the command -> aggregate -> event -> consumer slices, consumer
classification (read models vs automations), fact-event exclusion,
multi-slice ordering, and the empty/edge branches.
"""

import pytest

from protean.ir.generators.event_model import (
    element_fqns,
    generate_event_model_sections,
    generate_event_model_slice,
    generate_event_model_timeline,
    generate_slice_annotations,
    generate_slice_gwt,
    render_unmatched_annotations,
    slice_annotation_targets,
    unmatched_annotations,
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

    def test_slice_empty_cluster_still_renders_the_aggregate(self):
        # An empty cluster mapping is present, not absent, so the slice draws
        # the aggregate box, the same as the timeline does for that cluster.
        clusters: dict = {"app.Order": {}}
        result = generate_event_model_slice(_ir(clusters=clusters), "app.Order")
        assert result != "flowchart LR"
        assert "subgraph app_Order[Order]" in result
        assert "agg_app_Order[Order]" in result
        assert result == generate_event_model_timeline(_ir(clusters=clusters))


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
# Consumer lookup is indexed, not rescanned per event
# ------------------------------------------------------------------


class _CountingDict(dict):
    """A dict that counts how many times it is scanned with ``items()``."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scans = 0

    def items(self):
        self.scans += 1
        return super().items()


def _indexing_ir(event_count: int) -> dict:
    """One cluster with *event_count* events, plus a projector, EH and PM.

    ``projections`` and ``flows["process_managers"]`` are counting dicts, so
    a test can see how often the consumer side is scanned.
    """
    types = [f"App.OrderEvt{n}.v1" for n in range(event_count)]
    clusters = {
        "app.Order": _cluster(
            "app.Order",
            events={
                f"app.OrderEvt{n}": _event(f"app.OrderEvt{n}", types[n])
                for n in range(event_count)
            },
            event_handlers={
                "app.OrderEH": _event_handler(
                    "app.OrderEH", {t: ["on_evt"] for t in types}
                ),
            },
        ),
    }
    projections = _CountingDict(
        {
            "app.OrderView": _projection(
                "app.OrderView",
                {
                    "app.OrderProjector": _projector(
                        "app.OrderProjector",
                        "app.OrderView",
                        {t: ["on_evt"] for t in types},
                    ),
                },
            ),
        }
    )
    process_managers = _CountingDict(
        {"app.OrderPM": _process_manager("app.OrderPM", {t: ["on_evt"] for t in types})}
    )
    return _ir(
        clusters=clusters,
        projections=projections,
        flows={
            "domain_services": {},
            "process_managers": process_managers,
            "subscribers": {},
        },
    )


class TestConsumerIndexing:
    """Consumer lookup is indexed once per render, not rescanned per event.

    Without this, every event rescans every projection, cluster and process
    manager, so a domain with many events and many consumers costs
    events x consumers work on each `docs generate --type=event-model`.
    """

    @staticmethod
    def _scan_counts(ir: dict) -> tuple[int, int]:
        return (ir["projections"].scans, ir["flows"]["process_managers"].scans)

    @pytest.mark.parametrize(
        "render",
        [
            generate_event_model_timeline,
            lambda ir: generate_event_model_slice(ir, "app.Order"),
        ],
        ids=["timeline", "slice"],
    )
    def test_scan_count_does_not_grow_with_event_count(self, render):
        one, many = _indexing_ir(1), _indexing_ir(8)
        render(one)
        render(many)
        assert self._scan_counts(many) == self._scan_counts(one)

    def test_indexed_lookup_still_finds_every_consumer(self):
        result = generate_event_model_timeline(_indexing_ir(2))
        for n in range(2):
            evt = f"evt_app_OrderEvt{n}"
            assert f"{evt} --> rm_app_Order_app_OrderProjector" in result
            assert f"{evt} --> auto_app_Order_app_OrderEH" in result
            assert f"{evt} --> auto_app_Order_app_OrderPM" in result


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


# ------------------------------------------------------------------
# Slice Given-When-Then (generate_slice_gwt)
# ------------------------------------------------------------------


class TestSliceGwt:
    def test_ac1_given_when_then_in_order(self):
        """The GWT block names the aggregate and reads Given, When, Then."""
        result = generate_slice_gwt(_headline_ir(), "app.Order")
        assert "> **Given** Order" in result
        assert "> **When** PlaceOrder" in result
        assert "> **Then** OrderPlaced" in result
        # Given leads, When next, Then last.
        assert result.index("**Given**") < result.index("**When**")
        assert result.index("**When**") < result.index("**Then**")

    def test_ac2_one_command_one_event_headline(self):
        """The headline slice pairs the command and event on the When/Then lines."""
        result = generate_slice_gwt(_headline_ir(), "app.Order")
        # Exact block: three lines, one blockquote, in Given/When/Then order.
        assert (
            result == "> **Given** Order\n> **When** PlaceOrder\n> **Then** OrderPlaced"
        )

    def test_fact_event_excluded_from_then(self):
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
        result = generate_slice_gwt(_ir(clusters=clusters), "app.Order")
        assert "> **Then** OrderPlaced" in result
        assert "_OrderFact" not in result

    def test_only_fact_events_has_no_then_line(self):
        # events dict is non-empty, but every event is fact-filtered, so the
        # Then line is dropped: exercises the empty-after-filter branch.
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app._OrderFact": _event(
                        "app._OrderFact", "App._OrderFact.v1", is_fact_event=True
                    ),
                },
            ),
        }
        result = generate_slice_gwt(_ir(clusters=clusters), "app.Order")
        assert result == "> **Given** Order"
        assert "**Then**" not in result

    def test_commands_only_has_no_then_line(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                commands={
                    "app.PlaceOrder": _command("app.PlaceOrder", "App.PlaceOrder.v1"),
                },
            ),
        }
        result = generate_slice_gwt(_ir(clusters=clusters), "app.Order")
        assert "> **Given** Order" in result
        assert "> **When** PlaceOrder" in result
        # Negative: no results, so no Then line.
        assert "**Then**" not in result

    def test_events_only_has_no_when_line(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
        }
        result = generate_slice_gwt(_ir(clusters=clusters), "app.Order")
        assert "> **Given** Order" in result
        assert "> **Then** OrderPlaced" in result
        # Negative: no triggers, so no When line.
        assert "**When**" not in result

    def test_absent_cluster_returns_empty_string(self):
        assert generate_slice_gwt({}, "app.Order") == ""
        clusters = {"app.Order": _cluster("app.Order")}
        assert generate_slice_gwt(_ir(clusters=clusters), "app.Missing") == ""

    def test_empty_cluster_mapping_still_names_the_aggregate(self):
        # An empty cluster dict is present, not absent: derive the aggregate
        # name from the FQN and render only the Given line.
        clusters: dict = {"app.Order": {}}
        result = generate_slice_gwt(_ir(clusters=clusters), "app.Order")
        assert result == "> **Given** Order"

    def test_multi_command_multi_event_is_sorted(self):
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
            ),
        }
        result = generate_slice_gwt(_ir(clusters=clusters), "app.Order")
        assert "> **When** CancelOrder, PlaceOrder" in result
        assert "> **Then** OrderCancelled, OrderPlaced" in result

    def test_same_short_name_from_two_modules_is_listed_twice(self):
        # The diagram draws one node per FQN, so the GWT must list both
        # entries too. Collapsing them by short name would leave the prose
        # saying "one command, one event" while the diagram shows two nodes.
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                commands={
                    "app.sales.PlaceOrder": _command(
                        "app.sales.PlaceOrder", "App.Sales.PlaceOrder.v1"
                    ),
                    "app.trade.PlaceOrder": _command(
                        "app.trade.PlaceOrder", "App.Trade.PlaceOrder.v1"
                    ),
                },
                events={
                    "app.sales.OrderPlaced": _event(
                        "app.sales.OrderPlaced", "App.Sales.OrderPlaced.v1"
                    ),
                    "app.trade.OrderPlaced": _event(
                        "app.trade.OrderPlaced", "App.Trade.OrderPlaced.v1"
                    ),
                },
            ),
        }
        ir = _ir(clusters=clusters)
        result = generate_slice_gwt(ir, "app.Order")
        assert "> **When** PlaceOrder, PlaceOrder" in result
        assert "> **Then** OrderPlaced, OrderPlaced" in result
        # The GWT counts match the diagram's node counts.
        diagram = generate_event_model_slice(ir, "app.Order")
        assert diagram.count("[/PlaceOrder/]") == 2
        assert diagram.count("([OrderPlaced])") == 2

    def test_output_is_deterministic(self):
        # Insert keys in reverse-sorted order so a dropped ``sorted(...)`` would
        # produce insertion-order text and break the exact-match assertion.
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                commands={
                    "app.PlaceOrder": _command("app.PlaceOrder", "App.PlaceOrder.v1"),
                    "app.CancelOrder": _command(
                        "app.CancelOrder", "App.CancelOrder.v1"
                    ),
                },
            ),
        }
        ir = _ir(clusters=clusters)
        first = generate_slice_gwt(ir, "app.Order")
        assert first == generate_slice_gwt(ir, "app.Order")
        assert first == "> **Given** Order\n> **When** CancelOrder, PlaceOrder"


# ------------------------------------------------------------------
# Annotation match set (element_fqns / slice_annotation_targets)
# ------------------------------------------------------------------


class TestElementFqns:
    def test_match_set_covers_aggregate_command_event_and_consumers(self):
        result = element_fqns(_headline_ir())
        # Aggregate, command, event, and the projector that consumes the event.
        assert result == {
            "app.Order",
            "app.PlaceOrder",
            "app.OrderPlaced",
            "app.OrderSummaryProjector",
        }

    def test_match_set_includes_event_handlers_and_process_managers(self):
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
        result = element_fqns(_ir(clusters=clusters, flows=flows))
        assert "app.OrderNotifier" in result
        assert "app.FulfillmentPM" in result

    def test_fact_event_is_not_in_the_match_set(self):
        # A fact event is filtered from the diagram, so it draws no node and
        # is not a valid annotation target: a note on it is reported unmatched.
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
        result = element_fqns(_ir(clusters=clusters))
        assert "app.OrderPlaced" in result
        assert "app._OrderFact" not in result

    def test_empty_cluster_contributes_only_its_aggregate(self):
        result = element_fqns(_ir(clusters={"app.Order": {}}))
        assert result == {"app.Order"}

    def test_event_without_type_adds_no_consumers_to_the_match_set(self):
        # An empty event type is never a key in a handlers map, so the event
        # itself is a target but no consumer is pulled into the slice, the
        # same skip the diagram makes.
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={"app.OrderPlaced": _event("app.OrderPlaced", "")},
                event_handlers={
                    "app.OrderNotifier": _event_handler(
                        "app.OrderNotifier",
                        {"App.OrderPlaced.v1": ["send_email"]},
                    ),
                },
            ),
        }
        result = element_fqns(_ir(clusters=clusters))
        assert result == {"app.Order", "app.OrderPlaced"}

    def test_slice_targets_absent_cluster_is_empty(self):
        assert slice_annotation_targets(_ir(), "app.Missing") == set()

    def test_slice_targets_match_the_slice_nodes(self):
        targets = slice_annotation_targets(_headline_ir(), "app.Order")
        assert targets == {
            "app.Order",
            "app.PlaceOrder",
            "app.OrderPlaced",
            "app.OrderSummaryProjector",
        }


# ------------------------------------------------------------------
# Unmatched annotations report
# ------------------------------------------------------------------


class TestUnmatchedAnnotations:
    def test_matched_key_is_not_reported(self):
        annotations = {"app.Order": {"note": "The fulfillment boundary."}}
        assert unmatched_annotations(_headline_ir(), annotations) == []

    def test_unmatched_key_is_reported(self):
        annotations = {"app.Ghost": {"note": "Orphaned by a rename."}}
        assert unmatched_annotations(_headline_ir(), annotations) == ["app.Ghost"]

    def test_unmatched_keys_are_sorted(self):
        annotations = {
            "app.Zebra": {"note": "z"},
            "app.Apple": {"note": "a"},
        }
        assert unmatched_annotations(_headline_ir(), annotations) == [
            "app.Apple",
            "app.Zebra",
        ]

    def test_empty_annotations_report_nothing(self):
        assert unmatched_annotations(_headline_ir(), {}) == []

    def test_fact_event_key_is_reported_unmatched(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app._OrderFact": _event(
                        "app._OrderFact", "App._OrderFact.v1", is_fact_event=True
                    ),
                },
            ),
        }
        annotations = {"app._OrderFact": {"note": "Filtered from the model."}}
        assert unmatched_annotations(_ir(clusters=clusters), annotations) == [
            "app._OrderFact"
        ]

    def test_render_report_lists_every_key(self):
        report = render_unmatched_annotations(["app.Apple", "app.Zebra"])
        assert report.startswith("## Unmatched annotations")
        assert "- `app.Apple`" in report
        assert "- `app.Zebra`" in report

    def test_render_report_empty_for_no_keys(self):
        assert render_unmatched_annotations([]) == ""

    def test_render_report_collapses_newlines_in_a_key(self):
        # A newline in a key (a valid but pathological TOML key) must not break
        # the list or forge a heading: it is collapsed to a single line.
        report = render_unmatched_annotations(["bad\n## Forged\nx"])
        assert report.endswith("- `bad ## Forged x`")
        assert "\n## Forged" not in report

    def test_render_report_fences_backticks_in_a_key(self):
        # A backtick in a key (valid in a TOML quoted key) must not cut the
        # code span short: the fence grows past the longest run inside.
        report = render_unmatched_annotations(["app.`Odd`"])
        assert report.endswith("- `` app.`Odd` ``")

    def test_render_report_fences_a_backtick_run_in_a_key(self):
        # The fence is one backtick longer than the longest run in the key.
        report = render_unmatched_annotations(["a``b```c"])
        assert report.endswith("- ````a``b```c````")

    def test_render_report_renders_an_empty_key(self):
        # An empty key still needs a well-formed span, so it is padded.
        report = render_unmatched_annotations([""])
        assert report.endswith("- `  `")


# ------------------------------------------------------------------
# Per-slice annotation rendering (generate_slice_annotations)
# ------------------------------------------------------------------


class TestSliceAnnotations:
    def test_empty_annotations_render_nothing(self):
        # The no-op path: no annotations means an empty string, which keeps
        # the no-file baseline byte-identical to the pre-annotation render.
        assert generate_slice_annotations(_headline_ir(), "app.Order", {}) == ""

    def test_aggregate_note_renders_in_its_slice(self):
        annotations = {"app.Order": {"note": "The fulfillment boundary."}}
        result = generate_slice_annotations(_headline_ir(), "app.Order", annotations)
        assert result == "> **Note:** The fulfillment boundary."

    def test_owner_renders_when_present(self):
        annotations = {
            "app.Order": {"note": "The fulfillment boundary.", "owner": "Fulfillment"}
        }
        result = generate_slice_annotations(_headline_ir(), "app.Order", annotations)
        assert result == (
            "> **Note:** The fulfillment boundary.\n>\n> **Owner:** Fulfillment"
        )

    def test_multiline_note_is_one_blockquote(self):
        annotations = {
            "app.Order": {"note": "First line.\n\nSecond paragraph."},
        }
        result = generate_slice_annotations(_headline_ir(), "app.Order", annotations)
        assert result == ("> **Note:** First line.\n>\n> Second paragraph.")

    def test_note_keyed_by_command_renders_in_the_slice(self):
        annotations = {"app.PlaceOrder": {"note": "Triggered by checkout."}}
        result = generate_slice_annotations(_headline_ir(), "app.Order", annotations)
        assert result == "> **Note:** Triggered by checkout."

    def test_note_keyed_by_event_renders_in_the_slice(self):
        annotations = {"app.OrderPlaced": {"note": "Gates the shipment slice."}}
        result = generate_slice_annotations(_headline_ir(), "app.Order", annotations)
        assert result == "> **Note:** Gates the shipment slice."

    def test_unmatched_key_renders_nothing_in_the_slice(self):
        annotations = {"app.Ghost": {"note": "Orphaned."}}
        assert (
            generate_slice_annotations(_headline_ir(), "app.Order", annotations) == ""
        )

    def test_multiple_notes_render_in_sorted_fqn_order(self):
        annotations = {
            "app.PlaceOrder": {"note": "The command."},
            "app.Order": {"note": "The aggregate."},
        }
        result = generate_slice_annotations(_headline_ir(), "app.Order", annotations)
        # Sorted by FQN: app.Order before app.PlaceOrder.
        assert result == ("> **Note:** The aggregate.\n\n> **Note:** The command.")

    def test_note_does_not_leak_into_a_sibling_slice(self):
        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
            "app.Shipment": _cluster(
                "app.Shipment",
                events={
                    "app.OrderShipped": _event(
                        "app.OrderShipped", "App.OrderShipped.v1"
                    ),
                },
            ),
        }
        ir = _ir(clusters=clusters)
        annotations = {"app.Order": {"note": "The fulfillment boundary."}}
        assert generate_slice_annotations(ir, "app.Order", annotations) != ""
        assert generate_slice_annotations(ir, "app.Shipment", annotations) == ""

    def test_note_keyed_by_a_drawn_consumer_renders_in_the_slice(self):
        # app.OrderSummaryProjector is a consumer drawn in the app.Order slice.
        annotations = {
            "app.OrderSummaryProjector": {"note": "Feeds the ops dashboard."}
        }
        result = generate_slice_annotations(_headline_ir(), "app.Order", annotations)
        assert result == "> **Note:** Feeds the ops dashboard."

    def test_owner_with_embedded_newline_stays_quoted(self):
        # A TOML string may carry newlines. Every owner line must be
        # `> `-prefixed so it cannot forge a heading below the quote.
        annotations = {
            "app.Order": {
                "note": "The boundary.",
                "owner": "Alice\n## Forged Heading",
            }
        }
        result = generate_slice_annotations(_headline_ir(), "app.Order", annotations)
        assert result == (
            "> **Note:** The boundary.\n>\n> **Owner:** Alice\n> ## Forged Heading"
        )
        # No line escapes the blockquote.
        assert all(line.startswith(">") for line in result.splitlines())


# ------------------------------------------------------------------
# Whole-model rendering (generate_event_model_sections)
# ------------------------------------------------------------------


class TestEventModelSections:
    def test_sections_match_the_per_slice_functions(self):
        ir = _headline_ir()
        annotations = {"app.Order": {"note": "The fulfillment boundary."}}
        sections = generate_event_model_sections(ir, annotations)
        assert [section.cluster_fqn for section in sections] == ["app.Order"]
        section = sections[0]
        assert section.diagram == generate_event_model_slice(ir, "app.Order")
        assert section.gwt == generate_slice_gwt(ir, "app.Order")
        assert section.notes == generate_slice_annotations(ir, "app.Order", annotations)

    def test_sections_are_sorted_by_cluster_fqn(self):
        clusters = {
            "app.Shipment": _cluster("app.Shipment"),
            "app.Order": _cluster("app.Order"),
        }
        sections = generate_event_model_sections(_ir(clusters=clusters), {})
        assert [section.cluster_fqn for section in sections] == [
            "app.Order",
            "app.Shipment",
        ]

    def test_no_clusters_renders_no_sections(self):
        assert generate_event_model_sections(_ir(), {}) == []

    def test_empty_cluster_still_gets_a_section(self):
        # An empty cluster is present, not absent: the slice still draws the
        # aggregate box, so it still gets a section.
        sections = generate_event_model_sections(_ir(clusters={"app.Order": {}}), {})
        assert [section.cluster_fqn for section in sections] == ["app.Order"]
        assert sections[0].diagram == generate_event_model_slice(
            _ir(clusters={"app.Order": {}}), "app.Order"
        )

    def test_no_annotations_leaves_every_section_noteless(self):
        sections = generate_event_model_sections(_headline_ir(), {})
        assert [section.notes for section in sections] == [""]

    def test_consumer_indexes_are_built_once_for_the_whole_render(self, monkeypatch):
        # The point of this entry point: a render costs one pass over the
        # projections and flows, not one per slice.
        from protean.ir.generators import event_model

        calls = {"read_models": 0, "automations": 0}

        real_read_model_index = event_model._read_model_index
        real_automation_index = event_model._automation_index

        def counted_read_model_index(ir):
            calls["read_models"] += 1
            return real_read_model_index(ir)

        def counted_automation_index(ir):
            calls["automations"] += 1
            return real_automation_index(ir)

        monkeypatch.setattr(event_model, "_read_model_index", counted_read_model_index)
        monkeypatch.setattr(event_model, "_automation_index", counted_automation_index)

        clusters = {
            "app.Order": _cluster(
                "app.Order",
                events={
                    "app.OrderPlaced": _event("app.OrderPlaced", "App.OrderPlaced.v1"),
                },
            ),
            "app.Shipment": _cluster("app.Shipment"),
            "app.Payment": _cluster("app.Payment"),
        }
        annotations = {"app.Order": {"note": "The boundary."}}
        sections = event_model.generate_event_model_sections(
            _ir(clusters=clusters), annotations
        )

        assert len(sections) == 3
        assert calls == {"read_models": 1, "automations": 1}
