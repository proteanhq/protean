"""Tests for classify_changes — compatibility rule engine.

Pure dict-based tests; no Domain needed.
"""

from __future__ import annotations

import copy

import pytest

from protean.ir.diff import (
    CompatibilityChange,
    CompatibilityReport,
    classify_changes,
    diff_ir,
)


# ------------------------------------------------------------------
# Shared helpers (mirrors test_diff.py conventions)
# ------------------------------------------------------------------


def _minimal_ir(**overrides: object) -> dict:
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
    entities: dict | None = None,
    value_objects: dict | None = None,
    database_models: dict | None = None,
    options: dict | None = None,
) -> dict:
    return {
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
        "database_models": database_models or {},
        "entities": entities or {},
        "event_handlers": {},
        "events": events or {},
        "repositories": {},
        "value_objects": value_objects or {},
    }


def _make_event(name: str, fqn: str, fields: dict | None = None, **extra: object) -> dict:
    entry: dict = {
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
    entry.update(extra)
    return entry


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


def _make_entity(name: str, fqn: str, fields: dict | None = None) -> dict:
    return {
        "element_type": "ENTITY",
        "fields": fields or {},
        "fqn": fqn,
        "module": "app",
        "name": name,
        "part_of": "app.Order",
    }


def _make_projection_group(
    name: str, fields: dict | None = None, projectors: dict | None = None
) -> dict:
    return {
        "projection": {
            "element_type": "PROJECTION",
            "fields": fields or {},
            "fqn": f"app.{name}",
            "module": "app",
            "name": name,
        },
        "projectors": projectors or {},
        "queries": {},
        "query_handlers": {},
    }


def _run(left: dict, right: dict) -> CompatibilityReport:
    """Diff two IRs and classify the changes."""
    diff = diff_ir(left, right)
    return classify_changes(diff, left, right)


# ------------------------------------------------------------------
# CompatibilityReport / CompatibilityChange dataclasses
# ------------------------------------------------------------------


class TestCompatibilityReportDataclass:
    def test_empty_report_is_not_breaking(self):
        report = CompatibilityReport()
        assert report.is_breaking is False

    def test_report_with_breaking_changes_is_breaking(self):
        report = CompatibilityReport()
        report.breaking_changes.append(
            CompatibilityChange(
                severity="breaking",
                element_fqn="app.Order",
                change_type="element_removed",
                message="AGGREGATE 'app.Order' was removed",
            )
        )
        assert report.is_breaking is True

    def test_report_with_only_safe_changes_is_not_breaking(self):
        report = CompatibilityReport()
        report.safe_changes.append(
            CompatibilityChange(
                severity="safe",
                element_fqn="app.Order",
                change_type="element_added",
                message="AGGREGATE 'app.Order' was added",
            )
        )
        assert report.is_breaking is False

    def test_change_fields(self):
        change = CompatibilityChange(
            severity="breaking",
            element_fqn="app.Order",
            change_type="field_removed",
            message="Field 'name' removed from AGGREGATE 'app.Order'",
        )
        assert change.severity == "breaking"
        assert change.element_fqn == "app.Order"
        assert change.change_type == "field_removed"
        assert "name" in change.message


# ------------------------------------------------------------------
# Identical IRs produce empty report
# ------------------------------------------------------------------


class TestClassifyIdentical:
    def test_no_changes(self):
        ir = _minimal_ir()
        report = _run(ir, copy.deepcopy(ir))
        assert report.breaking_changes == []
        assert report.safe_changes == []
        assert report.is_breaking is False

    def test_identical_with_cluster(self):
        ir = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        report = _run(ir, copy.deepcopy(ir))
        assert report.breaking_changes == []
        assert report.safe_changes == []


# ------------------------------------------------------------------
# Cluster-level additions and removals
# ------------------------------------------------------------------


class TestClassifyClusterAddedRemoved:
    def test_added_cluster_is_safe(self):
        left = _minimal_ir()
        right = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        report = _run(left, right)
        assert report.is_breaking is False
        assert len(report.safe_changes) == 1
        change = report.safe_changes[0]
        assert change.change_type == "element_added"
        assert change.element_fqn == "app.Order"
        assert change.severity == "safe"

    def test_removed_cluster_is_breaking(self):
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        right = _minimal_ir()
        report = _run(left, right)
        assert report.is_breaking is True
        assert len(report.breaking_changes) == 1
        change = report.breaking_changes[0]
        assert change.change_type == "element_removed"
        assert change.element_fqn == "app.Order"
        assert change.severity == "breaking"

    def test_added_and_removed_clusters(self):
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        right = _minimal_ir(clusters={"app.Product": _make_cluster("Product")})
        report = _run(left, right)
        assert report.is_breaking is True
        breaking_fqns = {c.element_fqn for c in report.breaking_changes}
        safe_fqns = {c.element_fqn for c in report.safe_changes}
        assert "app.Order" in breaking_fqns
        assert "app.Product" in safe_fqns


# ------------------------------------------------------------------
# Aggregate field changes
# ------------------------------------------------------------------


class TestClassifyAggregateFieldChanges:
    def test_added_optional_field_is_safe(self):
        left = _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", fields={})}
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={"note": {"kind": "standard", "type": "String"}},
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is False
        assert len(report.safe_changes) == 1
        change = report.safe_changes[0]
        assert change.change_type == "optional_field_added"
        assert "note" in change.message

    def test_added_required_field_without_default_is_breaking(self):
        left = _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", fields={})}
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={
                        "amount": {
                            "kind": "standard",
                            "type": "Float",
                            "required": True,
                        }
                    },
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "required_field_added"
        assert "amount" in change.message

    def test_added_required_field_with_default_is_safe(self):
        left = _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", fields={})}
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={
                        "status": {
                            "kind": "standard",
                            "type": "String",
                            "required": True,
                            "default": "pending",
                        }
                    },
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is False
        change = report.safe_changes[0]
        assert change.change_type == "optional_field_added"

    def test_removed_field_is_breaking(self):
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={
                        "name": {"kind": "standard", "type": "String"},
                        "legacy": {"kind": "standard", "type": "String"},
                    },
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", fields={"name": {"kind": "standard", "type": "String"}}
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "field_removed"
        assert "legacy" in change.message

    def test_field_type_change_is_breaking(self):
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={"amount": {"kind": "standard", "type": "Float"}},
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={"amount": {"kind": "standard", "type": "Integer"}},
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "field_type_changed"
        assert "amount" in change.message
        assert "Float" in change.message
        assert "Integer" in change.message

    def test_non_type_field_attribute_change_produces_no_entry(self):
        """Changing max_length is not a compatibility-relevant change."""
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={"name": {"kind": "standard", "type": "String", "max_length": 100}},
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={"name": {"kind": "standard", "type": "String", "max_length": 200}},
                )
            }
        )
        report = _run(left, right)
        assert report.breaking_changes == []
        assert report.safe_changes == []


# ------------------------------------------------------------------
# __type__ string changes
# ------------------------------------------------------------------


class TestClassifyTypeStringChanged:
    def test_type_string_change_in_event_is_breaking(self):
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
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "type_string_changed"
        assert change.element_fqn == "app.OrderPlaced"
        assert "v1" in change.message
        assert "v2" in change.message

    def test_type_string_change_in_aggregate_is_breaking(self):
        left_cluster = _make_cluster("Order")
        right_cluster = copy.deepcopy(left_cluster)
        right_cluster["aggregate"]["__type__"] = "Test.Order.v2"
        left_cluster["aggregate"]["__type__"] = "Test.Order.v1"

        left = _minimal_ir(clusters={"app.Order": left_cluster})
        right = _minimal_ir(clusters={"app.Order": right_cluster})
        report = _run(left, right)
        assert report.is_breaking is True
        assert any(c.change_type == "type_string_changed" for c in report.breaking_changes)


# ------------------------------------------------------------------
# Visibility changes (published flag)
# ------------------------------------------------------------------


class TestClassifyVisibilityChanged:
    def test_public_to_internal_is_breaking(self):
        left_event = _make_event("OrderPlaced", "app.OrderPlaced", published=True)
        right_event = _make_event("OrderPlaced", "app.OrderPlaced")
        # right has no 'published' key — internal

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
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "visibility_public_to_internal"
        assert change.element_fqn == "app.OrderPlaced"

    def test_internal_to_public_is_safe(self):
        left_event = _make_event("OrderPlaced", "app.OrderPlaced")
        right_event = _make_event("OrderPlaced", "app.OrderPlaced", published=True)

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
        report = _run(left, right)
        assert report.is_breaking is False
        change = report.safe_changes[0]
        assert change.change_type == "visibility_internal_to_public"
        assert change.element_fqn == "app.OrderPlaced"


# ------------------------------------------------------------------
# Cluster sub-section: events
# ------------------------------------------------------------------


class TestClassifyEventChanges:
    def test_added_event_is_safe(self):
        event = _make_event("OrderShipped", "app.OrderShipped")
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", events={"app.OrderShipped": event}
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is False
        change = report.safe_changes[0]
        assert change.change_type == "element_added"
        assert change.element_fqn == "app.OrderShipped"

    def test_removed_event_is_breaking(self):
        event = _make_event("OrderPlaced", "app.OrderPlaced")
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", events={"app.OrderPlaced": event}
                )
            }
        )
        right = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "element_removed"
        assert change.element_fqn == "app.OrderPlaced"

    def test_removed_field_from_event_is_breaking(self):
        left_event = _make_event(
            "OrderPlaced",
            "app.OrderPlaced",
            fields={"amount": {"kind": "standard", "type": "Float"}},
        )
        right_event = _make_event("OrderPlaced", "app.OrderPlaced", fields={})

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
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "field_removed"
        assert "amount" in change.message

    def test_added_optional_field_to_event_is_safe(self):
        left_event = _make_event("OrderPlaced", "app.OrderPlaced", fields={})
        right_event = _make_event(
            "OrderPlaced",
            "app.OrderPlaced",
            fields={"note": {"kind": "standard", "type": "String"}},
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
        report = _run(left, right)
        assert report.is_breaking is False
        assert any(c.change_type == "optional_field_added" for c in report.safe_changes)

    def test_event_field_type_change_is_breaking(self):
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
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "field_type_changed"


# ------------------------------------------------------------------
# Cluster sub-section: commands
# ------------------------------------------------------------------


class TestClassifyCommandChanges:
    def test_added_command_is_safe(self):
        cmd = _make_command("CancelOrder", "app.CancelOrder")
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", commands={"app.CancelOrder": cmd}
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is False
        change = report.safe_changes[0]
        assert change.change_type == "element_added"
        assert change.element_fqn == "app.CancelOrder"

    def test_removed_command_is_breaking(self):
        cmd = _make_command("PlaceOrder", "app.PlaceOrder")
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", commands={"app.PlaceOrder": cmd}
                )
            }
        )
        right = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "element_removed"
        assert change.element_fqn == "app.PlaceOrder"

    def test_required_field_added_to_command_is_breaking(self):
        left_cmd = _make_command("PlaceOrder", "app.PlaceOrder", fields={})
        right_cmd = _make_command(
            "PlaceOrder",
            "app.PlaceOrder",
            fields={"quantity": {"kind": "standard", "type": "Integer", "required": True}},
        )

        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", commands={"app.PlaceOrder": left_cmd}
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", commands={"app.PlaceOrder": right_cmd}
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "required_field_added"
        assert "quantity" in change.message


# ------------------------------------------------------------------
# Cluster sub-section: entities
# ------------------------------------------------------------------


class TestClassifyEntityChanges:
    def test_added_entity_is_safe(self):
        entity = _make_entity("OrderLine", "app.OrderLine")
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", entities={"app.OrderLine": entity}
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is False
        change = report.safe_changes[0]
        assert change.change_type == "element_added"
        assert change.element_fqn == "app.OrderLine"

    def test_removed_entity_is_breaking(self):
        entity = _make_entity("OrderLine", "app.OrderLine")
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", entities={"app.OrderLine": entity}
                )
            }
        )
        right = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "element_removed"
        assert change.element_fqn == "app.OrderLine"

    def test_field_removed_from_entity_is_breaking(self):
        left_entity = _make_entity(
            "OrderLine",
            "app.OrderLine",
            fields={
                "sku": {"kind": "standard", "type": "String"},
                "qty": {"kind": "standard", "type": "Integer"},
            },
        )
        right_entity = _make_entity(
            "OrderLine",
            "app.OrderLine",
            fields={"sku": {"kind": "standard", "type": "String"}},
        )

        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", entities={"app.OrderLine": left_entity}
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", entities={"app.OrderLine": right_entity}
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "field_removed"
        assert "qty" in change.message


# ------------------------------------------------------------------
# Cluster sub-section: value_objects
# ------------------------------------------------------------------


class TestClassifyValueObjectChanges:
    def test_added_value_object_is_safe(self):
        vo = {
            "element_type": "VALUE_OBJECT",
            "fields": {},
            "fqn": "app.Address",
            "module": "app",
            "name": "Address",
        }
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", value_objects={"app.Address": vo}
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is False
        change = report.safe_changes[0]
        assert change.change_type == "element_added"

    def test_removed_value_object_is_breaking(self):
        vo = {
            "element_type": "VALUE_OBJECT",
            "fields": {"city": {"kind": "standard", "type": "String"}},
            "fqn": "app.Address",
            "module": "app",
            "name": "Address",
        }
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", value_objects={"app.Address": vo}
                )
            }
        )
        right = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "element_removed"
        assert change.element_fqn == "app.Address"


# ------------------------------------------------------------------
# Cluster sub-section: database_models
# ------------------------------------------------------------------


class TestClassifyDatabaseModelChanges:
    def _make_db_model(self, name: str, fqn: str, fields: dict | None = None) -> dict:
        return {
            "element_type": "DATABASE_MODEL",
            "fields": fields or {},
            "fqn": fqn,
            "module": "app",
            "name": name,
            "part_of": "app.Order",
        }

    def test_added_database_model_is_safe(self):
        model = self._make_db_model("OrderModel", "app.OrderModel")
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", database_models={"app.OrderModel": model}
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is False
        change = report.safe_changes[0]
        assert change.change_type == "element_added"

    def test_removed_database_model_is_breaking(self):
        model = self._make_db_model("OrderModel", "app.OrderModel")
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", database_models={"app.OrderModel": model}
                )
            }
        )
        right = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "element_removed"

    def test_removed_field_from_database_model_is_breaking(self):
        left_model = self._make_db_model(
            "OrderModel",
            "app.OrderModel",
            fields={
                "total": {"kind": "standard", "type": "Float"},
                "tax": {"kind": "standard", "type": "Float"},
            },
        )
        right_model = self._make_db_model(
            "OrderModel",
            "app.OrderModel",
            fields={"total": {"kind": "standard", "type": "Float"}},
        )
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", database_models={"app.OrderModel": left_model}
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", database_models={"app.OrderModel": right_model}
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "field_removed"
        assert "tax" in change.message


# ------------------------------------------------------------------
# Projection changes
# ------------------------------------------------------------------


class TestClassifyProjectionChanges:
    def test_added_projection_is_safe(self):
        left = _minimal_ir()
        right = _minimal_ir(
            projections={"app.Dashboard": _make_projection_group("Dashboard")}
        )
        report = _run(left, right)
        assert report.is_breaking is False
        change = report.safe_changes[0]
        assert change.change_type == "element_added"
        assert change.element_fqn == "app.Dashboard"

    def test_removed_projection_is_breaking(self):
        left = _minimal_ir(
            projections={"app.Dashboard": _make_projection_group("Dashboard")}
        )
        right = _minimal_ir()
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "element_removed"
        assert change.element_fqn == "app.Dashboard"

    def test_removed_field_from_projection_is_breaking(self):
        left_proj = _make_projection_group(
            "Dashboard",
            fields={
                "total": {"kind": "standard", "type": "Float"},
                "count": {"kind": "standard", "type": "Integer"},
            },
        )
        right_proj = _make_projection_group(
            "Dashboard",
            fields={"total": {"kind": "standard", "type": "Float"}},
        )
        left = _minimal_ir(projections={"app.Dashboard": left_proj})
        right = _minimal_ir(projections={"app.Dashboard": right_proj})
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "field_removed"
        assert "count" in change.message

    def test_added_optional_field_to_projection_is_safe(self):
        left_proj = _make_projection_group("Dashboard", fields={})
        right_proj = _make_projection_group(
            "Dashboard",
            fields={"summary": {"kind": "standard", "type": "String"}},
        )
        left = _minimal_ir(projections={"app.Dashboard": left_proj})
        right = _minimal_ir(projections={"app.Dashboard": right_proj})
        report = _run(left, right)
        assert report.is_breaking is False
        change = report.safe_changes[0]
        assert change.change_type == "optional_field_added"

    def test_projection_field_type_change_is_breaking(self):
        left_proj = _make_projection_group(
            "Dashboard",
            fields={"total": {"kind": "standard", "type": "Float"}},
        )
        right_proj = _make_projection_group(
            "Dashboard",
            fields={"total": {"kind": "standard", "type": "Integer"}},
        )
        left = _minimal_ir(projections={"app.Dashboard": left_proj})
        right = _minimal_ir(projections={"app.Dashboard": right_proj})
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "field_type_changed"

    def test_projection_group_change_with_only_projector_added_not_classified(self):
        """A projection group whose inner projection element is unchanged but
        has a new projector produces no compatibility entries — projectors are
        runtime wiring, not a persisted schema."""
        projector = {
            "element_type": "PROJECTOR",
            "fqn": "app.DashProjector",
            "handlers": {},
            "module": "app",
            "name": "DashProjector",
        }
        left_group = _make_projection_group("Dashboard")
        right_group = _make_projection_group(
            "Dashboard", projectors={"app.DashProjector": projector}
        )
        left = _minimal_ir(projections={"app.Dashboard": left_group})
        right = _minimal_ir(projections={"app.Dashboard": right_group})
        report = _run(left, right)
        # The projection element itself is unchanged; projectors are not classified
        assert report.breaking_changes == []
        assert report.safe_changes == []


# ------------------------------------------------------------------
# Non-persisted sections are not classified
# ------------------------------------------------------------------


class TestClassifyNonPersistedSectionsIgnored:
    """command_handlers, event_handlers, repositories, application_services,
    and flows are runtime wiring — not persisted schema."""

    def test_command_handler_changes_not_classified(self):
        cmd_handler = {
            "element_type": "COMMAND_HANDLER",
            "fqn": "app.OrderHandler",
            "handlers": {"Test.PlaceOrder.v1": ["handle"]},
            "module": "app",
            "name": "OrderHandler",
            "part_of": "app.Order",
        }
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        right_cluster = _make_cluster("Order")
        right_cluster["command_handlers"] = {"app.OrderHandler": cmd_handler}
        right = _minimal_ir(clusters={"app.Order": right_cluster})
        report = _run(left, right)
        # command_handler additions should not produce any entries
        assert report.breaking_changes == []
        assert report.safe_changes == []

    def test_flow_subscriber_changes_not_classified(self):
        left = _minimal_ir()
        right = _minimal_ir(
            flows={
                "domain_services": {},
                "process_managers": {},
                "subscribers": {
                    "app.PaySub": {
                        "element_type": "SUBSCRIBER",
                        "fqn": "app.PaySub",
                        "module": "app",
                        "name": "PaySub",
                    }
                },
            }
        )
        report = _run(left, right)
        assert report.breaking_changes == []
        assert report.safe_changes == []


# ------------------------------------------------------------------
# Multiple changes in one diff
# ------------------------------------------------------------------


class TestClassifyMultipleChanges:
    def test_mixed_breaking_and_safe_changes(self):
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={
                        "name": {"kind": "standard", "type": "String"},
                        "old_field": {"kind": "standard", "type": "String"},
                    },
                ),
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={
                        "name": {"kind": "standard", "type": "String"},
                        # old_field removed (breaking)
                        # new_optional added (safe)
                        "new_optional": {"kind": "standard", "type": "String"},
                    },
                ),
                # new cluster (safe)
                "app.Product": _make_cluster("Product"),
            }
        )
        report = _run(left, right)
        assert report.is_breaking is True
        breaking_types = {c.change_type for c in report.breaking_changes}
        safe_types = {c.change_type for c in report.safe_changes}
        assert "field_removed" in breaking_types
        assert "optional_field_added" in safe_types
        assert "element_added" in safe_types

    def test_multiple_field_removals_all_reported(self):
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={
                        "a": {"kind": "standard", "type": "String"},
                        "b": {"kind": "standard", "type": "String"},
                        "c": {"kind": "standard", "type": "String"},
                    },
                )
            }
        )
        right = _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", fields={})}
        )
        report = _run(left, right)
        assert len(report.breaking_changes) == 3
        removed_fields = {c.message for c in report.breaking_changes}
        assert any("'a'" in m for m in removed_fields)
        assert any("'b'" in m for m in removed_fields)
        assert any("'c'" in m for m in removed_fields)


# ------------------------------------------------------------------
# classify_changes with real domains
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestClassifyWithRealDomains:
    def test_classify_identical_domain_is_empty(self):
        from protean.ir.builder import IRBuilder

        from .elements import build_cluster_test_domain

        domain = build_cluster_test_domain()
        ir = IRBuilder(domain).build()
        diff = diff_ir(ir, copy.deepcopy(ir))
        report = classify_changes(diff, ir, ir)
        assert report.breaking_changes == []
        assert report.safe_changes == []
        assert report.is_breaking is False
