"""Tests for the handler wiring diagram generator."""

from __future__ import annotations

import pytest

from protean.ir.generators.handlers import generate_handler_wiring_diagram


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
