"""Tests for the handler wiring diagram generator."""

from __future__ import annotations

import pytest

from protean.ir.generators.handlers import (
    generate_cluster_command_handler_diagram,
    generate_command_handler_diagram,
    generate_event_handler_diagram,
    generate_handler_wiring_diagram,
    generate_process_manager_diagram,
    generate_projector_diagram,
    generate_single_projector_diagram,
    generate_subscriber_diagram,
)


# ---------------------------------------------------------------------------
# Helpers — composable IR builders
# ---------------------------------------------------------------------------


def _command(
    fqn: str,
    *,
    type_str: str = "",
    version: int = 1,
) -> dict:
    name = fqn.rsplit(".", 1)[-1]
    return {
        fqn: {
            "__type__": type_str or f"Test.{name}.v{version}",
            "__version__": version,
            "element_type": "COMMAND",
            "fields": {},
            "fqn": fqn,
            "name": name,
        }
    }


def _event(
    fqn: str,
    *,
    type_str: str = "",
    version: int = 1,
    published: bool = False,
    is_fact_event: bool = False,
) -> dict:
    name = fqn.rsplit(".", 1)[-1]
    return {
        fqn: {
            "__type__": type_str or f"Test.{name}.v{version}",
            "__version__": version,
            "element_type": "EVENT",
            "fields": {},
            "fqn": fqn,
            "is_fact_event": is_fact_event,
            "name": name,
            "published": published,
        }
    }


def _command_handler(fqn: str, *, handlers: dict | None = None) -> dict:
    name = fqn.rsplit(".", 1)[-1]
    return {
        fqn: {
            "element_type": "COMMAND_HANDLER",
            "fqn": fqn,
            "handlers": handlers or {},
            "name": name,
        }
    }


def _event_handler(fqn: str, *, handlers: dict | None = None) -> dict:
    name = fqn.rsplit(".", 1)[-1]
    return {
        fqn: {
            "element_type": "EVENT_HANDLER",
            "fqn": fqn,
            "handlers": handlers or {},
            "name": name,
        }
    }


def _cluster(
    fqn: str,
    *,
    commands: dict | None = None,
    events: dict | None = None,
    command_handlers: dict | None = None,
    event_handlers: dict | None = None,
) -> dict:
    name = fqn.rsplit(".", 1)[-1]
    return {
        fqn: {
            "aggregate": {
                "element_type": "AGGREGATE",
                "fields": {},
                "fqn": fqn,
                "name": name,
                "options": {},
                "invariants": {"pre": [], "post": []},
            },
            "commands": commands or {},
            "events": events or {},
            "command_handlers": command_handlers or {},
            "event_handlers": event_handlers or {},
            "entities": {},
            "value_objects": {},
        }
    }


def _process_manager(fqn: str, *, handlers: dict | None = None) -> dict:
    name = fqn.rsplit(".", 1)[-1]
    return {
        fqn: {
            "element_type": "PROCESS_MANAGER",
            "fqn": fqn,
            "handlers": handlers or {},
            "name": name,
        }
    }


def _projector(
    fqn: str, *, projector_for: str = "", handlers: dict | None = None
) -> dict:
    name = fqn.rsplit(".", 1)[-1]
    return {
        fqn: {
            "element_type": "PROJECTOR",
            "fqn": fqn,
            "handlers": handlers or {},
            "name": name,
            "projector_for": projector_for,
        }
    }


def _subscriber(fqn: str, *, stream: str = "", broker: str = "default") -> dict:
    name = fqn.rsplit(".", 1)[-1]
    return {
        fqn: {
            "element_type": "SUBSCRIBER",
            "fqn": fqn,
            "name": name,
            "stream": stream,
            "broker": broker,
        }
    }


def _ir(
    *,
    clusters: dict | None = None,
    process_managers: dict | None = None,
    subscribers: dict | None = None,
    projections: dict | None = None,
) -> dict:
    ir: dict = {"clusters": clusters or {}}
    ir["flows"] = {
        "process_managers": process_managers or {},
        "subscribers": subscribers or {},
    }
    ir["projections"] = projections or {}
    return ir


# ===========================================================================
# Tests
# ===========================================================================


class TestEmptyIR:
    def test_empty_ir(self):
        result = generate_handler_wiring_diagram({})
        assert result == "flowchart TD"

    def test_empty_clusters(self):
        result = generate_handler_wiring_diagram(
            {"clusters": {}, "flows": {}, "projections": {}}
        )
        assert result == "flowchart TD"

    def test_no_handlers(self):
        """Clusters exist but have no handlers of any kind."""
        ir = _ir(clusters=_cluster("app.Order"))
        result = generate_handler_wiring_diagram(ir)
        # Only the header — no subgraphs
        assert result == "flowchart TD"


class TestCommandHandlers:
    def test_subgraph_present(self):
        cmds = _command("app.PlaceOrder")
        ch = _command_handler(
            "app.OrderCH",
            handlers={"Test.PlaceOrder.v1": ["handle_place"]},
        )
        ir = _ir(clusters=_cluster("app.Order", commands=cmds, command_handlers=ch))
        result = generate_handler_wiring_diagram(ir)
        assert 'subgraph command_handlers["Command Handlers"]' in result

    def test_handler_node(self):
        cmds = _command("app.PlaceOrder")
        ch = _command_handler(
            "app.OrderCH",
            handlers={"Test.PlaceOrder.v1": ["handle_place"]},
        )
        ir = _ir(clusters=_cluster("app.Order", commands=cmds, command_handlers=ch))
        result = generate_handler_wiring_diagram(ir)
        assert "OrderCH" in result

    def test_command_to_handler_edge(self):
        cmds = _command("app.PlaceOrder")
        ch = _command_handler(
            "app.OrderCH",
            handlers={"Test.PlaceOrder.v1": ["handle_place"]},
        )
        ir = _ir(clusters=_cluster("app.Order", commands=cmds, command_handlers=ch))
        result = generate_handler_wiring_diagram(ir)
        assert "PlaceOrder" in result
        assert "-->" in result

    def test_handler_to_aggregate_edge(self):
        cmds = _command("app.PlaceOrder")
        ch = _command_handler(
            "app.OrderCH",
            handlers={"Test.PlaceOrder.v1": ["handle_place"]},
        )
        ir = _ir(clusters=_cluster("app.Order", commands=cmds, command_handlers=ch))
        result = generate_handler_wiring_diagram(ir)
        assert "ch_app_OrderCH" in result
        assert "agg_app_Order" in result

    def test_multiple_commands_same_handler(self):
        cmds = {
            **_command("app.PlaceOrder"),
            **_command("app.CancelOrder"),
        }
        ch = _command_handler(
            "app.OrderCH",
            handlers={
                "Test.PlaceOrder.v1": ["handle_place"],
                "Test.CancelOrder.v1": ["handle_cancel"],
            },
        )
        ir = _ir(clusters=_cluster("app.Order", commands=cmds, command_handlers=ch))
        result = generate_handler_wiring_diagram(ir)
        assert "PlaceOrder" in result
        assert "CancelOrder" in result


class TestEventHandlers:
    def test_subgraph_present(self):
        evts = _event("app.OrderPlaced")
        eh = _event_handler(
            "app.NotifyHandler",
            handlers={"Test.OrderPlaced.v1": ["send_email"]},
        )
        ir = _ir(clusters=_cluster("app.Order", events=evts, event_handlers=eh))
        result = generate_handler_wiring_diagram(ir)
        assert 'subgraph event_handlers["Event Handlers"]' in result

    def test_handler_node(self):
        evts = _event("app.OrderPlaced")
        eh = _event_handler(
            "app.NotifyHandler",
            handlers={"Test.OrderPlaced.v1": ["send_email"]},
        )
        ir = _ir(clusters=_cluster("app.Order", events=evts, event_handlers=eh))
        result = generate_handler_wiring_diagram(ir)
        assert "NotifyHandler" in result

    def test_event_to_handler_edge(self):
        evts = _event("app.OrderPlaced")
        eh = _event_handler(
            "app.NotifyHandler",
            handlers={"Test.OrderPlaced.v1": ["send_email"]},
        )
        ir = _ir(clusters=_cluster("app.Order", events=evts, event_handlers=eh))
        result = generate_handler_wiring_diagram(ir)
        assert "OrderPlaced" in result
        # Stadium shape for events
        assert "([" in result

    def test_no_event_handlers_no_subgraph(self):
        ir = _ir(clusters=_cluster("app.Order"))
        result = generate_handler_wiring_diagram(ir)
        assert "Event Handlers" not in result


class TestProcessManagers:
    def test_subgraph_present(self):
        evts = _event("app.OrderPlaced")
        pm = _process_manager(
            "app.FulfillmentPM",
            handlers={
                "Test.OrderPlaced.v1": {
                    "start": True,
                    "end": False,
                    "correlate": "order_id",
                    "methods": ["on_order_placed"],
                }
            },
        )
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            process_managers=pm,
        )
        result = generate_handler_wiring_diagram(ir)
        assert 'subgraph process_managers["Process Managers"]' in result

    def test_lifecycle_annotation_on_node(self):
        evts = _event("app.OrderPlaced")
        pm = _process_manager(
            "app.FulfillmentPM",
            handlers={
                "Test.OrderPlaced.v1": {
                    "start": True,
                    "end": False,
                    "correlate": "order_id",
                    "methods": ["on_order_placed"],
                },
                "Test.PaymentFailed.v1": {
                    "start": False,
                    "end": True,
                    "correlate": "order_id",
                    "methods": ["on_failed"],
                },
            },
        )
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            process_managers=pm,
        )
        result = generate_handler_wiring_diagram(ir)
        assert "start" in result
        assert "end" in result

    def test_start_edge_label(self):
        evts = _event("app.OrderPlaced")
        pm = _process_manager(
            "app.FulfillmentPM",
            handlers={
                "Test.OrderPlaced.v1": {
                    "start": True,
                    "end": False,
                    "correlate": "order_id",
                    "methods": ["on_order_placed"],
                }
            },
        )
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            process_managers=pm,
        )
        result = generate_handler_wiring_diagram(ir)
        assert "|start|" in result

    def test_end_edge_label(self):
        evts = _event("app.PaymentFailed")
        pm = _process_manager(
            "app.FulfillmentPM",
            handlers={
                "Test.PaymentFailed.v1": {
                    "start": False,
                    "end": True,
                    "correlate": "order_id",
                    "methods": ["on_failed"],
                }
            },
        )
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            process_managers=pm,
        )
        result = generate_handler_wiring_diagram(ir)
        assert "|end|" in result

    def test_plain_edge_no_lifecycle(self):
        evts = _event("app.PaymentConfirmed")
        pm = _process_manager(
            "app.FulfillmentPM",
            handlers={
                "Test.PaymentConfirmed.v1": {
                    "start": False,
                    "end": False,
                    "correlate": "order_id",
                    "methods": ["on_confirmed"],
                }
            },
        )
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            process_managers=pm,
        )
        result = generate_handler_wiring_diagram(ir)
        # No lifecycle-labelled edges when start=False and end=False
        assert "-->|" not in result

    def test_pm_without_lifecycle(self):
        evts = _event("app.SomeEvent")
        pm = _process_manager(
            "app.SimplePM",
            handlers={
                "Test.SomeEvent.v1": {
                    "start": False,
                    "end": False,
                    "correlate": "id",
                    "methods": ["on_event"],
                }
            },
        )
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            process_managers=pm,
        )
        result = generate_handler_wiring_diagram(ir)
        # No lifecycle annotation on node label
        lines = result.split("\n")
        pm_lines = [
            line for line in lines if "SimplePM" in line and "subgraph" not in line
        ]
        # The PM label should be just "SimplePM" without parenthetical
        for line in pm_lines:
            if "pm_app_SimplePM" in line and "[" in line:
                assert "(start" not in line


class TestProjectors:
    def test_subgraph_present(self):
        evts = _event("app.OrderPlaced")
        proj = _projector(
            "app.DashProjector",
            projector_for="app.Dashboard",
            handlers={"Test.OrderPlaced.v1": ["on_placed"]},
        )
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            projections={"app.Dashboard": {"projectors": proj}},
        )
        result = generate_handler_wiring_diagram(ir)
        assert 'subgraph projectors["Projectors"]' in result

    def test_projection_target_label(self):
        evts = _event("app.OrderPlaced")
        proj = _projector(
            "app.DashProjector",
            projector_for="app.Dashboard",
            handlers={"Test.OrderPlaced.v1": ["on_placed"]},
        )
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            projections={"app.Dashboard": {"projectors": proj}},
        )
        result = generate_handler_wiring_diagram(ir)
        assert "DashProjector" in result
        assert "Dashboard" in result
        assert "\u2192" in result  # arrow character

    def test_event_to_projector_edge(self):
        evts = _event("app.OrderPlaced")
        proj = _projector(
            "app.DashProjector",
            projector_for="app.Dashboard",
            handlers={"Test.OrderPlaced.v1": ["on_placed"]},
        )
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            projections={"app.Dashboard": {"projectors": proj}},
        )
        result = generate_handler_wiring_diagram(ir)
        assert "OrderPlaced" in result


class TestSubscribers:
    def test_subgraph_present(self):
        sub = _subscriber("app.StripeSubscriber", stream="stripe_webhooks")
        ir = _ir(subscribers=sub)
        result = generate_handler_wiring_diagram(ir)
        assert 'subgraph subscribers["Subscribers"]' in result

    def test_stream_label(self):
        sub = _subscriber("app.StripeSubscriber", stream="stripe_webhooks")
        ir = _ir(subscribers=sub)
        result = generate_handler_wiring_diagram(ir)
        assert "stripe_webhooks" in result
        assert "StripeSubscriber" in result

    def test_no_stream(self):
        sub = _subscriber("app.GenericSubscriber")
        ir = _ir(subscribers=sub)
        result = generate_handler_wiring_diagram(ir)
        assert "GenericSubscriber" in result

    def test_no_external_edges(self):
        """Subscribers have no incoming edges (they read from broker streams)."""
        sub = _subscriber("app.StripeSubscriber", stream="stripe_webhooks")
        ir = _ir(subscribers=sub)
        result = generate_handler_wiring_diagram(ir)
        lines = result.split("\n")
        edge_lines = [line for line in lines if "-->" in line]
        assert len(edge_lines) == 0


class TestFullIntegration:
    """Integration test with a rich IR similar to the ordering example."""

    @pytest.fixture()
    def full_ir(self) -> dict:
        order_cmds = {
            **_command("app.PlaceOrder"),
            **_command("app.CancelOrder"),
        }
        order_evts = {
            **_event("app.OrderPlaced"),
            **_event("app.OrderCancelled"),
        }
        order_ch = _command_handler(
            "app.OrderCH",
            handlers={
                "Test.PlaceOrder.v1": ["handle_place"],
                "Test.CancelOrder.v1": ["handle_cancel"],
            },
        )
        order_eh = _event_handler(
            "app.NotifyHandler",
            handlers={"Test.OrderPlaced.v1": ["send_email"]},
        )

        payment_cmds = _command("app.ConfirmPayment")
        payment_evts = {
            **_event("app.PaymentConfirmed"),
            **_event("app.PaymentFailed"),
        }
        payment_ch = _command_handler(
            "app.PaymentCH",
            handlers={"Test.ConfirmPayment.v1": ["handle_confirm"]},
        )

        pm = _process_manager(
            "app.FulfillmentPM",
            handlers={
                "Test.OrderPlaced.v1": {
                    "start": True,
                    "end": False,
                    "correlate": "order_id",
                    "methods": ["on_placed"],
                },
                "Test.PaymentConfirmed.v1": {
                    "start": False,
                    "end": False,
                    "correlate": "order_id",
                    "methods": ["on_confirmed"],
                },
                "Test.PaymentFailed.v1": {
                    "start": False,
                    "end": True,
                    "correlate": "order_id",
                    "methods": ["on_failed"],
                },
            },
        )

        proj = _projector(
            "app.DashProjector",
            projector_for="app.Dashboard",
            handlers={
                "Test.OrderPlaced.v1": ["on_placed"],
                "Test.OrderCancelled.v1": ["on_cancelled"],
                "Test.PaymentConfirmed.v1": ["on_confirmed"],
            },
        )

        sub = _subscriber("app.StripeSubscriber", stream="stripe_webhooks")

        clusters = {
            **_cluster(
                "app.Order",
                commands=order_cmds,
                events=order_evts,
                command_handlers=order_ch,
                event_handlers=order_eh,
            ),
            **_cluster(
                "app.Payment",
                commands=payment_cmds,
                events=payment_evts,
                command_handlers=payment_ch,
            ),
        }
        return _ir(
            clusters=clusters,
            process_managers=pm,
            subscribers=sub,
            projections={"app.Dashboard": {"projectors": proj}},
        )

    def test_starts_with_flowchart(self, full_ir: dict):
        result = generate_handler_wiring_diagram(full_ir)
        assert result.startswith("flowchart TD")

    def test_all_subgroups_present(self, full_ir: dict):
        result = generate_handler_wiring_diagram(full_ir)
        assert "Command Handlers" in result
        assert "Event Handlers" in result
        assert "Process Managers" in result
        assert "Projectors" in result
        assert "Subscribers" in result

    def test_all_command_handlers_present(self, full_ir: dict):
        result = generate_handler_wiring_diagram(full_ir)
        assert "OrderCH" in result
        assert "PaymentCH" in result

    def test_all_event_handlers_present(self, full_ir: dict):
        result = generate_handler_wiring_diagram(full_ir)
        assert "NotifyHandler" in result

    def test_pm_present(self, full_ir: dict):
        result = generate_handler_wiring_diagram(full_ir)
        assert "FulfillmentPM" in result

    def test_projector_present(self, full_ir: dict):
        result = generate_handler_wiring_diagram(full_ir)
        assert "DashProjector" in result
        assert "Dashboard" in result

    def test_subscriber_present(self, full_ir: dict):
        result = generate_handler_wiring_diagram(full_ir)
        assert "StripeSubscriber" in result
        assert "stripe_webhooks" in result

    def test_edges_after_subgraphs(self, full_ir: dict):
        """Edges appear after all 'end' keywords (Mermaid best practice)."""
        result = generate_handler_wiring_diagram(full_ir)
        lines = result.split("\n")
        last_end_idx = max(i for i, line in enumerate(lines) if line.strip() == "end")
        edge_lines = [i for i, line in enumerate(lines) if "-->" in line]
        assert all(idx > last_end_idx for idx in edge_lines)


# ===========================================================================
# Per-category generator tests
# ===========================================================================


class TestPerCategoryEmpty:
    """All per-category generators return 'flowchart TD' for empty IR."""

    def test_command_handler_empty(self):
        assert generate_command_handler_diagram({}) == "flowchart TD"

    def test_event_handler_empty(self):
        assert generate_event_handler_diagram({}) == "flowchart TD"

    def test_process_manager_empty(self):
        assert generate_process_manager_diagram({}) == "flowchart TD"

    def test_projector_empty(self):
        assert generate_projector_diagram({}) == "flowchart TD"

    def test_subscriber_empty(self):
        assert generate_subscriber_diagram({}) == "flowchart TD"


class TestCommandHandlerDiagram:
    def test_contains_only_command_handlers(self):
        cmds = _command("app.PlaceOrder")
        ch = _command_handler(
            "app.OrderCH",
            handlers={"Test.PlaceOrder.v1": ["handle_place"]},
        )
        evts = _event("app.OrderPlaced")
        eh = _event_handler(
            "app.NotifyHandler",
            handlers={"Test.OrderPlaced.v1": ["send_email"]},
        )
        ir = _ir(
            clusters=_cluster(
                "app.Order",
                commands=cmds,
                events=evts,
                command_handlers=ch,
                event_handlers=eh,
            )
        )
        result = generate_command_handler_diagram(ir)
        assert "Command Handlers" in result
        assert "OrderCH" in result
        assert "PlaceOrder" in result
        # Should NOT contain event handler content
        assert "NotifyHandler" not in result
        assert "Event Handlers" not in result

    def test_command_to_handler_to_aggregate_edges(self):
        cmds = _command("app.PlaceOrder")
        ch = _command_handler(
            "app.OrderCH",
            handlers={"Test.PlaceOrder.v1": ["handle_place"]},
        )
        ir = _ir(clusters=_cluster("app.Order", commands=cmds, command_handlers=ch))
        result = generate_command_handler_diagram(ir)
        assert "cmd_app_PlaceOrder" in result
        assert "ch_app_OrderCH" in result
        assert "agg_app_Order" in result


class TestEventHandlerDiagram:
    def test_contains_only_event_handlers(self):
        evts = _event("app.OrderPlaced")
        eh = _event_handler(
            "app.NotifyHandler",
            handlers={"Test.OrderPlaced.v1": ["send_email"]},
        )
        cmds = _command("app.PlaceOrder")
        ch = _command_handler(
            "app.OrderCH",
            handlers={"Test.PlaceOrder.v1": ["handle_place"]},
        )
        ir = _ir(
            clusters=_cluster(
                "app.Order",
                commands=cmds,
                events=evts,
                command_handlers=ch,
                event_handlers=eh,
            )
        )
        result = generate_event_handler_diagram(ir)
        assert "Event Handlers" in result
        assert "NotifyHandler" in result
        # Should NOT contain command handler content
        assert "OrderCH" not in result
        assert "Command Handlers" not in result


class TestProcessManagerDiagram:
    def test_contains_only_process_managers(self):
        evts = _event("app.OrderPlaced")
        pm = _process_manager(
            "app.FulfillmentPM",
            handlers={
                "Test.OrderPlaced.v1": {
                    "start": True,
                    "end": False,
                    "correlate": "order_id",
                    "methods": ["on_order_placed"],
                }
            },
        )
        sub = _subscriber("app.StripeSubscriber", stream="stripe_webhooks")
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            process_managers=pm,
            subscribers=sub,
        )
        result = generate_process_manager_diagram(ir)
        assert "Process Managers" in result
        assert "FulfillmentPM" in result
        assert "|start|" in result
        # Should NOT contain subscriber content
        assert "StripeSubscriber" not in result
        assert "Subscribers" not in result


class TestProjectorDiagram:
    def test_contains_only_projectors(self):
        evts = _event("app.OrderPlaced")
        proj = _projector(
            "app.DashProjector",
            projector_for="app.Dashboard",
            handlers={"Test.OrderPlaced.v1": ["on_placed"]},
        )
        sub = _subscriber("app.StripeSubscriber", stream="stripe_webhooks")
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            projections={"app.Dashboard": {"projectors": proj}},
            subscribers=sub,
        )
        result = generate_projector_diagram(ir)
        assert "Projectors" in result
        assert "DashProjector" in result
        assert "Dashboard" in result
        # Should NOT contain subscriber content
        assert "StripeSubscriber" not in result


class TestSubscriberDiagram:
    def test_contains_only_subscribers(self):
        sub = _subscriber("app.StripeSubscriber", stream="stripe_webhooks")
        evts = _event("app.OrderPlaced")
        eh = _event_handler(
            "app.NotifyHandler",
            handlers={"Test.OrderPlaced.v1": ["send_email"]},
        )
        ir = _ir(
            clusters=_cluster("app.Order", events=evts, event_handlers=eh),
            subscribers=sub,
        )
        result = generate_subscriber_diagram(ir)
        assert "Subscribers" in result
        assert "StripeSubscriber" in result
        assert "stripe_webhooks" in result
        # Should NOT contain event handler content
        assert "NotifyHandler" not in result


# ===========================================================================
# Per-cluster command handler tests
# ===========================================================================


class TestClusterCommandHandlerDiagram:
    def test_empty_ir(self):
        assert (
            generate_cluster_command_handler_diagram({}, "app.Order") == "flowchart LR"
        )

    def test_unknown_cluster(self):
        ir = _ir(clusters=_cluster("app.Order"))
        assert (
            generate_cluster_command_handler_diagram(ir, "app.Missing")
            == "flowchart LR"
        )

    def test_cluster_without_handlers(self):
        ir = _ir(clusters=_cluster("app.Order"))
        assert (
            generate_cluster_command_handler_diagram(ir, "app.Order") == "flowchart LR"
        )

    def test_single_cluster(self):
        cmds = _command("app.PlaceOrder")
        ch = _command_handler(
            "app.OrderCH",
            handlers={"Test.PlaceOrder.v1": ["handle_place"]},
        )
        ir = _ir(clusters=_cluster("app.Order", commands=cmds, command_handlers=ch))
        result = generate_cluster_command_handler_diagram(ir, "app.Order")
        assert "OrderCH" in result
        assert "PlaceOrder" in result
        assert "Order" in result

    def test_excludes_other_clusters(self):
        order_cmds = _command("app.PlaceOrder")
        order_ch = _command_handler(
            "app.OrderCH",
            handlers={"Test.PlaceOrder.v1": ["handle_place"]},
        )
        payment_cmds = _command("app.ConfirmPayment")
        payment_ch = _command_handler(
            "app.PaymentCH",
            handlers={"Test.ConfirmPayment.v1": ["handle_confirm"]},
        )
        clusters = {
            **_cluster("app.Order", commands=order_cmds, command_handlers=order_ch),
            **_cluster(
                "app.Payment", commands=payment_cmds, command_handlers=payment_ch
            ),
        }
        ir = _ir(clusters=clusters)
        result = generate_cluster_command_handler_diagram(ir, "app.Order")
        assert "OrderCH" in result
        assert "PlaceOrder" in result
        # Should NOT contain Payment cluster content
        assert "PaymentCH" not in result
        assert "ConfirmPayment" not in result


# ===========================================================================
# Per-projector tests
# ===========================================================================


class TestSingleProjectorDiagram:
    def test_empty_ir(self):
        assert generate_single_projector_diagram({}, "app.Dashboard") == "flowchart LR"

    def test_unknown_projection(self):
        ir = _ir()
        assert generate_single_projector_diagram(ir, "app.Missing") == "flowchart LR"

    def test_single_projector(self):
        evts = _event("app.OrderPlaced")
        proj = _projector(
            "app.DashProjector",
            projector_for="app.Dashboard",
            handlers={"Test.OrderPlaced.v1": ["on_placed"]},
        )
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            projections={"app.Dashboard": {"projectors": proj}},
        )
        result = generate_single_projector_diagram(ir, "app.Dashboard")
        assert "DashProjector" in result
        assert "Dashboard" in result
        assert "OrderPlaced" in result

    def test_excludes_other_projections(self):
        evts = {
            **_event("app.OrderPlaced"),
            **_event("app.OrderCancelled"),
        }
        proj1 = _projector(
            "app.DashProjector",
            projector_for="app.Dashboard",
            handlers={"Test.OrderPlaced.v1": ["on_placed"]},
        )
        proj2 = _projector(
            "app.StatsProjector",
            projector_for="app.Stats",
            handlers={"Test.OrderCancelled.v1": ["on_cancelled"]},
        )
        ir = _ir(
            clusters=_cluster("app.Order", events=evts),
            projections={
                "app.Dashboard": {"projectors": proj1},
                "app.Stats": {"projectors": proj2},
            },
        )
        result = generate_single_projector_diagram(ir, "app.Dashboard")
        assert "DashProjector" in result
        # Should NOT contain Stats projector content
        assert "StatsProjector" not in result
