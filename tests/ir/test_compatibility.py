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


def _make_event(
    name: str, fqn: str, fields: dict | None = None, **extra: object
) -> dict:
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
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order", fields={})})
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
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order", fields={})})
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
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order", fields={})})
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
        assert change.change_type == "required_field_with_default_added"
        assert "with a default" in change.message

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
                    fields={
                        "name": {
                            "kind": "standard",
                            "type": "String",
                            "max_length": 100,
                        }
                    },
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={
                        "name": {
                            "kind": "standard",
                            "type": "String",
                            "max_length": 200,
                        }
                    },
                )
            }
        )
        report = _run(left, right)
        assert report.breaking_changes == []
        assert report.safe_changes == []


# ------------------------------------------------------------------
# Field renames (#1139)
# ------------------------------------------------------------------


def _std(type_name: str = "String", **extra: object) -> dict:
    return {"kind": "standard", "type": type_name, **extra}


class TestClassifyFieldRename:
    def test_declared_rename_is_safe_not_remove_add(self):
        left = _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", fields={"name": _std()})}
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order", fields={"customer_name": _std(renamed_from=["name"])}
                )
            }
        )
        report = _run(left, right)

        assert report.is_breaking is False
        assert [c.change_type for c in report.safe_changes] == ["field_renamed"]
        assert "name" in report.safe_changes[0].message
        assert "customer_name" in report.safe_changes[0].message
        # The remove+add pair is suppressed.
        assert report.breaking_changes == []

    def test_required_field_rename_is_still_safe(self):
        """A rename to a required field is safe — the alias resolves old
        payloads, so it is not a 'required field added without default'."""
        left = _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", fields={"name": _std()})}
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={
                        "customer_name": _std(required=True, renamed_from=["name"])
                    },
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is False
        assert [c.change_type for c in report.safe_changes] == ["field_renamed"]

    def test_rename_without_matching_alias_is_still_breaking(self):
        """Adding a new field and removing an old one, with no renamed_from
        linking them, remains a breaking remove+add."""
        left = _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", fields={"name": _std()})}
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster("Order", fields={"customer_name": _std()})
            }
        )
        report = _run(left, right)
        assert report.is_breaking is True
        assert "field_removed" in {c.change_type for c in report.breaking_changes}
        assert "field_renamed" not in {c.change_type for c in report.safe_changes}

    def test_alias_naming_a_still_present_field_is_not_a_rename(self):
        """renamed_from must name a *removed* field — if the alias still
        exists, the new field is a plain addition, not a rename."""
        left = _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", fields={"name": _std()})}
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={
                        "name": _std(),
                        "customer_name": _std(renamed_from=["name"]),
                    },
                )
            }
        )
        report = _run(left, right)
        assert "field_renamed" not in {c.change_type for c in report.safe_changes}
        assert "optional_field_added" in {c.change_type for c in report.safe_changes}

    def test_multiple_aliases_one_matches_removed_field(self):
        left = _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", fields={"name": _std()})}
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={"customer_name": _std(renamed_from=["ancient", "name"])},
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is False
        assert [c.change_type for c in report.safe_changes] == ["field_renamed"]

    def test_renamed_field_on_event_is_safe(self):
        left_event = _make_event(
            "OrderPlaced", "app.OrderPlaced", fields={"name": _std()}
        )
        right_event = _make_event(
            "OrderPlaced",
            "app.OrderPlaced",
            fields={"customer_name": _std(renamed_from=["name"])},
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
        assert [c.change_type for c in report.safe_changes] == ["field_renamed"]

    def test_rename_with_type_change_is_breaking(self):
        """A rename that also changes the field type is breaking — an old
        payload's value cannot satisfy the new type."""
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster("Order", fields={"amount": _std("Integer")})
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={"total": _std("Float", renamed_from=["amount"])},
                )
            }
        )
        report = _run(left, right)
        assert report.is_breaking is True
        change = report.breaking_changes[0]
        assert change.change_type == "field_type_changed"
        assert "amount" in change.message and "total" in change.message
        assert "Integer" in change.message and "Float" in change.message
        assert "field_renamed" not in {c.change_type for c in report.safe_changes}


class TestContractFieldRename:
    """Published-event field renames must not read as breaking in the
    deprecation-aware contract diff either."""

    @staticmethod
    def _ir(events: list[dict]) -> dict:
        return {
            "clusters": {},
            "projections": {},
            "flows": {"domain_services": {}, "process_managers": {}, "subscribers": {}},
            "contracts": {"events": events},
            "diagnostics": [],
            "domain": {"name": "Test"},
        }

    def test_published_event_field_rename_is_not_breaking(self):
        left = self._ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {"name": _std()},
                }
            ]
        )
        right = self._ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {"customer_name": _std(renamed_from=["name"])},
                }
            ]
        )
        result = diff_ir(left, right)

        contracts = result["contracts"]
        assert result["summary"]["has_breaking_changes"] is False
        assert contracts.get("breaking_changes", []) == []
        renamed = contracts.get("renamed_fields", [])
        assert len(renamed) == 1
        assert renamed[0]["field"] == "name"
        assert renamed[0]["renamed_to"] == "customer_name"

    def test_published_event_rename_with_type_change_is_breaking(self):
        left = self._ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {"amount": _std("Integer")},
                }
            ]
        )
        right = self._ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {"total": _std("Float", renamed_from=["amount"])},
                }
            ]
        )
        result = diff_ir(left, right)

        contracts = result["contracts"]
        assert result["summary"]["has_breaking_changes"] is True
        assert contracts.get("renamed_fields", []) == []
        assert any(
            b["type"] == "contract_field_type_changed"
            for b in contracts.get("breaking_changes", [])
        )

    def test_multiple_contract_renames_are_deterministically_ordered(self):
        """Rename detection iterates the added fields in sorted order, so the
        emitted ``renamed_fields`` list is stable regardless of set-iteration
        order (guards against flaky diffs)."""
        left = self._ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {"aaa": _std(), "bbb": _std()},
                }
            ]
        )
        right = self._ir(
            [
                {
                    "fqn": "app.OrderPlaced",
                    "type": "App.OrderPlaced.v1",
                    "fields": {
                        "zzz": _std(renamed_from=["bbb"]),
                        "yyy": _std(renamed_from=["aaa"]),
                    },
                }
            ]
        )
        renamed = diff_ir(left, right)["contracts"]["renamed_fields"]
        # Ordered by the (sorted) new field name: yyy (from aaa), zzz (from bbb).
        assert [r["renamed_to"] for r in renamed] == ["yyy", "zzz"]
        assert [r["field"] for r in renamed] == ["aaa", "bbb"]


# ------------------------------------------------------------------
# Evolution-aware compatibility (#1132)
# ------------------------------------------------------------------


def _evt(name: str, version: int, fields: dict) -> dict:
    """An event IR entry at a given version (both ``__version__`` and the
    version-encoding ``__type__`` string move together, as they do in real IR)."""
    return _make_event(
        name,
        f"app.{name}",
        fields=fields,
        __version__=version,
        __type__=f"Test.{name}.v{version}",
    )


def _cluster_with_events(events: dict) -> dict:
    return _make_cluster("Order", events=events)


class TestInternalEventDeprecationGrace:
    """Deliverable 1: deprecation-aware removal now covers internal/ES events
    (element-level), not only published contracts."""

    def test_deprecated_field_removed_past_removal_is_safe(self):
        left = _minimal_ir(
            clusters={
                "app.Order": _cluster_with_events(
                    {
                        "app.OrderPlaced": _evt(
                            "OrderPlaced",
                            1,
                            {
                                "legacy": _std(
                                    deprecated={"since": "0.15", "removal": "0.18"}
                                )
                            },
                        )
                    }
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _cluster_with_events(
                    {"app.OrderPlaced": _evt("OrderPlaced", 1, {})}
                )
            }
        )
        report = classify_changes(
            diff_ir(left, right), left, right, current_version="0.18"
        )
        assert report.is_breaking is False
        assert [c.change_type for c in report.safe_changes] == ["field_removed"]
        assert "expected removal" in report.safe_changes[0].message

    def test_deprecated_field_removed_before_removal_is_breaking(self):
        left = _minimal_ir(
            clusters={
                "app.Order": _cluster_with_events(
                    {
                        "app.OrderPlaced": _evt(
                            "OrderPlaced",
                            1,
                            {
                                "legacy": _std(
                                    deprecated={"since": "0.15", "removal": "0.18"}
                                )
                            },
                        )
                    }
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _cluster_with_events(
                    {"app.OrderPlaced": _evt("OrderPlaced", 1, {})}
                )
            }
        )
        report = classify_changes(
            diff_ir(left, right), left, right, current_version="0.16"
        )
        assert report.is_breaking is True
        # Factual message — states the scheduled removal, does not overclaim
        # "before its removal version" (which needs a current_version).
        msg = report.breaking_changes[0].message
        assert "deprecated since v0.15" in msg
        assert "scheduled for removal in v0.18" in msg

    def test_deprecated_field_without_removal_version_is_breaking(self):
        left = _minimal_ir(
            clusters={
                "app.Order": _cluster_with_events(
                    {
                        "app.OrderPlaced": _evt(
                            "OrderPlaced",
                            1,
                            {"legacy": _std(deprecated={"since": "0.15"})},
                        )
                    }
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _cluster_with_events(
                    {"app.OrderPlaced": _evt("OrderPlaced", 1, {})}
                )
            }
        )
        report = classify_changes(
            diff_ir(left, right), left, right, current_version="0.20"
        )
        assert report.is_breaking is True
        assert "no removal version set" in report.breaking_changes[0].message

    def test_non_deprecated_field_removal_stays_breaking(self):
        left = _minimal_ir(
            clusters={
                "app.Order": _cluster_with_events(
                    {"app.OrderPlaced": _evt("OrderPlaced", 1, {"legacy": _std()})}
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _cluster_with_events(
                    {"app.OrderPlaced": _evt("OrderPlaced", 1, {})}
                )
            }
        )
        report = classify_changes(diff_ir(left, right), left, right)
        assert report.is_breaking is True
        assert report.breaking_changes[0].change_type == "field_removed"


class TestUpcasterMitigation:
    """Deliverable 2: a version bump an upcaster covers is not breaking."""

    @staticmethod
    def _ir(events: dict, upcasters: dict | None = None) -> dict:
        overrides: dict = {"clusters": {"app.Order": _cluster_with_events(events)}}
        if upcasters is not None:
            overrides["upcasters"] = upcasters
        return _minimal_ir(**overrides)

    def test_covered_version_bump_is_not_breaking(self):
        left = self._ir(
            {"app.OrderPlaced": _evt("OrderPlaced", 1, {"amount": _std("Float")})}
        )
        right = self._ir(
            {"app.OrderPlaced": _evt("OrderPlaced", 2, {})},
            upcasters={"OrderPlaced": [{"from_version": 1, "to_version": 2}]},
        )
        report = classify_changes(diff_ir(left, right), left, right)
        assert report.is_breaking is False
        # Both the field removal and the type-string bump are mitigated + cited.
        assert {c.change_type for c in report.safe_changes} == {
            "field_removed",
            "type_string_changed",
        }
        assert all(
            c.mitigated_by == "upcaster OrderPlaced v1->v2" for c in report.safe_changes
        )

    def test_version_bump_without_upcaster_is_breaking(self):
        left = self._ir(
            {"app.OrderPlaced": _evt("OrderPlaced", 1, {"amount": _std("Float")})}
        )
        right = self._ir({"app.OrderPlaced": _evt("OrderPlaced", 2, {})})
        report = classify_changes(diff_ir(left, right), left, right)
        assert report.is_breaking is True

    def test_multi_step_chain_mitigates(self):
        left = self._ir(
            {"app.OrderPlaced": _evt("OrderPlaced", 1, {"amount": _std("Float")})}
        )
        right = self._ir(
            {"app.OrderPlaced": _evt("OrderPlaced", 3, {})},
            upcasters={
                "OrderPlaced": [
                    {"from_version": 1, "to_version": 2},
                    {"from_version": 2, "to_version": 3},
                ]
            },
        )
        report = classify_changes(diff_ir(left, right), left, right)
        assert report.is_breaking is False

    def test_upcaster_gap_leaves_change_breaking(self):
        """v1->v3 bump with only a v2->v3 upcaster: v1 payloads are stranded, so
        the change is NOT mitigated."""
        left = self._ir(
            {"app.OrderPlaced": _evt("OrderPlaced", 1, {"amount": _std("Float")})}
        )
        right = self._ir(
            {"app.OrderPlaced": _evt("OrderPlaced", 3, {})},
            upcasters={"OrderPlaced": [{"from_version": 2, "to_version": 3}]},
        )
        report = classify_changes(diff_ir(left, right), left, right)
        assert report.is_breaking is True

    def test_upcaster_for_a_different_event_does_not_mitigate(self):
        left = self._ir(
            {"app.OrderPlaced": _evt("OrderPlaced", 1, {"amount": _std("Float")})}
        )
        right = self._ir(
            {"app.OrderPlaced": _evt("OrderPlaced", 2, {})},
            upcasters={"OtherEvent": [{"from_version": 1, "to_version": 2}]},
        )
        report = classify_changes(diff_ir(left, right), left, right)
        assert report.is_breaking is True

    def test_mitigation_leaves_unrelated_breaking_changes(self):
        """A mitigated event bump coexists with an unrelated breaking change
        (here an aggregate field removal): only the event's changes downgrade."""
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={"legacy": _std()},
                    events={
                        "app.OrderPlaced": _evt(
                            "OrderPlaced", 1, {"amount": _std("Float")}
                        )
                    },
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={},
                    events={"app.OrderPlaced": _evt("OrderPlaced", 2, {})},
                )
            },
            upcasters={"OrderPlaced": [{"from_version": 1, "to_version": 2}]},
        )
        report = classify_changes(diff_ir(left, right), left, right)
        assert report.is_breaking is True
        # Only the aggregate field removal remains breaking.
        assert [c.change_type for c in report.breaking_changes] == ["field_removed"]
        assert report.breaking_changes[0].element_fqn == "app.Order"
        # The event's version-bump changes were mitigated.
        assert any(c.mitigated_by for c in report.safe_changes)

    def test_same_version_field_change_is_not_mitigated(self):
        """An upcaster does not excuse an in-place change at the *same* version
        — there was no version bump for it to cover."""
        left = self._ir(
            {"app.OrderPlaced": _evt("OrderPlaced", 2, {"amount": _std("Float")})}
        )
        right = self._ir(
            {"app.OrderPlaced": _evt("OrderPlaced", 2, {})},
            upcasters={"OrderPlaced": [{"from_version": 1, "to_version": 2}]},
        )
        report = classify_changes(diff_ir(left, right), left, right)
        assert report.is_breaking is True

    def test_added_event_is_skipped_by_mitigation(self):
        """The mitigation pass skips a newly-added event (no prior version to
        bump from). An unrelated breaking change keeps the pass running so the
        skip branch is exercised."""
        left = _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", fields={"legacy": _std()})}
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    fields={},
                    events={"app.NewEvent": _evt("NewEvent", 2, {})},
                )
            },
            upcasters={"NewEvent": [{"from_version": 1, "to_version": 2}]},
        )
        report = classify_changes(diff_ir(left, right), left, right)
        # Aggregate field removed -> breaking; the added event is safe.
        assert report.is_breaking is True
        assert [c.change_type for c in report.breaking_changes] == ["field_removed"]

    def test_event_without_version_is_not_mitigated(self):
        """A malformed event entry lacking ``__version__`` is left breaking
        rather than crashing the mitigation pass."""
        left_event = _make_event("OrderPlaced", "app.OrderPlaced", {"amount": _std()})
        right_event = _make_event("OrderPlaced", "app.OrderPlaced", {})
        del left_event["__version__"]
        del right_event["__version__"]
        left = self._ir({"app.OrderPlaced": left_event})
        right = self._ir(
            {"app.OrderPlaced": right_event},
            upcasters={"OrderPlaced": [{"from_version": 1, "to_version": 2}]},
        )
        report = classify_changes(diff_ir(left, right), left, right)
        assert report.is_breaking is True

    def test_visibility_flip_riding_a_mitigated_bump_stays_breaking(self):
        """An upcaster covers the schema transformation, not an orthogonal
        public->internal visibility flip that happens at the same bump."""
        left_event = _make_event(
            "OrderPlaced",
            "app.OrderPlaced",
            {"amount": _std("Float")},
            __version__=1,
            __type__="Test.OrderPlaced.v1",
            published=True,
        )
        right_event = _evt("OrderPlaced", 2, {})  # v2, internal (no published)
        left = self._ir({"app.OrderPlaced": left_event})
        right = self._ir(
            {"app.OrderPlaced": right_event},
            upcasters={"OrderPlaced": [{"from_version": 1, "to_version": 2}]},
        )
        report = classify_changes(diff_ir(left, right), left, right)
        assert report.is_breaking is True
        assert [c.change_type for c in report.breaking_changes] == [
            "visibility_public_to_internal"
        ]
        # The schema-transformation changes are still mitigated.
        assert {c.change_type for c in report.safe_changes} == {
            "field_removed",
            "type_string_changed",
        }


class TestRenameOnEventStillSafe:
    """Deliverable 3: the #1139 rename signal holds for event-sourced events."""

    def test_declared_rename_on_es_event_is_safe(self):
        left = _minimal_ir(
            clusters={
                "app.Order": _cluster_with_events(
                    {"app.OrderPlaced": _evt("OrderPlaced", 1, {"name": _std()})}
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _cluster_with_events(
                    {
                        "app.OrderPlaced": _evt(
                            "OrderPlaced",
                            1,
                            {"customer_name": _std(renamed_from=["name"])},
                        )
                    }
                )
            }
        )
        report = classify_changes(diff_ir(left, right), left, right)
        assert report.is_breaking is False
        assert [c.change_type for c in report.safe_changes] == ["field_renamed"]


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
        assert any(
            c.change_type == "type_string_changed" for c in report.breaking_changes
        )


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
                "app.Order": _make_cluster("Order", events={"app.OrderShipped": event})
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
                "app.Order": _make_cluster("Order", events={"app.OrderPlaced": event})
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
                "app.Order": _make_cluster("Order", commands={"app.CancelOrder": cmd})
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
                "app.Order": _make_cluster("Order", commands={"app.PlaceOrder": cmd})
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
            fields={
                "quantity": {"kind": "standard", "type": "Integer", "required": True}
            },
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
                "app.Order": _make_cluster("Order", entities={"app.OrderLine": entity})
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
                "app.Order": _make_cluster("Order", entities={"app.OrderLine": entity})
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
                "app.Order": _make_cluster("Order", value_objects={"app.Address": vo})
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
                "app.Order": _make_cluster("Order", value_objects={"app.Address": vo})
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
        right = _minimal_ir(clusters={"app.Order": _make_cluster("Order", fields={})})
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


# ------------------------------------------------------------------
# Avro compatibility verdicts (BACKWARD / FORWARD / FULL / NONE)
# ------------------------------------------------------------------


def _fld(type_name: str = "String", **extra: object) -> dict:
    return {"kind": "standard", "type": type_name, **extra}


@pytest.mark.no_test_domain
class TestAvroVerdict:
    def _agg(self, fields: dict) -> dict:
        return _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", fields=fields)}
        )

    def test_no_changes_is_full(self):
        ir = self._agg({"id": _fld("Identifier")})
        assert _run(ir, ir).avro_verdict == "FULL"

    def test_add_optional_is_full(self):
        report = _run(self._agg({}), self._agg({"note": _fld("String")}))
        assert report.avro_verdict == "FULL"

    def test_add_required_with_default_is_full(self):
        report = _run(
            self._agg({}),
            self._agg({"status": _fld("String", required=True, default="pending")}),
        )
        assert report.avro_verdict == "FULL"

    def test_add_required_no_default_is_forward_not_backward(self):
        report = _run(
            self._agg({}), self._agg({"amount": _fld("Float", required=True)})
        )
        assert report.avro_verdict == "FORWARD"

    def test_remove_required_field_is_backward_not_forward(self):
        report = _run(
            self._agg({"amount": _fld("Float", required=True)}), self._agg({})
        )
        assert report.avro_verdict == "BACKWARD"

    def test_remove_optional_field_is_full(self):
        report = _run(self._agg({"note": _fld("String")}), self._agg({}))
        assert report.avro_verdict == "FULL"

    def test_type_change_is_none(self):
        report = _run(
            self._agg({"amount": _fld("Integer", required=True)}),
            self._agg({"amount": _fld("Float", required=True)}),
        )
        assert report.avro_verdict == "NONE"

    def test_element_removed_is_none(self):
        left = _minimal_ir(clusters={"app.Order": _make_cluster("Order")})
        right = _minimal_ir()
        assert _run(left, right).avro_verdict == "NONE"

    def test_required_rename_is_backward(self):
        # Backward via the emitted Avro alias; forward-unsafe because an old
        # reader cannot fill the now-absent required old name.
        report = _run(
            self._agg({"old_name": _fld("String", required=True)}),
            self._agg(
                {"new_name": _fld("String", required=True, renamed_from=["old_name"])}
            ),
        )
        assert report.avro_verdict == "BACKWARD"

    def test_optional_rename_is_full(self):
        report = _run(
            self._agg({"old_name": _fld("String")}),
            self._agg({"new_name": _fld("String", renamed_from=["old_name"])}),
        )
        assert report.avro_verdict == "FULL"

    def test_add_required_with_callable_default_is_forward_not_backward(self):
        # A callable default is not emittable as a static Avro default, so a new
        # reader has no value for old data → not BACKWARD.
        report = _run(
            self._agg({}),
            self._agg({"seq": _fld("Auto", required=True, default="<callable>")}),
        )
        assert report.avro_verdict == "FORWARD"

    def test_remove_required_with_static_default_is_full(self):
        report = _run(
            self._agg({"amount": _fld("Float", required=True, default=0.0)}),
            self._agg({}),
        )
        assert report.avro_verdict == "FULL"

    def test_remove_required_with_callable_default_is_backward(self):
        report = _run(
            self._agg({"seq": _fld("Auto", required=True, default="<callable>")}),
            self._agg({}),
        )
        assert report.avro_verdict == "BACKWARD"

    def test_remove_identifier_field_is_backward(self):
        # Avro encodes identifier fields as required, so removing one is not
        # forward-safe even though the IR spec carries no `required` flag.
        report = _run(
            self._agg({"code": _fld("Identifier", identifier=True)}),
            self._agg({}),
        )
        assert report.avro_verdict == "BACKWARD"

    def test_backward_only_and_forward_only_intersect_to_none(self):
        # remove-required (BACKWARD) ∧ add-required-no-default (FORWARD) → NONE.
        report = _run(
            self._agg({"amount": _fld("Float", required=True)}),
            self._agg({"qty": _fld("Integer", required=True)}),
        )
        assert report.avro_verdict == "NONE"

    def test_per_element_verdicts(self):
        left = _minimal_ir(
            clusters={
                "app.A": _make_cluster("A", fields={"x": _fld("Float", required=True)}),
                "app.B": _make_cluster("B", fields={}),
            }
        )
        right = _minimal_ir(
            clusters={
                "app.A": _make_cluster("A", fields={}),  # remove required → BACKWARD
                "app.B": _make_cluster(
                    "B", fields={"y": _fld("Integer", required=True)}
                ),  # add required-no-default → FORWARD
            }
        )
        report = _run(left, right)
        by_element = report.avro_verdicts_by_element()
        assert by_element["app.A"] == "BACKWARD"
        assert by_element["app.B"] == "FORWARD"
        # The domain-wide verdict is the intersection.
        assert report.avro_verdict == "NONE"

    def test_intersection_across_changes(self):
        # add-optional (FULL) ∧ remove-required (BACKWARD) → BACKWARD overall.
        report = _run(
            self._agg({"amount": _fld("Float", required=True)}),
            self._agg({"note": _fld("String")}),
        )
        assert report.avro_verdict == "BACKWARD"

    def test_visibility_flip_is_avro_neutral_but_still_breaking(self):
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    events={
                        "app.OrderPlaced": _make_event(
                            "OrderPlaced", "app.OrderPlaced", published=True
                        )
                    },
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    events={
                        "app.OrderPlaced": _make_event("OrderPlaced", "app.OrderPlaced")
                    },
                )
            }
        )
        report = _run(left, right)
        # A public→internal flip is breaking, but it changes the publication
        # contract, not the payload bytes, so it is Avro-neutral.
        assert report.is_breaking is True
        assert report.avro_verdict == "FULL"

    def test_upcaster_mitigated_change_is_backward(self):
        left = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    events={
                        "app.OrderPlaced": _make_event(
                            "OrderPlaced",
                            "app.OrderPlaced",
                            fields={"a": _fld("Integer", required=True)},
                        )
                    },
                )
            }
        )
        right = _minimal_ir(
            clusters={
                "app.Order": _make_cluster(
                    "Order",
                    events={
                        "app.OrderPlaced": _make_event(
                            "OrderPlaced",
                            "app.OrderPlaced",
                            fields={"a": _fld("Float", required=True)},
                            __version__=2,
                            __type__="Test.OrderPlaced.v2",
                        )
                    },
                )
            },
            upcasters={"OrderPlaced": [{"from_version": 1, "to_version": 2}]},
        )
        report = _run(left, right)
        # The upcaster covers v1→v2, so the type change is mitigated
        # (backward-safe at read time) → BACKWARD, not NONE.
        assert report.avro_verdict == "BACKWARD"
        assert any(c.mitigated_by for c in report.safe_changes)

    def test_direction_breaks_explain_a_non_full_verdict(self):
        report = _run(
            self._agg({"amount": _fld("Float", required=True)}), self._agg({})
        )
        breaks = report.avro_direction_breaks()
        assert len(breaks) == 1
        direction, change = breaks[0]
        assert direction == "FORWARD"  # removing a required field breaks forward
        assert change.change_type == "field_removed"


@pytest.mark.no_test_domain
class TestVerdictMatchesFastavro:
    """The verdict must agree with real Avro resolution of the emitted `.avsc`.

    This guards against the verdict drifting from what a schema registry would
    actually enforce on the schema `generators/avro.py` emits.
    """

    def _avsc(self, fields: dict) -> dict:
        from protean.ir.generators.avro import generate_avro_schema

        return generate_avro_schema(
            {"element_type": "EVENT", "name": "E", "fqn": "app.E", "fields": fields}
        )

    def _resolves(self, writer_fields: dict, reader_fields: dict, record: dict) -> bool:
        """True if a record written with *writer_fields* decodes under *reader_fields*."""
        import io

        fastavro = pytest.importorskip("fastavro")
        writer = fastavro.parse_schema(self._avsc(writer_fields))
        reader = fastavro.parse_schema(self._avsc(reader_fields))
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, writer, record)
        buf.seek(0)
        try:
            fastavro.schemaless_reader(buf, writer, reader)
            return True
        except Exception:
            return False

    def _agg(self, fields: dict) -> dict:
        return _minimal_ir(
            clusters={"app.Order": _make_cluster("Order", fields=fields)}
        )

    def test_required_rename_backward_matches_fastavro(self):
        old = {"old_name": _fld("String", required=True)}
        new = {"new_name": _fld("String", required=True, renamed_from=["old_name"])}
        assert _run(self._agg(old), self._agg(new)).avro_verdict == "BACKWARD"
        # BACKWARD: a new-schema reader decodes old-written data (via the alias).
        assert self._resolves(old, new, {"old_name": "x"}) is True
        # not FORWARD: an old-schema reader cannot decode new-written data.
        assert self._resolves(new, old, {"new_name": "x"}) is False

    def test_add_optional_full_matches_fastavro(self):
        old = {"a": _fld("String", required=True)}
        new = {"a": _fld("String", required=True), "note": _fld("String")}
        assert _run(self._agg(old), self._agg(new)).avro_verdict == "FULL"
        assert self._resolves(old, new, {"a": "x"}) is True  # backward
        assert self._resolves(new, old, {"a": "x", "note": None}) is True  # forward

    def test_add_required_no_default_not_backward_matches_fastavro(self):
        old = {"a": _fld("String", required=True)}
        new = {
            "a": _fld("String", required=True),
            "amount": _fld("Float", required=True),
        }
        assert _run(self._agg(old), self._agg(new)).avro_verdict == "FORWARD"
        # not BACKWARD: the new reader needs `amount`, absent from old data.
        assert self._resolves(old, new, {"a": "x"}) is False
