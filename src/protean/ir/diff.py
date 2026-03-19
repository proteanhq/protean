"""IR diff — compare two IR snapshots at field-level granularity.

Public API::

    from protean.ir.diff import diff_ir, classify_changes

    result = diff_ir(left_ir, right_ir)
    report = classify_changes(result, left_ir, right_ir)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def diff_ir(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    current_version: str | None = None,
) -> dict[str, Any]:
    """Compare two IR dicts and return a structured diff.

    The result contains per-section diffs (clusters, projections, flows,
    contracts, diagnostics, domain) plus a summary with counts and
    breaking-change flags.

    Skips derived/volatile keys: ``$schema``, ``ir_version``,
    ``generated_at``, ``checksum``, ``elements``.

    Args:
        current_version: When provided, used to classify removals of
            deprecated elements/fields as "expected" (safe) vs "premature"
            (breaking) based on the ``removal`` version in the deprecation
            metadata.
    """
    result: dict[str, Any] = {}

    result["clusters"] = _diff_keyed_section(
        left.get("clusters", {}),
        right.get("clusters", {}),
        _diff_cluster,
    )
    result["projections"] = _diff_keyed_section(
        left.get("projections", {}),
        right.get("projections", {}),
        _diff_projection_group,
    )
    result["flows"] = _diff_flows(
        left.get("flows", {}),
        right.get("flows", {}),
    )
    result["contracts"] = _diff_contracts(
        left.get("contracts", {}),
        right.get("contracts", {}),
        current_version=current_version,
    )
    result["diagnostics"] = _diff_diagnostics(
        left.get("diagnostics", []),
        right.get("diagnostics", []),
    )
    result["domain"] = _diff_domain(
        left.get("domain", {}),
        right.get("domain", {}),
    )
    result["summary"] = _build_summary(result, left, right)

    return result


# ------------------------------------------------------------------
# Generic helpers
# ------------------------------------------------------------------


def _diff_keyed_section(
    left: dict[str, Any],
    right: dict[str, Any],
    element_differ: Any,
) -> dict[str, Any]:
    """Diff two FQN-keyed dicts using *element_differ* for shared keys."""
    added: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    changed: dict[str, Any] = {}

    left_keys = set(left.keys())
    right_keys = set(right.keys())

    for key in sorted(right_keys - left_keys):
        added[key] = _element_summary(right[key])

    for key in sorted(left_keys - right_keys):
        removed[key] = _element_summary(left[key])

    for key in sorted(left_keys & right_keys):
        delta = element_differ(left[key], right[key])
        if delta:
            changed[key] = delta

    return _prune_empty({"added": added, "removed": removed, "changed": changed})


def _element_summary(entry: dict[str, Any]) -> dict[str, Any]:
    """Produce a minimal summary of an element for added/removed listings."""
    summary: dict[str, Any] = {}
    for key in ("name", "element_type", "fqn"):
        if key in entry:
            summary[key] = entry[key]
    # For cluster entries, extract aggregate name
    if "aggregate" in entry:
        summary["name"] = entry["aggregate"].get("name", "")
        summary["element_type"] = "CLUSTER"
    # For projection groups
    if "projection" in entry:
        summary["name"] = entry["projection"].get("name", "")
        summary["element_type"] = "PROJECTION"
    return summary


def _diff_flat_dict(
    left: dict[str, Any],
    right: dict[str, Any],
    skip_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Compare two flat dicts attribute by attribute.

    Returns ``{"changed": {key: {"left": ..., "right": ...}}}`` for
    attributes that differ.
    """
    skip = skip_keys or set()
    changed: dict[str, Any] = {}

    all_keys = sorted(set(left.keys()) | set(right.keys()))
    for key in all_keys:
        if key in skip:
            continue
        left_val = left.get(key)
        right_val = right.get(key)
        if left_val != right_val:
            changed[key] = {"left": left_val, "right": right_val}

    return _prune_empty({"changed": changed})


def _diff_fields(
    left_fields: dict[str, Any],
    right_fields: dict[str, Any],
) -> dict[str, Any]:
    """Diff two field dicts at attribute level."""
    added: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    changed: dict[str, Any] = {}

    left_names = set(left_fields.keys())
    right_names = set(right_fields.keys())

    for name in sorted(right_names - left_names):
        added[name] = right_fields[name]

    for name in sorted(left_names - right_names):
        removed[name] = left_fields[name]

    for name in sorted(left_names & right_names):
        left_f = left_fields[name]
        right_f = right_fields[name]
        if left_f != right_f:
            field_delta: dict[str, Any] = {}
            all_attrs = sorted(set(left_f.keys()) | set(right_f.keys()))
            for attr in all_attrs:
                lv = left_f.get(attr)
                rv = right_f.get(attr)
                if lv != rv:
                    field_delta[attr] = {"left": lv, "right": rv}
            if field_delta:
                changed[name] = field_delta

    return _prune_empty({"added": added, "removed": removed, "changed": changed})


def _diff_invariants(
    left_inv: dict[str, Any],
    right_inv: dict[str, Any],
) -> dict[str, Any]:
    """Diff invariant sections (pre/post lists of names)."""
    changed: dict[str, Any] = {}
    for category in ("pre", "post"):
        left_set = set(left_inv.get(category, []))
        right_set = set(right_inv.get(category, []))
        added = sorted(right_set - left_set)
        removed = sorted(left_set - right_set)
        if added or removed:
            entry: dict[str, Any] = {}
            if added:
                entry["added"] = added
            if removed:
                entry["removed"] = removed
            changed[category] = entry
    return changed


def _diff_handlers(
    left_handlers: dict[str, Any],
    right_handlers: dict[str, Any],
) -> dict[str, Any]:
    """Diff handler maps ({__type__: [method_names]})."""
    added: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    changed: dict[str, Any] = {}

    left_keys = set(left_handlers.keys())
    right_keys = set(right_handlers.keys())

    for key in sorted(right_keys - left_keys):
        added[key] = right_handlers[key]

    for key in sorted(left_keys - right_keys):
        removed[key] = left_handlers[key]

    for key in sorted(left_keys & right_keys):
        if left_handlers[key] != right_handlers[key]:
            changed[key] = {
                "left": left_handlers[key],
                "right": right_handlers[key],
            }

    return _prune_empty({"added": added, "removed": removed, "changed": changed})


# ------------------------------------------------------------------
# Element-level diffing
# ------------------------------------------------------------------


def _diff_element(
    left_el: dict[str, Any],
    right_el: dict[str, Any],
) -> dict[str, Any]:
    """Diff a single domain element (aggregate, entity, command, etc.)."""
    delta: dict[str, Any] = {}

    # Fields
    left_fields = left_el.get("fields", {})
    right_fields = right_el.get("fields", {})
    if left_fields != right_fields:
        fields_diff = _diff_fields(left_fields, right_fields)
        if fields_diff:
            delta["fields"] = fields_diff

    # Options
    left_opts = left_el.get("options", {})
    right_opts = right_el.get("options", {})
    if left_opts != right_opts:
        opts_diff = _diff_flat_dict(left_opts, right_opts)
        if opts_diff:
            delta["options"] = opts_diff

    # Invariants
    left_inv = left_el.get("invariants", {})
    right_inv = right_el.get("invariants", {})
    if left_inv != right_inv:
        inv_diff = _diff_invariants(left_inv, right_inv)
        if inv_diff:
            delta["invariants"] = inv_diff

    # Handlers (for command/event handlers, projectors)
    left_handlers = left_el.get("handlers", {})
    right_handlers = right_el.get("handlers", {})
    if left_handlers != right_handlers:
        h_diff = _diff_handlers(left_handlers, right_handlers)
        if h_diff:
            delta["handlers"] = h_diff

    # Apply handlers (ES aggregates)
    left_apply = left_el.get("apply_handlers", {})
    right_apply = right_el.get("apply_handlers", {})
    if left_apply != right_apply:
        a_diff = _diff_flat_dict(left_apply, right_apply)
        if a_diff:
            delta["apply_handlers"] = a_diff

    # Scalar attributes
    skip = {
        "fields",
        "options",
        "invariants",
        "handlers",
        "apply_handlers",
        "subscription",
    }
    scalar_diff = _diff_flat_dict(left_el, right_el, skip_keys=skip)
    if scalar_diff.get("changed"):
        delta["attributes"] = scalar_diff

    return delta


# ------------------------------------------------------------------
# Section-level diffing
# ------------------------------------------------------------------

_CLUSTER_SUBSECTIONS = (
    "entities",
    "value_objects",
    "commands",
    "events",
    "command_handlers",
    "event_handlers",
    "repositories",
    "database_models",
    "application_services",
)


def _diff_cluster(
    left_cluster: dict[str, Any],
    right_cluster: dict[str, Any],
) -> dict[str, Any]:
    """Diff a single aggregate cluster."""
    delta: dict[str, Any] = {}

    # Aggregate itself
    agg_diff = _diff_element(left_cluster["aggregate"], right_cluster["aggregate"])
    if agg_diff:
        delta["aggregate"] = agg_diff

    # Sub-sections (entities, commands, events, etc.)
    for section in _CLUSTER_SUBSECTIONS:
        left_sec = left_cluster.get(section, {})
        right_sec = right_cluster.get(section, {})
        if left_sec != right_sec:
            sec_diff = _diff_keyed_section(left_sec, right_sec, _diff_element)
            if sec_diff:
                delta[section] = sec_diff

    return delta


def _diff_projection_group(
    left_proj: dict[str, Any],
    right_proj: dict[str, Any],
) -> dict[str, Any]:
    """Diff a single projection group."""
    delta: dict[str, Any] = {}

    # Projection element
    proj_diff = _diff_element(
        left_proj.get("projection", {}),
        right_proj.get("projection", {}),
    )
    if proj_diff:
        delta["projection"] = proj_diff

    for section in ("projectors", "queries", "query_handlers"):
        left_sec = left_proj.get(section, {})
        right_sec = right_proj.get(section, {})
        if left_sec != right_sec:
            sec_diff = _diff_keyed_section(left_sec, right_sec, _diff_element)
            if sec_diff:
                delta[section] = sec_diff

    return delta


def _diff_flows(
    left_flows: dict[str, Any],
    right_flows: dict[str, Any],
) -> dict[str, Any]:
    """Diff the flows section (domain_services, process_managers, subscribers)."""
    delta: dict[str, Any] = {}

    for section in ("domain_services", "process_managers", "subscribers"):
        left_sec = left_flows.get(section, {})
        right_sec = right_flows.get(section, {})
        if left_sec != right_sec:
            sec_diff = _diff_keyed_section(left_sec, right_sec, _diff_element)
            if sec_diff:
                delta[section] = sec_diff

    return delta


def _parse_version_tuple(version_str: str) -> tuple[int | str, ...]:
    """Parse a version string into a comparable tuple.

    Handles versions like ``"0.15"``, ``"0.15.0"``, ``"1.2.3"``.
    Non-numeric segments are kept as strings so that pre-release
    suffixes sort correctly (e.g. ``"rc1"`` < any int).
    """
    parts: list[int | str] = []
    for segment in version_str.strip().split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            parts.append(segment)
    return tuple(parts)


def _classify_removal(
    deprecated: dict[str, str] | None,
    current_version: str | None = None,
) -> str:
    """Classify a removal based on deprecation metadata.

    Returns one of:
    - ``"expected_removal"`` — deprecated and past the removal version (safe)
    - ``"premature_removal"`` — deprecated but before removal version (breaking)
    - ``"unexpected_removal"`` — not deprecated at all (breaking)
    """
    if deprecated is None:
        return "unexpected_removal"

    removal = deprecated.get("removal")
    if removal is None:
        # Deprecated without explicit removal version — still breaking if
        # removed, since consumers may not have migrated yet.
        return "premature_removal"

    if current_version is not None:
        try:
            if _parse_version_tuple(current_version) >= _parse_version_tuple(
                removal
            ):
                return "expected_removal"
        except Exception:
            pass

    # Without a current version to compare, we can't confirm the removal
    # is past the deadline — treat as premature.
    return "premature_removal"


def _diff_contracts(
    left_contracts: dict[str, Any],
    right_contracts: dict[str, Any],
    current_version: str | None = None,
) -> dict[str, Any]:
    """Diff the contracts section and detect breaking changes.

    Contract entries use language-neutral keys: ``type`` (not ``__type__``),
    ``version``, ``fields``, and ``fqn``.

    Deprecation-aware classification:
    - Removing a deprecated element **after** its removal version → safe
    - Removing a deprecated element **before** its removal version → breaking
    - Removing a non-deprecated element → breaking
    """
    left_events = left_contracts.get("events", [])
    right_events = right_contracts.get("events", [])

    left_by_fqn = {e["fqn"]: e for e in left_events}
    right_by_fqn = {e["fqn"]: e for e in right_events}

    left_fqns = set(left_by_fqn.keys())
    right_fqns = set(right_by_fqn.keys())

    added = [right_by_fqn[f] for f in sorted(right_fqns - left_fqns)]
    removed = [left_by_fqn[f] for f in sorted(left_fqns - right_fqns)]

    breaking: list[dict[str, Any]] = []
    expected_removals: list[dict[str, Any]] = []

    # Removed published events — classify by deprecation status
    for event in removed:
        event_label = event.get("type", event["fqn"])
        deprecated = event.get("deprecated")
        classification = _classify_removal(deprecated, current_version)

        if classification == "expected_removal":
            expected_removals.append(
                {
                    "type": "contract_event_removed",
                    "classification": "expected_removal",
                    "event": event_label,
                    "fqn": event["fqn"],
                    "deprecated": deprecated,
                    "message": (
                        f"Published event '{event_label}' was removed "
                        f"(deprecated since v{deprecated['since']}, "
                        f"removal expected in v{deprecated.get('removal', '?')})"
                    ),
                }
            )
        else:
            entry: dict[str, Any] = {
                "type": "contract_event_removed",
                "classification": classification,
                "event": event_label,
                "fqn": event["fqn"],
                "message": f"Published event '{event_label}' was removed",
            }
            if deprecated:
                entry["deprecated"] = deprecated
                entry["message"] += (
                    f" (deprecated since v{deprecated['since']}"
                )
                if deprecated.get("removal"):
                    entry["message"] += (
                        f", scheduled for removal in v{deprecated['removal']}"
                    )
                entry["message"] += " — removed prematurely)"
            breaking.append(entry)

    # Check events present in both for type/version/field changes
    for event_fqn in sorted(left_fqns & right_fqns):
        left_evt = left_by_fqn[event_fqn]
        right_evt = right_by_fqn[event_fqn]

        # type string change is breaking
        left_type = left_evt.get("type", "")
        right_type = right_evt.get("type", "")
        if left_type != right_type:
            breaking.append(
                {
                    "type": "contract_type_changed",
                    "fqn": event_fqn,
                    "left": left_type,
                    "right": right_type,
                    "message": (
                        f"type changed for published event: "
                        f"'{left_type}' → '{right_type}'"
                    ),
                }
            )

        # Field-level changes — classify removed fields by deprecation
        left_fields = left_evt.get("fields", {})
        right_fields = right_evt.get("fields", {})
        removed_fields = set(left_fields.keys()) - set(right_fields.keys())
        for field_name in sorted(removed_fields):
            field_deprecated = left_fields[field_name].get("deprecated")
            field_classification = _classify_removal(
                field_deprecated, current_version
            )

            if field_classification == "expected_removal":
                expected_removals.append(
                    {
                        "type": "contract_field_removed",
                        "classification": "expected_removal",
                        "fqn": event_fqn,
                        "field": field_name,
                        "deprecated": field_deprecated,
                        "message": (
                            f"Field '{field_name}' removed from published "
                            f"event '{left_type}' (expected removal)"
                        ),
                    }
                )
            else:
                f_entry: dict[str, Any] = {
                    "type": "contract_field_removed",
                    "classification": field_classification,
                    "fqn": event_fqn,
                    "field": field_name,
                    "message": (
                        f"Field '{field_name}' removed from published event "
                        f"'{left_type}'"
                    ),
                }
                if field_deprecated:
                    f_entry["deprecated"] = field_deprecated
                breaking.append(f_entry)

    result: dict[str, Any] = {}
    if added:
        result["added"] = added
    if removed:
        result["removed"] = removed
    if breaking:
        result["breaking_changes"] = breaking
    if expected_removals:
        result["expected_removals"] = expected_removals

    return result


def _diff_diagnostics(
    left_diag: list[dict[str, Any]],
    right_diag: list[dict[str, Any]],
) -> dict[str, Any]:
    """Diff diagnostic lists. Identity is (code, element)."""
    left_set = {(d["code"], d["element"]) for d in left_diag}
    right_set = {(d["code"], d["element"]) for d in right_diag}

    right_by_key = {(d["code"], d["element"]): d for d in right_diag}
    left_by_key = {(d["code"], d["element"]): d for d in left_diag}

    added = [right_by_key[k] for k in sorted(right_set - left_set)]
    resolved = [left_by_key[k] for k in sorted(left_set - right_set)]

    result: dict[str, Any] = {}
    if added:
        result["added"] = added
    if resolved:
        result["resolved"] = resolved

    return result


def _diff_domain(
    left_domain: dict[str, Any],
    right_domain: dict[str, Any],
) -> dict[str, Any]:
    """Diff domain metadata."""
    return _diff_flat_dict(left_domain, right_domain)


# ------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------


def _count_changes(section: dict[str, Any]) -> dict[str, int]:
    """Count added/removed/changed in a section dict."""
    return {
        "added": len(section.get("added", {})),
        "removed": len(section.get("removed", {})),
        "changed": len(section.get("changed", {})),
    }


def _build_summary(
    result: dict[str, Any],
    left: dict[str, Any],
    right: dict[str, Any],
) -> dict[str, Any]:
    """Build the summary section from the diff result."""
    total_added = 0
    total_removed = 0
    total_changed = 0

    for section_name in ("clusters", "projections"):
        counts = _count_changes(result.get(section_name, {}))
        total_added += counts["added"]
        total_removed += counts["removed"]
        total_changed += counts["changed"]

    # Flows has sub-sections
    flows = result.get("flows", {})
    for sub in ("domain_services", "process_managers", "subscribers"):
        counts = _count_changes(flows.get(sub, {}))
        total_added += counts["added"]
        total_removed += counts["removed"]
        total_changed += counts["changed"]

    has_breaking = bool(result.get("contracts", {}).get("breaking_changes", []))

    has_changes = (
        total_added > 0
        or total_removed > 0
        or total_changed > 0
        or bool(result.get("contracts", {}).get("added"))
        or bool(result.get("contracts", {}).get("removed"))
        or bool(result.get("diagnostics", {}))
        or bool(result.get("domain", {}).get("changed"))
    )

    return {
        "has_breaking_changes": has_breaking,
        "has_changes": has_changes,
        "left_checksum": left.get("checksum", ""),
        "right_checksum": right.get("checksum", ""),
        "counts": {
            "added": total_added,
            "changed": total_changed,
            "removed": total_removed,
        },
    }


# ------------------------------------------------------------------
# Utilities
# ------------------------------------------------------------------


def _prune_empty(d: dict[str, Any]) -> dict[str, Any]:
    """Remove keys whose values are empty dicts, lists, or None."""
    return {k: v for k, v in d.items() if v}


# ------------------------------------------------------------------
# Compatibility classification
# ------------------------------------------------------------------

_PERSISTED_CLUSTER_SUBSECTIONS: tuple[str, ...] = (
    "entities",
    "value_objects",
    "commands",
    "events",
    "database_models",
)

_SECTION_TO_ELEMENT_TYPE: dict[str, str] = {
    "entities": "ENTITY",
    "value_objects": "VALUE_OBJECT",
    "commands": "COMMAND",
    "events": "EVENT",
    "database_models": "DATABASE_MODEL",
}


@dataclass
class CompatibilityChange:
    """A single entry in a compatibility report."""

    severity: str  # "breaking" or "safe"
    element_fqn: str
    change_type: str
    message: str


@dataclass
class CompatibilityReport:
    """Report of compatibility changes between two IR snapshots."""

    breaking_changes: list[CompatibilityChange] = field(default_factory=list)
    safe_changes: list[CompatibilityChange] = field(default_factory=list)

    @property
    def is_breaking(self) -> bool:
        """Return True if there are any breaking changes."""
        return bool(self.breaking_changes)


def classify_changes(
    diff_result: dict[str, Any],
    left_ir: dict[str, Any],
    right_ir: dict[str, Any],
) -> CompatibilityReport:
    """Classify persisted-schema changes in a diff result as breaking or safe.

    Walks the ``clusters`` and ``projections`` sections of *diff_result* and
    applies the following ruleset to each persisted/serialized element
    (aggregates, entities, value objects, commands, events, database models,
    and projections).  Non-persisted runtime sections (command_handlers,
    event_handlers, repositories, application_services, flows) are not
    classified.

    Rules:

    - Add optional field (no ``required`` flag, or has ``default``): safe
    - Add required field with a ``default`` value: safe
    - Add required field without a ``default``: breaking
    - Remove field from any persisted element: breaking
    - Change field type: breaking
    - Remove an element: breaking
    - Add a new element: safe
    - Visibility public → internal (``published: True`` → absent): breaking
    - Visibility internal → public (absent → ``published: True``): safe
    - Change ``__type__`` string: breaking
    """
    report = CompatibilityReport()

    _classify_clusters(diff_result.get("clusters", {}), report)
    _classify_projections(diff_result.get("projections", {}), report)

    return report


def _classify_clusters(
    clusters_diff: dict[str, Any],
    report: CompatibilityReport,
) -> None:
    for fqn in clusters_diff.get("added", {}):
        report.safe_changes.append(
            CompatibilityChange(
                severity="safe",
                element_fqn=fqn,
                change_type="element_added",
                message=f"AGGREGATE '{fqn}' was added",
            )
        )

    for fqn in clusters_diff.get("removed", {}):
        report.breaking_changes.append(
            CompatibilityChange(
                severity="breaking",
                element_fqn=fqn,
                change_type="element_removed",
                message=f"AGGREGATE '{fqn}' was removed",
            )
        )

    for cluster_fqn, cluster_delta in clusters_diff.get("changed", {}).items():
        agg_delta = cluster_delta.get("aggregate", {})
        if agg_delta:
            _classify_element_delta(agg_delta, cluster_fqn, "AGGREGATE", report)

        for section in _PERSISTED_CLUSTER_SUBSECTIONS:
            section_diff = cluster_delta.get(section, {})
            if not section_diff:
                continue
            element_type = _SECTION_TO_ELEMENT_TYPE[section]

            for fqn in section_diff.get("added", {}):
                report.safe_changes.append(
                    CompatibilityChange(
                        severity="safe",
                        element_fqn=fqn,
                        change_type="element_added",
                        message=f"{element_type} '{fqn}' was added",
                    )
                )

            for fqn in section_diff.get("removed", {}):
                report.breaking_changes.append(
                    CompatibilityChange(
                        severity="breaking",
                        element_fqn=fqn,
                        change_type="element_removed",
                        message=f"{element_type} '{fqn}' was removed",
                    )
                )

            for fqn, element_delta in section_diff.get("changed", {}).items():
                _classify_element_delta(element_delta, fqn, element_type, report)


def _classify_projections(
    projections_diff: dict[str, Any],
    report: CompatibilityReport,
) -> None:
    for fqn in projections_diff.get("added", {}):
        report.safe_changes.append(
            CompatibilityChange(
                severity="safe",
                element_fqn=fqn,
                change_type="element_added",
                message=f"PROJECTION '{fqn}' was added",
            )
        )

    for fqn in projections_diff.get("removed", {}):
        report.breaking_changes.append(
            CompatibilityChange(
                severity="breaking",
                element_fqn=fqn,
                change_type="element_removed",
                message=f"PROJECTION '{fqn}' was removed",
            )
        )

    for proj_fqn, proj_delta in projections_diff.get("changed", {}).items():
        proj_element_delta = proj_delta.get("projection", {})
        if proj_element_delta:
            _classify_element_delta(
                proj_element_delta, proj_fqn, "PROJECTION", report
            )


def _classify_element_delta(
    element_delta: dict[str, Any],
    fqn: str,
    element_type: str,
    report: CompatibilityReport,
) -> None:
    _classify_field_changes(
        element_delta.get("fields", {}), fqn, element_type, report
    )
    _classify_attribute_changes(element_delta.get("attributes", {}), fqn, report)


def _classify_field_changes(
    fields_diff: dict[str, Any],
    fqn: str,
    element_type: str,
    report: CompatibilityReport,
) -> None:
    for field_name, field_dict in fields_diff.get("added", {}).items():
        is_required = field_dict.get("required", False)
        has_default = "default" in field_dict
        if is_required and not has_default:
            report.breaking_changes.append(
                CompatibilityChange(
                    severity="breaking",
                    element_fqn=fqn,
                    change_type="required_field_added",
                    message=(
                        f"Required field '{field_name}' added to {element_type} "
                        f"'{fqn}' without a default value"
                    ),
                )
            )
        elif is_required and has_default:
            report.safe_changes.append(
                CompatibilityChange(
                    severity="safe",
                    element_fqn=fqn,
                    change_type="required_field_with_default_added",
                    message=(
                        f"Required field '{field_name}' added to {element_type} "
                        f"'{fqn}' with a default value"
                    ),
                )
            )
        else:
            report.safe_changes.append(
                CompatibilityChange(
                    severity="safe",
                    element_fqn=fqn,
                    change_type="optional_field_added",
                    message=(
                        f"Optional field '{field_name}' added to "
                        f"{element_type} '{fqn}'"
                    ),
                )
            )

    for field_name in fields_diff.get("removed", {}):
        report.breaking_changes.append(
            CompatibilityChange(
                severity="breaking",
                element_fqn=fqn,
                change_type="field_removed",
                message=f"Field '{field_name}' removed from {element_type} '{fqn}'",
            )
        )

    for field_name, field_changes in fields_diff.get("changed", {}).items():
        if "type" in field_changes:
            left_type = field_changes["type"].get("left")
            right_type = field_changes["type"].get("right")
            report.breaking_changes.append(
                CompatibilityChange(
                    severity="breaking",
                    element_fqn=fqn,
                    change_type="field_type_changed",
                    message=(
                        f"Field '{field_name}' type changed from '{left_type}' to "
                        f"'{right_type}' in {element_type} '{fqn}'"
                    ),
                )
            )


def _classify_attribute_changes(
    attrs_diff: dict[str, Any],
    fqn: str,
    report: CompatibilityReport,
) -> None:
    changed = attrs_diff.get("changed", {})

    if "__type__" in changed:
        type_change = changed["__type__"]
        left_type = type_change.get("left")
        right_type = type_change.get("right")
        report.breaking_changes.append(
            CompatibilityChange(
                severity="breaking",
                element_fqn=fqn,
                change_type="type_string_changed",
                message=(
                    f"Type string changed for '{fqn}': '{left_type}' → '{right_type}'"
                ),
            )
        )

    if "published" in changed:
        pub_change = changed["published"]
        left_published = pub_change.get("left")
        right_published = pub_change.get("right")
        if left_published and not right_published:
            report.breaking_changes.append(
                CompatibilityChange(
                    severity="breaking",
                    element_fqn=fqn,
                    change_type="visibility_public_to_internal",
                    message=f"'{fqn}' changed from public to internal (breaking change)",
                )
            )
        elif not left_published and right_published:
            report.safe_changes.append(
                CompatibilityChange(
                    severity="safe",
                    element_fqn=fqn,
                    change_type="visibility_internal_to_public",
                    message=f"'{fqn}' changed from internal to public",
                )
            )
