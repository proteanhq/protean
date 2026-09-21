"""IR diff — compare two IR snapshots at field-level granularity.

Public API::

    from protean.ir.diff import diff_ir, classify_changes

    result = diff_ir(left_ir, right_ir)
    report = classify_changes(result, left_ir, right_ir)
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any, Literal

from protean.utils.upcasting import missing_upcaster_source_versions

# The Avro compatibility verdict vocabulary (matches Confluent/Avro terms).
AvroVerdict = Literal["FULL", "BACKWARD", "FORWARD", "NONE"]

# The IR field-spec sentinel for a default produced by a callable (which cannot
# be emitted as a static schema default). Mirrors ``generators/avro.py``.
_CALLABLE_DEFAULT = "<callable>"

# The version segment a ``__type__`` string ends with, e.g. the ``.v2`` of
# ``"Ordering.OrderPlaced.v2"``. Stripping it leaves the base the runtime
# upcaster chain is keyed by.
_VERSION_SUFFIX = re.compile(r"\.v\d+$")


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

    Compares only the content sections below; the derived/volatile keys in
    :data:`protean.ir.constants.VOLATILE_IR_KEYS` (``$schema``, ``ir_version``,
    ``generated_at``, ``checksum``, ``elements``) are ignored. The content
    checksum excludes the same set, keeping ``ir check`` and ``ir diff`` in
    agreement.

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


def _diff_method_edges(
    left_edges: dict[str, Any],
    right_edges: dict[str, Any],
) -> dict[str, Any]:
    """Diff ``method_edges`` maps ({method_name: {raises, invokes}}).

    Keyed by the owning method name, each edge value compared whole — a gained,
    lost or altered producer/consumer edge is reported once under that method.
    """
    added: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    changed: dict[str, Any] = {}

    left_keys = set(left_edges.keys())
    right_keys = set(right_edges.keys())

    for key in sorted(right_keys - left_keys):
        added[key] = right_edges[key]

    for key in sorted(left_keys - right_keys):
        removed[key] = left_edges[key]

    for key in sorted(left_keys & right_keys):
        if left_edges[key] != right_edges[key]:
            changed[key] = {
                "left": left_edges[key],
                "right": right_edges[key],
            }

    return _prune_empty({"added": added, "removed": removed, "changed": changed})


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

    # Method edges (raise/invoke derivation)
    left_edges = left_el.get("method_edges", {})
    right_edges = right_el.get("method_edges", {})
    if left_edges != right_edges:
        edges_diff = _diff_method_edges(left_edges, right_edges)
        if edges_diff:
            delta["method_edges"] = edges_diff

    # Scalar attributes
    skip = {
        "fields",
        "options",
        "invariants",
        "handlers",
        "apply_handlers",
        "method_edges",
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
            if _parse_version_tuple(current_version) >= _parse_version_tuple(removal):
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
    renamed_fields: list[dict[str, Any]] = []

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
                entry["message"] += f" (deprecated since v{deprecated['since']}"
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

        # A removed field claimed by a `renamed_from` on a surviving field is a
        # safe rename (the alias resolves old payloads), not a breaking removal.
        added_fields = {
            name: right_fields[name]
            for name in sorted(right_fields.keys() - left_fields.keys())
        }
        contract_renames = _detect_field_renames(added_fields, removed_fields)
        for old_name, new_name in contract_renames.items():
            old_type = left_fields[old_name].get("type")
            new_type = right_fields[new_name].get("type")
            if old_type != new_type:
                # A rename that also changes type breaks old payloads.
                breaking.append(
                    {
                        "type": "contract_field_type_changed",
                        "fqn": event_fqn,
                        "field": old_name,
                        "renamed_to": new_name,
                        "left": old_type,
                        "right": new_type,
                        "message": (
                            f"Field '{old_name}' renamed to '{new_name}' with a "
                            f"type change from '{old_type}' to '{new_type}' in "
                            f"published event '{left_type}'"
                        ),
                    }
                )
            else:
                renamed_fields.append(
                    {
                        "type": "contract_field_renamed",
                        "fqn": event_fqn,
                        "field": old_name,
                        "renamed_to": new_name,
                        "message": (
                            f"Field '{old_name}' renamed to '{new_name}' in "
                            f"published event '{left_type}'"
                        ),
                    }
                )

        for field_name in sorted(removed_fields):
            if field_name in contract_renames:
                continue
            field_deprecated = left_fields[field_name].get("deprecated")
            field_classification = _classify_removal(field_deprecated, current_version)

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
    if renamed_fields:
        result["renamed_fields"] = renamed_fields

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
    # When an otherwise-breaking change is downgraded to safe because a
    # registered upcaster transforms old payloads, this names the mitigating
    # upcaster coverage (e.g. "upcaster OrderPlaced v1->v3").
    mitigated_by: str | None = None
    # Per-field Avro safety overrides. ``None`` means "not applicable — use the
    # ``_AVRO_CHANGE_SAFETY`` table default for this change type". They are set
    # only where safety is per-field rather than fixed by the change type:
    # ``field_removed`` / ``field_renamed`` set ``forward_safe`` (depends on the
    # old field's optionality), and a required-field-add with a *callable*
    # default sets ``backward_safe=False`` (Avro cannot emit a callable default).
    backward_safe: bool | None = None
    forward_safe: bool | None = None


# Avro compatibility safety per change type: (backward_safe, forward_safe).
# BACKWARD = a new-schema reader decodes old-written data; FORWARD = an
# old-schema reader decodes new-written data. Change types absent from this
# table are treated as fully incompatible (conservative). A change's per-field
# ``backward_safe``/``forward_safe`` override wins over the table when set.
_AVRO_CHANGE_SAFETY: dict[str, tuple[bool, bool]] = {
    "element_added": (True, True),
    "element_removed": (False, False),
    "optional_field_added": (True, True),
    "required_field_with_default_added": (True, True),
    "required_field_added": (False, True),
    # Removing / renaming a field is backward-safe (a new reader ignores the
    # absent old field; a rename resolves via the emitted Avro ``aliases``);
    # forward-safety depends on the old field and is set per-change. The table
    # default is the conservative False in case a producer forgets to set it.
    "field_removed": (True, False),
    "field_renamed": (True, False),
    "field_type_changed": (False, False),
    "type_string_changed": (False, False),
    # Visibility flips change the publication contract, not the payload bytes,
    # so they are neutral for Avro decode. They remain breaking in the report
    # (and still gate the exit code via ``is_breaking``) — the verdict and the
    # gate are separate axes.
    "visibility_public_to_internal": (True, True),
    "visibility_internal_to_public": (True, True),
}


def _change_avro_safety(change: CompatibilityChange) -> tuple[bool, bool]:
    """Return ``(backward_safe, forward_safe)`` for one change under Avro rules."""
    table_backward, table_forward = _AVRO_CHANGE_SAFETY.get(
        change.change_type, (False, False)
    )
    backward = table_backward if change.backward_safe is None else change.backward_safe
    forward = table_forward if change.forward_safe is None else change.forward_safe
    if change.mitigated_by is not None:
        # A registered upcaster transforms old payloads to the new shape at read
        # time, so a new-schema reader can decode old data -> backward-safe.
        backward = True
    return backward, forward


def _verdict_from_safety(backward: bool, forward: bool) -> AvroVerdict:
    if backward and forward:
        return "FULL"
    if backward:
        return "BACKWARD"
    if forward:
        return "FORWARD"
    return "NONE"


def _avro_verdict(changes: list[CompatibilityChange]) -> AvroVerdict:
    """Fold per-change Avro safety into one verdict.

    The verdict holds a direction only if *every* change is safe in that
    direction (the intersection). An empty change set is vacuously ``FULL``.
    """
    backward = all(_change_avro_safety(c)[0] for c in changes)
    forward = all(_change_avro_safety(c)[1] for c in changes)
    return _verdict_from_safety(backward, forward)


@dataclass
class CompatibilityReport:
    """Report of compatibility changes between two IR snapshots."""

    breaking_changes: list[CompatibilityChange] = field(default_factory=list)
    safe_changes: list[CompatibilityChange] = field(default_factory=list)

    @property
    def is_breaking(self) -> bool:
        """Return True if there are any breaking changes."""
        return bool(self.breaking_changes)

    @property
    def avro_verdict(self) -> AvroVerdict:
        """Domain-wide Avro compatibility verdict — the intersection across all
        changes (breaking and safe alike, since a safe change like a rename can
        still be forward-incompatible). This is the conservative whole-domain
        answer; use :meth:`avro_verdicts_by_element` for a per-element breakdown."""
        return _avro_verdict(self.breaking_changes + self.safe_changes)

    def avro_verdicts_by_element(self) -> dict[str, AvroVerdict]:
        """Return the Avro verdict for each element that changed, keyed by FQN.

        The domain-wide :attr:`avro_verdict` is the intersection of these; a
        per-element breakdown shows exactly which element carries a weaker
        verdict (Avro compatibility is per-subject).
        """
        by_element: dict[str, list[CompatibilityChange]] = {}
        for change in self.breaking_changes + self.safe_changes:
            by_element.setdefault(change.element_fqn, []).append(change)
        return {fqn: _avro_verdict(changes) for fqn, changes in by_element.items()}

    def avro_direction_breaks(
        self,
    ) -> list[tuple[Literal["BACKWARD", "FORWARD"], CompatibilityChange]]:
        """Return ``(direction, change)`` for each change that breaks a direction.

        Direction is ``"BACKWARD"`` or ``"FORWARD"``; a change unsafe in both
        yields two entries. Used to explain a non-``FULL`` verdict.
        """
        breaks: list[tuple[Literal["BACKWARD", "FORWARD"], CompatibilityChange]] = []
        for change in self.breaking_changes + self.safe_changes:
            backward, forward = _change_avro_safety(change)
            if not backward:
                breaks.append(("BACKWARD", change))
            if not forward:
                breaks.append(("FORWARD", change))
        return breaks


def classify_changes(
    diff_result: dict[str, Any],
    left_ir: dict[str, Any],
    right_ir: dict[str, Any],
    current_version: str | None = None,
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

    Two evolution-aware refinements apply to every persisted element (not only
    published event contracts):

    - **Deprecation grace**: a field deprecated and removed at/past its
      ``removal`` version is a safe (expected) removal. This needs
      ``current_version`` to compare against; without it a deprecated removal is
      classified premature (still breaking). The ``protean ir diff`` CLI does
      not yet supply ``current_version``, so this downgrade is currently only
      reachable by callers that pass it explicitly.
    - **Upcaster mitigation**: an event version bump whose old→new path a
      registered upcaster chain covers has its schema-transformation changes
      downgraded to safe (see :func:`_apply_upcaster_mitigation`). This reads
      ``__version__`` from the IR directly and needs no ``current_version``.
    - **Event-sourced aggregate replay coverage**: an event-sourced aggregate is
      rebuilt by replaying its events, so a breaking field removal on it
      downgrades to safe when every rebuilding event whose payload changed has an
      upcaster covering it and at least one long-standing rebuilding event has an
      upcaster-covered version bump (see :func:`_apply_es_aggregate_mitigation`).
      A classic table-backed aggregate is never touched by this path.
    """
    report = CompatibilityReport()

    _classify_clusters(diff_result.get("clusters", {}), report, current_version)
    _classify_projections(diff_result.get("projections", {}), report, current_version)

    # Both mitigation passes read event coverage from one source of truth so they
    # never disagree about whether a given event's version bump is upcaster-covered.
    coverage = _event_upcaster_coverage(left_ir, right_ir)
    # Downgrade breaking changes on an event whose version bump is covered by a
    # registered upcaster (the upcaster transforms old payloads to the new
    # shape), citing the mitigating coverage.
    _apply_upcaster_mitigation(report, coverage)
    # Downgrade breaking field changes on an event-sourced aggregate when the
    # events that rebuild it are all covered.
    _apply_es_aggregate_mitigation(report, left_ir, right_ir, coverage)

    return report


def _events_by_fqn(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Collect every event entry across an IR's clusters, keyed by fqn."""
    events: dict[str, dict[str, Any]] = {}
    for cluster in ir.get("clusters", {}).values():
        events.update(cluster.get("events", {}))
    return events


def _value_objects_by_fqn(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Collect every value object entry across an IR's clusters, keyed by fqn.

    Scanned across all clusters because an event can embed a value object that
    belongs to another aggregate's cluster.
    """
    value_objects: dict[str, dict[str, Any]] = {}
    for cluster in ir.get("clusters", {}).values():
        value_objects.update(cluster.get("value_objects", {}))
    return value_objects


def _type_string_base(entry: dict[str, Any]) -> str:
    """The ``__type__`` string of *entry* without its trailing version segment.

    ``"Ordering.OrderPlaced.v2"`` gives ``"Ordering.OrderPlaced"``. This is the
    key the runtime upcaster chain is registered under: ``TypeManager``
    registers every edge as ``f"{domain.camel_case_name}.{event_name}"`` and
    ``UpcasterChain`` looks a stored message up by the base of its own type
    string. An entry carrying no ``__type__`` gives ``""``, which compares
    equal across the two snapshots and so decides nothing on its own.
    """
    return _VERSION_SUFFIX.sub("", str(entry.get("__type__") or ""))


# Change types that make up a payload-schema transformation an upcaster can
# perform. Orthogonal changes that happen to ride along with the version bump
# (e.g. a visibility flip or the element being removed) are NOT covered.
_UPCASTER_MITIGATABLE = frozenset(
    {
        "field_removed",
        "field_type_changed",
        "required_field_added",
        "type_string_changed",
    }
)

# The subset of the above an event-sourced aggregate can earn: a field removal,
# and nothing else. Three exclusions:
#
# - ``type_string_changed``: an aggregate carries no ``__type__`` version string,
#   so the change never applies to one.
# - ``field_type_changed``: a stored state snapshot can survive it.
#   ``_load_aggregate_current`` builds the aggregate straight from the snapshot's
#   ``to_dict()`` payload and only falls back to replay when that construction
#   raises ``ValidationError``. A removed field raises ("Extra inputs are not
#   permitted"), so the stale snapshot is discarded and the upcaster runs. A type
#   change often does not: ``Float`` -> ``Integer`` coerces a stored ``5.0`` to
#   ``5`` and constructs fine, so the aggregate loads from the pre-change snapshot
#   with the upcaster never consulted, and can hold different state than a full
#   replay would produce.
# - ``required_field_added``: replay never checks the new field is set.
#   ``BaseAggregate._create_for_reconstitution`` initialises every field to
#   ``None`` and ``from_events`` applies the handlers and returns with no
#   required-field validation at the end, so a handler that does not assign the
#   new field leaves it ``None`` and the aggregate loads anyway. Upcaster coverage
#   does not rule that out: an upcaster puts the field in the *event payload*,
#   while the ``@apply`` handler is what would have to read it across to the
#   aggregate, and the IR carries no evidence either way (``apply_handlers`` maps
#   an event fqn to a method name and nothing more). So the add stays breaking
#   until replay validates the field or the IR can show a handler establishes it.
_ES_AGGREGATE_MITIGATABLE = frozenset({"field_removed"})


def _event_upcaster_coverage(
    left_ir: dict[str, Any],
    right_ir: dict[str, Any],
) -> dict[str, tuple[str, str | None]]:
    """Whether a registered upcaster chain reaches each event's current version.

    Returns a map of event fqn to ``(status, citation)``. ``status`` is ``"gap"``
    when any stored version below the new ``__version__`` cannot be upcast to it,
    and ``"covered"`` when the chains do reach it from every prior version *and*
    this diff bumped the version. ``citation`` names the covering upcaster for a
    ``"covered"`` bump (e.g. ``"upcaster OrderPlaced v1->v2"``) and is ``None``
    for a ``"gap"``.

    The gap question is asked of every event, bumped or not. An event standing
    still at v3 whose v1->v2 upcaster was deleted in this diff has stranded its
    stored v1 payloads just as surely as a bump would, and replay of a stream
    carrying them fails. A bumped event is the only one that can be ``"covered"``,
    because coverage is what an upcaster earns for the *new* shape; an event that
    did not bump earns nothing and is absent from the map. A bump whose type
    string base also moved earns nothing either, because the chain is keyed by
    that base. This is the single source of coverage truth both mitigation
    passes read.
    """
    upcasters = right_ir.get("upcasters", {})
    left_events = _events_by_fqn(left_ir)
    right_events = _events_by_fqn(right_ir)

    coverage: dict[str, tuple[str, str | None]] = {}
    for event_fqn, right_entry in right_events.items():
        left_entry = left_events.get(event_fqn)
        if left_entry is None:
            continue
        left_v = left_entry.get("__version__")
        right_v = right_entry.get("__version__")
        if not isinstance(right_v, int):
            continue
        # Keyed by event base name (matching the `Domain.Name` type string and
        # `_diagnose_upcaster_gap`). Two events sharing a class name across
        # aggregates would pool edges — a pre-existing name-based limitation;
        # TODO(3.4.6): key by the qualified type string once available in the IR.
        edges = [
            (e["from_version"], e["to_version"])
            for e in upcasters.get(right_entry.get("name", ""), [])
        ]
        # Every stored version has to reach right_v, not just left_v. The old
        # IR's version is only the newest payload in the store; v1 payloads
        # written before an earlier bump are still there. This is the same rule
        # `UPCASTER_GAP` applies at build time, so the two never disagree: an
        # event bumped v2->v3 whose v1->v2 edge is gone strands its v1 payloads,
        # and a change riding on that bump stays breaking.
        if missing_upcaster_source_versions(edges, right_v):
            coverage[event_fqn] = ("gap", None)
            continue
        if not isinstance(left_v, int) or right_v <= left_v:
            continue
        # The chain is keyed by the type string's base, not by the event class.
        # `TypeManager._populate_chain` registers every edge under
        # `f"{domain.camel_case_name}.{event_name}"`, and a stored message is
        # looked up by the base of the type string it was written with. Move
        # that base (rename the domain, rename the event class) and a stored
        # `Ordering.OrderPlaced.v1` message reaches neither a chain nor a class,
        # whatever upcasters are registered for the new base. The bump earns
        # nothing then, so no coverage is granted and the change stays breaking.
        if _type_string_base(left_entry) != _type_string_base(right_entry):
            continue
        coverage[event_fqn] = (
            "covered",
            f"upcaster {right_entry.get('name', '')} v{left_v}->v{right_v}",
        )
    return coverage


# Field attributes that take no part in constructing a value, so moving one
# cannot make a stored payload fail. Every other attribute counts: type,
# required, max_length, choices and the rest all decide whether a value is
# accepted, and an attribute added to the IR later counts until it is listed
# here. The default has to be "this can reject a payload", because the answer
# feeds a downgrade. ``renamed_from`` is only half inert (adding an alias is,
# dropping one is not), so it sits here and `_aliases_dropped` reads it instead.
_REPLAY_INERT_FIELD_ATTRS = frozenset({"deprecated", "description", "renamed_from"})


def _aliases_dropped(
    left_field: dict[str, Any],
    right_field: dict[str, Any],
) -> bool:
    """Whether *right_field* stopped answering to an alias *left_field* declared.

    Adding a ``renamed_from`` alias is inert for replay: no stored payload uses
    the name being aliased away from, so nothing in the store changes meaning.
    Dropping one is not inert. Payloads written under that old key are still in
    the event store, alias resolution no longer maps the key, and strict
    deserialization rejects it as an extra input.
    """
    return bool(
        set(left_field.get("renamed_from") or [])
        - set(right_field.get("renamed_from") or [])
    )


def _field_shape_moved(
    left_field: dict[str, Any],
    right_field: dict[str, Any],
) -> bool:
    """Whether a field moved in a way a payload may fail.

    *left_field* and *right_field* are the same field on either side of the diff:
    either under the same name, or paired by a declared rename.
    """
    if _aliases_dropped(left_field, right_field):
        return True
    return any(
        left_field.get(attr) != right_field.get(attr)
        for attr in (left_field.keys() | right_field.keys()) - _REPLAY_INERT_FIELD_ATTRS
    )


# Field kinds whose value is an embedded value object payload rather than a
# scalar. The field entry names its value object as a ``target`` fqn and says
# nothing about that value object's own fields, so the shape a stored payload
# has to satisfy is only reachable by following the target.
_VALUE_OBJECT_FIELD_KINDS = frozenset({"value_object", "value_object_list"})


def _embedded_value_object_moved(
    left_field: dict[str, Any],
    right_field: dict[str, Any],
    left_value_objects: dict[str, dict[str, Any]],
    right_value_objects: dict[str, dict[str, Any]],
    seen: frozenset[str],
) -> bool:
    """Whether the value object *right_field* embeds changed shape under it.

    A value object field serializes as a nested dict of that value object's
    fields, and is deserialized by constructing the value object from it. So
    removing ``Address.zip`` fails every stored payload carrying a zip, exactly
    as removing a field straight off the event would, while the event's own
    field entry (``{"kind": "value_object", "target": "...Address"}``) is
    byte-identical across the diff. The target has to be followed to see it.

    *seen* carries the targets already being compared further up the stack, so a
    value object that embeds itself terminates instead of recursing forever.
    """
    if left_field.get("kind") not in _VALUE_OBJECT_FIELD_KINDS:
        return False
    target = right_field.get("target")
    # A moved ``kind`` or ``target`` is already a shape move by the field's own
    # attributes, so this only has to answer the stable-target case.
    if not isinstance(target, str) or target in seen:
        return False
    left_target = left_value_objects.get(target)
    right_target = right_value_objects.get(target)
    if left_target is None or right_target is None:
        # The value object is registered on one side only, so there is no pair
        # of shapes to compare and no evidence the stored nested payload still
        # constructs. That reads as moved: the answer feeds a downgrade.
        return left_target is not right_target
    return _payload_fields_moved(
        left_target.get("fields", {}),
        right_target.get("fields", {}),
        left_value_objects,
        right_value_objects,
        seen | {target},
    )


def _payload_fields_moved(
    left_fields: dict[str, Any],
    right_fields: dict[str, Any],
    left_value_objects: dict[str, dict[str, Any]],
    right_value_objects: dict[str, dict[str, Any]],
    seen: frozenset[str] = frozenset(),
) -> bool:
    """Whether a payload written for *left_fields* can still satisfy *right_fields*.

    Used for an event's own fields and, through
    :func:`_embedded_value_object_moved`, for the fields of every value object
    those fields embed.
    """
    removed = {
        name: field for name, field in left_fields.items() if name not in right_fields
    }
    added = {
        name: field for name, field in right_fields.items() if name not in left_fields
    }
    renames = _detect_field_renames(added, removed)
    renamed_new = set(renames.values())
    if set(removed) - set(renames):
        return True
    if any(
        name not in renamed_new and field.get("required") and "default" not in field
        for name, field in added.items()
    ):
        return True
    # Every old field name paired with the right-side field that has to accept
    # its stored values: the same name, or the new name a rename aliases it to.
    paired = {name: name for name in left_fields.keys() & right_fields.keys()}
    paired.update(renames)
    return any(
        _field_shape_moved(left_fields[old_name], right_fields[new_name])
        or _embedded_value_object_moved(
            left_fields[old_name],
            right_fields[new_name],
            left_value_objects,
            right_value_objects,
            seen,
        )
        for old_name, new_name in paired.items()
    )


def _payload_changed_events(
    left_ir: dict[str, Any],
    right_ir: dict[str, Any],
) -> set[str]:
    """Event fqns whose new shape a stored old payload can no longer satisfy.

    Read from the two IRs rather than from the classified report. ``diff_ir``
    records every field-attribute delta, but :func:`_classify_field_changes`
    only emits a change for a few of them: a field that goes optional to
    required, or loses its default, produces no change at all, and yet every
    historical payload that omits it fails strict event construction before
    replay can start. Severity is the wrong question too: a field removal the
    deprecation grace already called safe still leaves that field in every
    payload sitting in the event store, and strict deserialization rejects it
    ("Extra inputs are not permitted"). Only an upcaster drops it.

    An event counts as changed when a field was removed, when a required field
    with no default was added (a stored payload omits it), when a field's shape
    moved (see :data:`_REPLAY_INERT_FIELD_ATTRS`), when a value object one of
    its fields embeds moved in any of those ways (see
    :func:`_embedded_value_object_moved`), or when the ``__type__`` string
    changed, which leaves a stored message unable to resolve back to the event
    class.

    A declared rename is not a removal here: the alias resolves the old name in
    old payloads. It is still shape-compared, under the new name. The alias only
    routes the old key to the new field; that field then has to accept the stored
    value, so a rename that also changes the type or another validating
    constraint fails old payloads just as an in-place change would.
    """
    left_events = _events_by_fqn(left_ir)
    right_events = _events_by_fqn(right_ir)
    left_value_objects = _value_objects_by_fqn(left_ir)
    right_value_objects = _value_objects_by_fqn(right_ir)

    changed: set[str] = set()
    for event_fqn, right_entry in right_events.items():
        left_entry = left_events.get(event_fqn)
        if left_entry is None:
            continue
        if left_entry.get("__type__") != right_entry.get("__type__"):
            changed.add(event_fqn)
            continue

        if _payload_fields_moved(
            left_entry.get("fields", {}),
            right_entry.get("fields", {}),
            left_value_objects,
            right_value_objects,
        ):
            changed.add(event_fqn)
    return changed


def _apply_upcaster_mitigation(
    report: CompatibilityReport,
    coverage: dict[str, tuple[str, str | None]],
) -> None:
    """Downgrade breaking changes on events whose version bump an upcaster covers.

    Registered upcaster chains that reach an event's new ``__version__`` from
    every prior version transform stored payloads to the new shape, so the
    schema-transformation changes that make up that version bump (field removals,
    type changes, required-field additions, the ``__type__`` version-string bump)
    are no longer breaking. Only those change types are downgraded. An orthogonal
    change such as a public→internal visibility flip is left breaking. Each
    downgraded change is moved to ``safe_changes`` with ``mitigated_by`` set to
    the covering upcaster. *coverage* is the map from :func:`_event_upcaster_coverage`.
    """
    if not report.breaking_changes:
        return

    mitigation = {
        event_fqn: citation
        for event_fqn, (status, citation) in coverage.items()
        if status == "covered"
    }
    if not mitigation:
        return

    still_breaking: list[CompatibilityChange] = []
    for change in report.breaking_changes:
        citation = mitigation.get(change.element_fqn)
        # Only downgrade schema-transformation changes the upcaster actually
        # performs; leave orthogonal changes (e.g. a visibility flip) breaking.
        if citation is None or change.change_type not in _UPCASTER_MITIGATABLE:
            still_breaking.append(change)
            continue
        change.severity = "safe"
        change.mitigated_by = citation
        report.safe_changes.append(change)
    report.breaking_changes = still_breaking


def _apply_es_aggregate_mitigation(
    report: CompatibilityReport,
    left_ir: dict[str, Any],
    right_ir: dict[str, Any],
    coverage: dict[str, tuple[str, str | None]],
) -> None:
    """Downgrade a breaking field removal on an event-sourced aggregate that earned
    replay coverage: one rebuilding event has an upcaster-covered version bump and
    every rebuilding event whose payload changed is upcaster-covered.

    An event-sourced aggregate is rebuilt by replaying the events its
    ``apply_handlers`` name. So a breaking field removal on it is earned-safe on
    the same terms as those events. Two conditions: every rebuilding event whose
    payload schema changed must have a version bump an upcaster covers, and at
    least one event that already rebuilt the aggregate in the old snapshot must
    have such a bump. A stored version no upcaster chain reaches (a gap, with or
    without a bump in this diff), a payload change made without a version bump, or
    no bump at all leaves the aggregate breaking, because nothing was earned. That
    first condition is answered from the two IRs, by
    :func:`_payload_changed_events`: the classified report names only some of the
    shape changes that strand a stored payload, so reading it would miss the rest.
    A version bump covered on an ``@apply`` handler added in this diff earns
    nothing either: that handler never rebuilt historical state, so its coverage
    says nothing about the old aggregate. Coverage is at aggregate granularity:
    the IR carries no per-field provenance, so a covered
    bump on any rebuilding event downgrades the aggregate's field removal, not only
    the fields that event happens to populate. A classic (non-event-sourced)
    aggregate is never touched by this path; its breaking field changes stay
    breaking, and ``exclude`` is the only escape hatch there.

    A field type change and a required-field add are not on the earned list. A
    stored *state* snapshot can survive a type change and skip replay entirely,
    and replay runs no required-field validation, so neither one is proven safe by
    upcaster coverage. See :data:`_ES_AGGREGATE_MITIGATABLE` for both arguments.

    The aggregate must be event-sourced in *both* snapshots, and must still name
    the same ``stream_category`` and the same ``identity_field``. A classic
    aggregate converted to event sourcing in this diff persisted its old state as
    table rows, which replay cannot reconstruct. Both halves of the stream name
    ``f"{stream_category}-{identifier}"`` have to hold still: an aggregate whose
    stream category moved leaves its whole history behind under the old category,
    and one whose identity moved to another field asks for a stream keyed by a
    different value. Either way replay finds no events at all, nothing is earned,
    and its field changes stay breaking. Likewise a rebuilding
    event that fell out of replay in this diff is treated as a gap. That happens
    in two shapes: its ``@apply`` handler was
    dropped, so historical events of that type sit in the store with no handler
    (see :meth:`BaseAggregate._apply_handler`), or the event was removed from the
    domain outright, so a stored message of that type no longer resolves to an
    event class at all. *coverage* is the map from
    :func:`_event_upcaster_coverage`.
    """
    if not report.breaking_changes:
        return

    left_clusters = left_ir.get("clusters", {})
    # Events this diff dropped from the domain entirely, read from the two IRs
    # rather than inferred from the handler maps: a handler can outlive the event
    # it applies, and it is the event registration replay needs to resolve a
    # stored message back to a class.
    removed_events = set(_events_by_fqn(left_ir)) - set(_events_by_fqn(right_ir))
    # Every event a stored payload can no longer satisfy, read from the two IRs.
    # `coverage` only ever reports "covered" for a version bump, so an event whose
    # shape moved without one is absent from it, and that absence does not mean
    # the payload is unchanged.
    payload_changed_events = _payload_changed_events(left_ir, right_ir)
    # Per aggregate fqn, the citation to attach when its field changes are earned-safe.
    aggregate_citation: dict[str, str] = {}
    for fqn, cluster in right_ir.get("clusters", {}).items():
        aggregate = cluster.get("aggregate", {})
        options = aggregate.get("options", {})
        if not options.get("is_event_sourced"):
            continue
        # The aggregate must also have been event-sourced in the old snapshot.
        # A classic->event-sourced conversion stored its old state as table rows,
        # which replay cannot rebuild, so no field change is earned-safe.
        left_aggregate = left_clusters.get(fqn, {}).get("aggregate", {})
        left_options = left_aggregate.get("options", {})
        if not left_options.get("is_event_sourced"):
            continue
        # Replay reads the stream the aggregate names: `_load_aggregate_current`
        # pages `f"{stream_category}-{identifier}"`. Move the category and every
        # historical event is left behind under the old one, so replay of an
        # existing aggregate finds no events at all and reports it missing. No
        # upcaster earns anything back from that, so the field changes stay
        # breaking.
        if left_options.get("stream_category") != options.get("stream_category"):
            continue
        # The identifier half of that stream name is the value of whichever
        # field carries the identity. Point the identity at a different field
        # and every existing aggregate's events stay under a stream keyed by the
        # old field's value, while a load now asks for one keyed by the new
        # field's. Replay finds nothing, same as a category move, so nothing is
        # earned. A field merely renamed in place is caught here too: the IR
        # records the identity as a name, and reading a rename as continuity
        # would be guessing.
        if left_aggregate.get("identity_field") != aggregate.get("identity_field"):
            continue
        rebuilding_events = aggregate.get("apply_handlers", {})
        if not rebuilding_events:
            continue
        # A rebuilding event falls out of replay in two shapes. Its @apply handler
        # is dropped, leaving historical events in the store with no handler. Or
        # the event itself is gone from the domain, so a stored message of that
        # type no longer resolves to a class and replay cannot even deserialize it.
        # Either shape is a gap: nothing is earned for this aggregate.
        left_rebuilding_events = left_aggregate.get("apply_handlers", {})
        if any(
            event_fqn not in rebuilding_events or event_fqn in removed_events
            for event_fqn in left_rebuilding_events
        ):
            continue

        covering_citations: list[str] = []
        has_gap = False
        for event_fqn in rebuilding_events:
            status, citation = coverage.get(event_fqn, ("unchanged", None))
            # A payload change is only survivable when an upcaster covers it.
            if status == "gap" or (
                event_fqn in payload_changed_events and status != "covered"
            ):
                has_gap = True
                break
            # Only an event that already rebuilt this aggregate earns the
            # downgrade. A handler added in this diff never applied to historical
            # state, so a covered bump on its event proves nothing about replay.
            if (
                status == "covered"
                and citation is not None
                and event_fqn in left_rebuilding_events
            ):
                covering_citations.append(citation)
        # Downgrade only when every changed rebuilding event is covered and at
        # least one long-standing rebuilding event was bumped-and-covered.
        if has_gap or not covering_citations:
            continue
        aggregate_citation[fqn] = ", ".join(sorted(covering_citations))

    if not aggregate_citation:
        return

    still_breaking: list[CompatibilityChange] = []
    for change in report.breaking_changes:
        citation = aggregate_citation.get(change.element_fqn)
        # Only downgrade the field removal replay can reconstruct; leave every
        # other change (a type change, a required add, a removed aggregate) breaking.
        if citation is None or change.change_type not in _ES_AGGREGATE_MITIGATABLE:
            still_breaking.append(change)
            continue
        change.severity = "safe"
        change.mitigated_by = citation
        report.safe_changes.append(change)
    report.breaking_changes = still_breaking


def _classify_clusters(
    clusters_diff: dict[str, Any],
    report: CompatibilityReport,
    current_version: str | None = None,
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
            _classify_element_delta(
                agg_delta, cluster_fqn, "AGGREGATE", report, current_version
            )

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
                _classify_element_delta(
                    element_delta, fqn, element_type, report, current_version
                )


def _classify_projections(
    projections_diff: dict[str, Any],
    report: CompatibilityReport,
    current_version: str | None = None,
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
                proj_element_delta, proj_fqn, "PROJECTION", report, current_version
            )


def _classify_element_delta(
    element_delta: dict[str, Any],
    fqn: str,
    element_type: str,
    report: CompatibilityReport,
    current_version: str | None = None,
) -> None:
    _classify_field_changes(
        element_delta.get("fields", {}), fqn, element_type, report, current_version
    )
    _classify_attribute_changes(element_delta.get("attributes", {}), fqn, report)


def _detect_field_renames(
    added: dict[str, Any],
    removed: Collection[str],
) -> dict[str, str]:
    """Return ``{old_name: new_name}`` for declared renames in a fields diff.

    An added field whose ``renamed_from`` names a removed field is a rename,
    not a remove+add: the alias resolves old stored payloads, so it is a safe
    change. ``removed`` is any container of removed field names. Each removed
    name is claimed by at most one rename.
    """
    renames: dict[str, str] = {}
    for new_name, field_dict in added.items():
        for old_name in field_dict.get("renamed_from") or []:
            if old_name in removed and old_name not in renames:
                renames[old_name] = new_name
    return renames


def _has_static_default(field: dict[str, Any]) -> bool:
    """Whether *field* carries a default Avro can emit as a schema default.

    A callable default (the ``<callable>`` IR sentinel) is not emittable, so it
    does not count — matching ``generators/avro.py``'s ``has_default`` rule.
    """
    return "default" in field and field["default"] != _CALLABLE_DEFAULT


def _removal_forward_safe(old_field: dict[str, Any]) -> bool:
    """Whether removing (or renaming) away *old_field* keeps forward compatibility.

    An old-schema reader can decode new data that lacks the old field only when
    the field was optional or carried a static default. Identifier fields count
    as required (Avro encodes them as required — see ``generators/avro.py``).
    """
    is_required = old_field.get("required") or old_field.get("identifier")
    return not is_required or _has_static_default(old_field)


def _classify_field_changes(
    fields_diff: dict[str, Any],
    fqn: str,
    element_type: str,
    report: CompatibilityReport,
    current_version: str | None = None,
) -> None:
    added = fields_diff.get("added", {})
    removed = fields_diff.get("removed", {})

    # Declared renames are safe (the alias covers old payloads) and suppress
    # the remove+add pair they would otherwise be diffed as — unless the rename
    # also changes the field type, which old payloads cannot satisfy.
    renames = _detect_field_renames(added, removed)
    renamed_new = set(renames.values())
    for old_name, new_name in renames.items():
        old_type = removed[old_name].get("type")
        new_type = added[new_name].get("type")
        if old_type != new_type:
            report.breaking_changes.append(
                CompatibilityChange(
                    severity="breaking",
                    element_fqn=fqn,
                    change_type="field_type_changed",
                    message=(
                        f"Field '{old_name}' renamed to '{new_name}' with a type "
                        f"change from '{old_type}' to '{new_type}' in "
                        f"{element_type} '{fqn}'"
                    ),
                )
            )
        else:
            report.safe_changes.append(
                CompatibilityChange(
                    severity="safe",
                    element_fqn=fqn,
                    change_type="field_renamed",
                    message=(
                        f"Field '{old_name}' renamed to '{new_name}' in "
                        f"{element_type} '{fqn}'"
                    ),
                    # Backward-safe via the emitted Avro ``aliases``; forward
                    # safety depends on whether an old reader can fill the
                    # now-absent old name (optional or defaulted).
                    forward_safe=_removal_forward_safe(removed[old_name]),
                )
            )

    for field_name, field_dict in added.items():
        if field_name in renamed_new:
            continue
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
                    # A *callable* default cannot be emitted as an Avro schema
                    # default, so a new reader has no value for old data missing
                    # the field — not backward-safe in that case.
                    backward_safe=_has_static_default(field_dict),
                )
            )
        else:
            report.safe_changes.append(
                CompatibilityChange(
                    severity="safe",
                    element_fqn=fqn,
                    change_type="optional_field_added",
                    message=(
                        f"Optional field '{field_name}' added to {element_type} '{fqn}'"
                    ),
                )
            )

    for field_name in removed:
        if field_name in renames:
            continue
        # Deprecation-aware removal: a field deprecated and past its removal
        # version is a safe (expected) removal. This now applies to every
        # persisted element — including internal and event-sourced events,
        # which previously only got raw (always-breaking) classification (the
        # deprecation grace was limited to published contracts).
        deprecated = removed[field_name].get("deprecated")
        classification = _classify_removal(deprecated, current_version)
        forward_safe = _removal_forward_safe(removed[field_name])
        if classification == "expected_removal":
            report.safe_changes.append(
                CompatibilityChange(
                    severity="safe",
                    element_fqn=fqn,
                    change_type="field_removed",
                    message=(
                        f"Field '{field_name}' removed from {element_type} '{fqn}' "
                        f"(expected removal, deprecated since "
                        f"v{deprecated['since']})"
                    ),
                    forward_safe=forward_safe,
                )
            )
        else:
            # Breaking (premature/unexpected). State the deprecation facts
            # rather than asserting the removal is "before its removal version"
            # — which cannot be known without a removal version and a
            # current_version (which the `ir diff` CLI does not yet supply).
            message = f"Field '{field_name}' removed from {element_type} '{fqn}'"
            if deprecated:
                removal = deprecated.get("removal")
                if removal:
                    message += (
                        f" (deprecated since v{deprecated['since']}, "
                        f"scheduled for removal in v{removal})"
                    )
                else:
                    message += (
                        f" (deprecated since v{deprecated['since']}, "
                        f"no removal version set)"
                    )
            report.breaking_changes.append(
                CompatibilityChange(
                    severity="breaking",
                    element_fqn=fqn,
                    change_type="field_removed",
                    message=message,
                    forward_safe=forward_safe,
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
