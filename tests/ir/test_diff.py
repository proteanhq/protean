"""Tests for IR diff — pure dict-based, no Domain needed."""

import copy

import pytest

from protean.ir.diff import diff_ir


def _minimal_ir(**overrides: object) -> dict:
    """Build a minimal valid IR dict for diff testing."""
    ir: dict = {
        "$schema": "https://protean.dev/ir/v0.1.0/schema.json",
        "checksum": "sha256:abc123",
        "clusters": {},
        "contracts": {"events": []},
        "diagnostics": [],
        "domain": {
            "camel_case_name": "Test",
            "command_processing": "sync",
            "event_processing": "sync",
            "identity_strategy": "uuid",
            "identity_type": "string",
            "name": "Test",
            "normalized_name": "test",
        },
        "elements": {},
        "flows": {
            "domain_services": {},
            "process_managers": {},
            "subscribers": {},
        },
        "generated_at": "2026-01-01T00:00:00",
        "ir_version": "0.1.0",
        "projections": {},
    }
    ir.update(overrides)
    return ir


def _make_cluster(
    name: str,
    fields: dict | None = None,
    events: dict | None = None,
    commands: dict | None = None,
    options: dict | None = None,
    **extra_sections: dict,
) -> dict:
    """Build a minimal cluster dict."""
    cluster: dict = {
        "aggregate": {
            "element_type": "AGGREGATE",
            "fields": fields or {},
            "fqn": f"app.{name}",
            "identity_field": "id",
            "invariants": {"post": [], "pre": []},
            "module": "app",
            "name": name,
            "options": options
            or {
                "auto_add_id_field": True,
                "fact_events": False,
                "is_event_sourced": False,
                "limit": 100,
                "provider": "default",
                "schema_name": None,
                "stream_category": None,
            },
        },
        "application_services": {},
        "command_handlers": {},
        "commands": commands or {},
        "database_models": {},
        "entities": {},
        "event_handlers": {},
        "events": events or {},
        "repositories": {},
        "value_objects": {},
    }
    cluster.update(extra_sections)
    return cluster


def _make_event(name: str, fqn: str, fields: dict | None = None) -> dict:
    return {
        "__type__": f"Test.{name}.v1",
        "__version__": 1,
        "element_type": "EVENT",
        "fields": fields or {},
        "fqn": fqn,
        "is_fact_event": False,
        "module": "app",
        "name": name,
        "part_of": "app.Order",
    }


def _make_command(name: str, fqn: str, fields: dict | None = None) -> dict:
    return {
        "__type__": f"Test.{name}.v1",
        "__version__": 1,
        "element_type": "COMMAND",
        "fields": fields or {},
        "fqn": fqn,
        "module": "app",
        "name": name,
        "part_of": "app.Order",
    }


# ------------------------------------------------------------------
# Identical IRs
# ------------------------------------------------------------------


class TestDiffIdentical:
    def test_no_changes(self):
        ir = _minimal_ir()
        result = diff_ir(ir, copy.deepcopy(ir))
        assert result["summary"]["has_changes"] is False

    def test_counts_all_zero(self):
        ir = _minimal_ir()
        result = diff_ir(ir, copy.deepcopy(ir))
        counts = result["summary"]["counts"]
        assert counts["added"] == 0
        assert counts["removed"] == 0
        assert counts["changed"] == 0

    def test_no_breaking_changes(self):
        ir = _minimal_ir()
        result = diff_ir(ir, copy.deepcopy(ir))
        assert result["summary"]["has_breaking_changes"] is False


# ------------------------------------------------------------------
# Cluster changes
# ------------------------------------------------------------------


class TestDiffClusters:
    def test_added_cluster(self):
        left = _minimal_ir()
        right = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        result = diff_ir(left, right)
        assert "app.Order" in result["clusters"]["added"]
        assert result["summary"]["counts"]["added"] == 1

    def test_removed_cluster(self):
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        right = _minimal_ir()
        result = diff_ir(left, right)
        assert "app.Order" in result["clusters"]["removed"]
        assert result["summary"]["counts"]["removed"] == 1

    def test_unchanged_cluster_not_in_changed(self):
        cluster = _make_cluster("Order")
        left = _minimal_ir(clusters={"app.Order": cluster})
        right = _minimal_ir(clusters={"app.Order": copy.deepcopy(cluster)})
        result = diff_ir(left, right)
        assert result["summary"]["has_changes"] is False


# ------------------------------------------------------------------
# Field-level changes
# ------------------------------------------------------------------


class TestDiffFields:
    def test_added_field(self):
        left_cluster = _make_cluster(
            "Order", fields={"name": {"kind": "standard", "type": "String"}}
        )
        right_cluster = _make_cluster(
            "Order",
            fields={
                "name": {"kind": "standard", "type": "String"},
                "email": {"kind": "standard", "type": "String", "required": True},
            },
        )
        left = _minimal_ir(clusters={"app.Order": left_cluster})
        right = _minimal_ir(clusters={"app.Order": right_cluster})
        result = diff_ir(left, right)
        agg_fields = result["clusters"]["changed"]["app.Order"]["aggregate"]["fields"]
        assert "email" in agg_fields["added"]

    def test_removed_field(self):
        left_cluster = _make_cluster(
            "Order",
            fields={
                "name": {"kind": "standard", "type": "String"},
                "legacy": {"kind": "standard", "type": "String"},
            },
        )
        right_cluster = _make_cluster(
            "Order", fields={"name": {"kind": "standard", "type": "String"}}
        )
        left = _minimal_ir(clusters={"app.Order": left_cluster})
        right = _minimal_ir(clusters={"app.Order": right_cluster})
        result = diff_ir(left, right)
        agg_fields = result["clusters"]["changed"]["app.Order"]["aggregate"]["fields"]
        assert "legacy" in agg_fields["removed"]

    def test_changed_field_attribute(self):
        left_cluster = _make_cluster(
            "Order",
            fields={"name": {"kind": "standard", "type": "String", "max_length": 100}},
        )
        right_cluster = _make_cluster(
            "Order",
            fields={"name": {"kind": "standard", "type": "String", "max_length": 200}},
        )
        left = _minimal_ir(clusters={"app.Order": left_cluster})
        right = _minimal_ir(clusters={"app.Order": right_cluster})
        result = diff_ir(left, right)
        field_change = result["clusters"]["changed"]["app.Order"]["aggregate"][
            "fields"
        ]["changed"]["name"]
        assert field_change["max_length"] == {"left": 100, "right": 200}


# ------------------------------------------------------------------
# Sub-section changes (entities, events, commands within a cluster)
# ------------------------------------------------------------------


class TestDiffClusterSubsections:
    def test_added_event(self):
        event = _make_event("OrderPlaced", "app.OrderPlaced")
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster("Order", events={"app.OrderPlaced": event})
            }
        )
        result = diff_ir(left, right)
        events_diff = result["clusters"]["changed"]["app.Order"]["events"]
        assert "app.OrderPlaced" in events_diff["added"]

    def test_removed_command(self):
        cmd = _make_command("PlaceOrder", "app.PlaceOrder")
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster("Order", commands={"app.PlaceOrder": cmd})
            }
        )
        right = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        result = diff_ir(left, right)
        cmds_diff = result["clusters"]["changed"]["app.Order"]["commands"]
        assert "app.PlaceOrder" in cmds_diff["removed"]

    def test_changed_event_field(self):
        left_event = _make_event(
            "OrderPlaced",
            "app.OrderPlaced",
            fields={"amount": {"kind": "standard", "type": "Float"}},
        )
        right_event = _make_event(
            "OrderPlaced",
            "app.OrderPlaced",
            fields={"amount": {"kind": "standard", "type": "Integer"}},
        )
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", events={"app.OrderPlaced": left_event}
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", events={"app.OrderPlaced": right_event}
                )
            }
        )
        result = diff_ir(left, right)
        event_change = result["clusters"]["changed"]["app.Order"]["events"]["changed"][
            "app.OrderPlaced"
        ]
        assert event_change["fields"]["changed"]["amount"]["type"] == {
            "left": "Float",
            "right": "Integer",
        }


# ------------------------------------------------------------------
# Options changes
# ------------------------------------------------------------------


class TestDiffOptions:
    def test_changed_option(self):
        left_opts = {
            "auto_add_id_field": True,
            "fact_events": False,
            "is_event_sourced": False,
            "limit": 100,
            "provider": "default",
            "schema_name": None,
            "stream_category": None,
        }
        right_opts = dict(left_opts, is_event_sourced=True)
        left = _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", options=left_opts)}
        )
        right = _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", options=right_opts)}
        )
        result = diff_ir(left, right)
        opts = result["clusters"]["changed"]["app.Order"]["aggregate"]["options"]
        assert opts["changed"]["is_event_sourced"] == {"left": False, "right": True}


# ------------------------------------------------------------------
# Contract changes and breaking change detection
# ------------------------------------------------------------------


class TestDiffContracts:
    def test_added_published_event(self):
        left = _minimal_ir()
        right = _minimal_ir(
            contracts={
                "events": [
                    {"__type__": "Test.OrderPlaced.v1", "fqn": "app.OrderPlaced"}
                ]
            }
        )
        result = diff_ir(left, right)
        assert len(result["contracts"]["added"]) == 1
        assert result["summary"]["has_breaking_changes"] is False

    def test_removed_published_event_is_breaking(self):
        left = _minimal_ir(
            contracts={
                "events": [
                    {"__type__": "Test.OrderPlaced.v1", "fqn": "app.OrderPlaced"}
                ]
            }
        )
        right = _minimal_ir()
        result = diff_ir(left, right)
        assert len(result["contracts"]["removed"]) == 1
        assert result["summary"]["has_breaking_changes"] is True
        breaking = result["contracts"]["breaking_changes"]
        assert breaking[0]["type"] == "contract_event_removed"

    def test_type_change_is_breaking(self):
        left = _minimal_ir(
            contracts={
                "events": [
                    {"__type__": "Test.OrderPlaced.v1", "fqn": "app.OrderPlaced"}
                ]
            }
        )
        right = _minimal_ir(
            contracts={
                "events": [
                    {"__type__": "Test.OrderPlaced.v2", "fqn": "app.OrderPlaced"}
                ]
            }
        )
        result = diff_ir(left, right)
        assert result["summary"]["has_breaking_changes"] is True
        breaking = result["contracts"]["breaking_changes"]
        assert any(b["type"] == "contract_type_changed" for b in breaking)

    def test_removed_field_from_published_event_is_breaking(self):
        event_with_field = _make_event(
            "OrderPlaced",
            "app.OrderPlaced",
            fields={"amount": {"kind": "standard", "type": "Float"}},
        )
        event_without_field = _make_event("OrderPlaced", "app.OrderPlaced", fields={})

        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", events={"app.OrderPlaced": event_with_field}
                )
            },
            contracts={
                "events": [
                    {"__type__": "Test.OrderPlaced.v1", "fqn": "app.OrderPlaced"}
                ]
            },
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", events={"app.OrderPlaced": event_without_field}
                )
            },
            contracts={
                "events": [
                    {"__type__": "Test.OrderPlaced.v1", "fqn": "app.OrderPlaced"}
                ]
            },
        )
        result = diff_ir(left, right)
        assert result["summary"]["has_breaking_changes"] is True
        breaking = result["contracts"]["breaking_changes"]
        assert any(
            b["type"] == "contract_field_removed" and b["field"] == "amount"
            for b in breaking
        )

    def test_no_breaking_when_contracts_unchanged(self):
        contract = {
            "events": [{"__type__": "Test.OrderPlaced.v1", "fqn": "app.OrderPlaced"}]
        }
        left = _minimal_ir(contracts=copy.deepcopy(contract))
        right = _minimal_ir(contracts=copy.deepcopy(contract))
        result = diff_ir(left, right)
        assert result["summary"]["has_breaking_changes"] is False


# ------------------------------------------------------------------
# Invariant changes
# ------------------------------------------------------------------


class TestDiffInvariants:
    def test_added_invariant(self):
        left_cluster = _make_cluster("Order")
        left_cluster["aggregate"]["invariants"] = {"pre": [], "post": []}
        right_cluster = _make_cluster("Order")
        right_cluster["aggregate"]["invariants"] = {
            "pre": [],
            "post": ["total_must_be_positive"],
        }
        left = _minimal_ir(clusters={"app.Order": left_cluster})
        right = _minimal_ir(clusters={"app.Order": right_cluster})
        result = diff_ir(left, right)
        inv = result["clusters"]["changed"]["app.Order"]["aggregate"]["invariants"]
        assert "total_must_be_positive" in inv["post"]["added"]

    def test_removed_invariant(self):
        left_cluster = _make_cluster("Order")
        left_cluster["aggregate"]["invariants"] = {"pre": ["check_stock"], "post": []}
        right_cluster = _make_cluster("Order")
        right_cluster["aggregate"]["invariants"] = {"pre": [], "post": []}
        left = _minimal_ir(clusters={"app.Order": left_cluster})
        right = _minimal_ir(clusters={"app.Order": right_cluster})
        result = diff_ir(left, right)
        inv = result["clusters"]["changed"]["app.Order"]["aggregate"]["invariants"]
        assert "check_stock" in inv["pre"]["removed"]


# ------------------------------------------------------------------
# Handler wiring changes
# ------------------------------------------------------------------


class TestDiffHandlers:
    def _make_event_handler(self, name: str, fqn: str, handlers: dict) -> dict:
        return {
            "element_type": "EVENT_HANDLER",
            "fqn": fqn,
            "handlers": handlers,
            "module": "app",
            "name": name,
            "part_of": "app.Order",
        }

    def test_added_handler_wiring(self):
        eh_left = self._make_event_handler(
            "OrderHandler", "app.OrderHandler", handlers={}
        )
        eh_right = self._make_event_handler(
            "OrderHandler",
            "app.OrderHandler",
            handlers={"Test.OrderPlaced.v1": ["on_placed"]},
        )
        left_cluster = _make_cluster(
            "Order", event_handlers={"app.OrderHandler": eh_left}
        )
        right_cluster = _make_cluster(
            "Order", event_handlers={"app.OrderHandler": eh_right}
        )
        left = _minimal_ir(clusters={"app.Order": left_cluster})
        right = _minimal_ir(clusters={"app.Order": right_cluster})
        result = diff_ir(left, right)
        eh_change = result["clusters"]["changed"]["app.Order"]["event_handlers"][
            "changed"
        ]["app.OrderHandler"]
        assert "Test.OrderPlaced.v1" in eh_change["handlers"]["added"]

    def test_removed_handler_wiring(self):
        eh_left = self._make_event_handler(
            "OrderHandler",
            "app.OrderHandler",
            handlers={"Test.OrderPlaced.v1": ["on_placed"]},
        )
        eh_right = self._make_event_handler(
            "OrderHandler", "app.OrderHandler", handlers={}
        )
        left_cluster = _make_cluster(
            "Order", event_handlers={"app.OrderHandler": eh_left}
        )
        right_cluster = _make_cluster(
            "Order", event_handlers={"app.OrderHandler": eh_right}
        )
        left = _minimal_ir(clusters={"app.Order": left_cluster})
        right = _minimal_ir(clusters={"app.Order": right_cluster})
        result = diff_ir(left, right)
        eh_change = result["clusters"]["changed"]["app.Order"]["event_handlers"][
            "changed"
        ]["app.OrderHandler"]
        assert "Test.OrderPlaced.v1" in eh_change["handlers"]["removed"]

    def test_changed_handler_methods(self):
        eh_left = self._make_event_handler(
            "OrderHandler",
            "app.OrderHandler",
            handlers={"Test.OrderPlaced.v1": ["on_placed"]},
        )
        eh_right = self._make_event_handler(
            "OrderHandler",
            "app.OrderHandler",
            handlers={"Test.OrderPlaced.v1": ["on_placed", "log_placed"]},
        )
        left_cluster = _make_cluster(
            "Order", event_handlers={"app.OrderHandler": eh_left}
        )
        right_cluster = _make_cluster(
            "Order", event_handlers={"app.OrderHandler": eh_right}
        )
        left = _minimal_ir(clusters={"app.Order": left_cluster})
        right = _minimal_ir(clusters={"app.Order": right_cluster})
        result = diff_ir(left, right)
        eh_change = result["clusters"]["changed"]["app.Order"]["event_handlers"][
            "changed"
        ]["app.OrderHandler"]
        handler_changed = eh_change["handlers"]["changed"]["Test.OrderPlaced.v1"]
        assert handler_changed["left"] == ["on_placed"]
        assert handler_changed["right"] == ["on_placed", "log_placed"]


# ------------------------------------------------------------------
# Apply handler changes (ES aggregates)
# ------------------------------------------------------------------


class TestDiffApplyHandlers:
    def test_added_apply_handler(self):
        left_cluster = _make_cluster("Account")
        left_cluster["aggregate"]["apply_handlers"] = {}
        right_cluster = _make_cluster("Account")
        right_cluster["aggregate"]["apply_handlers"] = {"app.AccountOpened": "opened"}
        left = _minimal_ir(clusters={"app.Account": left_cluster})
        right = _minimal_ir(clusters={"app.Account": right_cluster})
        result = diff_ir(left, right)
        apply_diff = result["clusters"]["changed"]["app.Account"]["aggregate"][
            "apply_handlers"
        ]
        assert apply_diff["changed"]["app.AccountOpened"] == {
            "left": None,
            "right": "opened",
        }

    def test_removed_apply_handler(self):
        left_cluster = _make_cluster("Account")
        left_cluster["aggregate"]["apply_handlers"] = {"app.AccountOpened": "opened"}
        right_cluster = _make_cluster("Account")
        right_cluster["aggregate"]["apply_handlers"] = {}
        left = _minimal_ir(clusters={"app.Account": left_cluster})
        right = _minimal_ir(clusters={"app.Account": right_cluster})
        result = diff_ir(left, right)
        apply_diff = result["clusters"]["changed"]["app.Account"]["aggregate"][
            "apply_handlers"
        ]
        assert apply_diff["changed"]["app.AccountOpened"] == {
            "left": "opened",
            "right": None,
        }


# ------------------------------------------------------------------
# Scalar attribute changes
# ------------------------------------------------------------------


class TestDiffScalarAttributes:
    def test_changed_element_name(self):
        """Renaming an element (same FQN, different name) shows in attributes."""
        left_event = _make_event("OrderPlaced", "app.OrderPlaced")
        right_event = _make_event("OrderPlaced", "app.OrderPlaced")
        right_event["name"] = "OrderWasPlaced"
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", events={"app.OrderPlaced": left_event}
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", events={"app.OrderPlaced": right_event}
                )
            }
        )
        result = diff_ir(left, right)
        attrs = result["clusters"]["changed"]["app.Order"]["events"]["changed"][
            "app.OrderPlaced"
        ]["attributes"]
        assert attrs["changed"]["name"] == {
            "left": "OrderPlaced",
            "right": "OrderWasPlaced",
        }

    def test_changed_type_string(self):
        left_event = _make_event("OrderPlaced", "app.OrderPlaced")
        right_event = _make_event("OrderPlaced", "app.OrderPlaced")
        right_event["__type__"] = "Test.OrderPlaced.v2"
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", events={"app.OrderPlaced": left_event}
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", events={"app.OrderPlaced": right_event}
                )
            }
        )
        result = diff_ir(left, right)
        attrs = result["clusters"]["changed"]["app.Order"]["events"]["changed"][
            "app.OrderPlaced"
        ]["attributes"]
        assert attrs["changed"]["__type__"]["left"] == "Test.OrderPlaced.v1"
        assert attrs["changed"]["__type__"]["right"] == "Test.OrderPlaced.v2"


# ------------------------------------------------------------------
# Projection sub-section changes
# ------------------------------------------------------------------


class TestDiffProjectionSubsections:
    def _make_projection_group(
        self, name: str, projectors: dict | None = None, queries: dict | None = None
    ) -> dict:
        return {
            "projection": {
                "element_type": "PROJECTION",
                "fields": {},
                "fqn": f"app.{name}",
                "module": "app",
                "name": name,
            },
            "projectors": projectors or {},
            "queries": queries or {},
            "query_handlers": {},
        }

    def test_added_projector(self):
        projector = {
            "element_type": "PROJECTOR",
            "fqn": "app.DashProjector",
            "handlers": {},
            "module": "app",
            "name": "DashProjector",
        }
        left = _minimal_ir(
            projections={"app.Dashboard": self._make_projection_group("Dashboard")}
        )
        right = _minimal_ir(
            projections={
                "app.Dashboard": self._make_projection_group(
                    "Dashboard", projectors={"app.DashProjector": projector}
                )
            }
        )
        result = diff_ir(left, right)
        proj_change = result["projections"]["changed"]["app.Dashboard"]
        assert "app.DashProjector" in proj_change["projectors"]["added"]

    def test_added_query(self):
        query = {
            "element_type": "QUERY",
            "fields": {"order_id": {"kind": "standard", "type": "Identifier"}},
            "fqn": "app.GetDashboard",
            "module": "app",
            "name": "GetDashboard",
        }
        left = _minimal_ir(
            projections={"app.Dashboard": self._make_projection_group("Dashboard")}
        )
        right = _minimal_ir(
            projections={
                "app.Dashboard": self._make_projection_group(
                    "Dashboard", queries={"app.GetDashboard": query}
                )
            }
        )
        result = diff_ir(left, right)
        proj_change = result["projections"]["changed"]["app.Dashboard"]
        assert "app.GetDashboard" in proj_change["queries"]["added"]


# ------------------------------------------------------------------
# Diagnostics
# ------------------------------------------------------------------


class TestDiffDiagnostics:
    def test_added_diagnostic(self):
        left = _minimal_ir()
        right = _minimal_ir(
            diagnostics=[
                {
                    "code": "UNHANDLED_EVENT",
                    "element": "app.OrderPlaced",
                    "level": "warning",
                    "message": "No handler",
                }
            ]
        )
        result = diff_ir(left, right)
        assert len(result["diagnostics"]["added"]) == 1

    def test_resolved_diagnostic(self):
        left = _minimal_ir(
            diagnostics=[
                {
                    "code": "UNUSED_COMMAND",
                    "element": "app.PlaceOrder",
                    "level": "warning",
                    "message": "No handler",
                }
            ]
        )
        right = _minimal_ir()
        result = diff_ir(left, right)
        assert len(result["diagnostics"]["resolved"]) == 1

    def test_unchanged_diagnostic_not_listed(self):
        diag = [
            {
                "code": "UNHANDLED_EVENT",
                "element": "app.OrderPlaced",
                "level": "warning",
                "message": "No handler",
            }
        ]
        left = _minimal_ir(diagnostics=copy.deepcopy(diag))
        right = _minimal_ir(diagnostics=copy.deepcopy(diag))
        result = diff_ir(left, right)
        assert result.get("diagnostics", {}) == {}


# ------------------------------------------------------------------
# Domain config changes
# ------------------------------------------------------------------


class TestDiffDomain:
    def test_changed_domain_config(self):
        left = _minimal_ir()
        right = _minimal_ir()
        right["domain"]["event_processing"] = "async"
        result = diff_ir(left, right)
        changed = result["domain"]["changed"]
        assert changed["event_processing"] == {"left": "sync", "right": "async"}

    def test_changed_domain_name(self):
        left = _minimal_ir()
        right = _minimal_ir()
        right["domain"]["name"] = "NewName"
        result = diff_ir(left, right)
        assert "name" in result["domain"]["changed"]


# ------------------------------------------------------------------
# Projections
# ------------------------------------------------------------------


class TestDiffProjections:
    def _make_projection_group(self, name: str, fields: dict | None = None) -> dict:
        return {
            "projection": {
                "element_type": "PROJECTION",
                "fields": fields or {},
                "fqn": f"app.{name}",
                "module": "app",
                "name": name,
            },
            "projectors": {},
            "queries": {},
            "query_handlers": {},
        }

    def test_added_projection(self):
        left = _minimal_ir()
        right = _minimal_ir(
            projections={"app.Dashboard": self._make_projection_group("Dashboard")}
        )
        result = diff_ir(left, right)
        assert "app.Dashboard" in result["projections"]["added"]

    def test_removed_projection(self):
        left = _minimal_ir(
            projections={"app.Dashboard": self._make_projection_group("Dashboard")}
        )
        right = _minimal_ir()
        result = diff_ir(left, right)
        assert "app.Dashboard" in result["projections"]["removed"]

    def test_changed_projection_field(self):
        left_proj = self._make_projection_group(
            "Dashboard", fields={"total": {"kind": "standard", "type": "Float"}}
        )
        right_proj = self._make_projection_group(
            "Dashboard", fields={"total": {"kind": "standard", "type": "Integer"}}
        )
        left = _minimal_ir(projections={"app.Dashboard": left_proj})
        right = _minimal_ir(projections={"app.Dashboard": right_proj})
        result = diff_ir(left, right)
        proj_change = result["projections"]["changed"]["app.Dashboard"]["projection"][
            "fields"
        ]
        assert proj_change["changed"]["total"]["type"] == {
            "left": "Float",
            "right": "Integer",
        }


# ------------------------------------------------------------------
# Flows
# ------------------------------------------------------------------


class TestDiffFlows:
    def test_added_subscriber(self):
        left = _minimal_ir()
        right = _minimal_ir(
            flows={
                "domain_services": {},
                "process_managers": {},
                "subscribers": {
                    "app.PaymentSub": {
                        "element_type": "SUBSCRIBER",
                        "fqn": "app.PaymentSub",
                        "module": "app",
                        "name": "PaymentSub",
                        "broker": "default",
                        "stream": "payments",
                    }
                },
            }
        )
        result = diff_ir(left, right)
        assert "app.PaymentSub" in result["flows"]["subscribers"]["added"]

    def test_removed_process_manager(self):
        left = _minimal_ir(
            flows={
                "domain_services": {},
                "process_managers": {
                    "app.Fulfillment": {
                        "element_type": "PROCESS_MANAGER",
                        "fqn": "app.Fulfillment",
                        "module": "app",
                        "name": "Fulfillment",
                    }
                },
                "subscribers": {},
            }
        )
        right = _minimal_ir()
        result = diff_ir(left, right)
        assert "app.Fulfillment" in result["flows"]["process_managers"]["removed"]


# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------


class TestDiffSummary:
    def test_checksums_in_summary(self):
        left = _minimal_ir(checksum="sha256:left111")
        right = _minimal_ir(checksum="sha256:right222")
        result = diff_ir(left, right)
        assert result["summary"]["left_checksum"] == "sha256:left111"
        assert result["summary"]["right_checksum"] == "sha256:right222"

    def test_has_changes_true_when_clusters_differ(self):
        left = _minimal_ir()
        right = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        result = diff_ir(left, right)
        assert result["summary"]["has_changes"] is True

    def test_has_changes_true_when_only_diagnostics_differ(self):
        left = _minimal_ir()
        right = _minimal_ir(
            diagnostics=[
                {
                    "code": "UNHANDLED_EVENT",
                    "element": "app.X",
                    "level": "warning",
                    "message": "msg",
                }
            ]
        )
        result = diff_ir(left, right)
        assert result["summary"]["has_changes"] is True


# ------------------------------------------------------------------
# Integration: diff with real domains
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestDiffWithRealDomains:
    """Use actual domain builders to generate IRs and diff them."""

    def test_diff_same_domain_is_empty(self):
        from protean.ir.builder import IRBuilder

        from .elements import build_cluster_test_domain

        domain = build_cluster_test_domain()
        ir = IRBuilder(domain).build()
        result = diff_ir(ir, copy.deepcopy(ir))
        assert result["summary"]["has_changes"] is False

    def test_diff_different_domains_has_changes(self):
        from protean.ir.builder import IRBuilder

        from .elements import build_cluster_test_domain, build_handler_test_domain

        ir1 = IRBuilder(build_cluster_test_domain()).build()
        ir2 = IRBuilder(build_handler_test_domain()).build()
        result = diff_ir(ir1, ir2)
        assert result["summary"]["has_changes"] is True
        # Both have different aggregates, so clusters differ
        assert result["clusters"]
