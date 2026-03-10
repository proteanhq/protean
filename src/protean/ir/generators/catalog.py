"""Event and command catalog generator.

Produces human-readable Markdown tables describing every event and command
in the domain, grouped by aggregate cluster.  Each message includes its
type string, version, published/fact-event flags, and a field table with
Type / Required / Constraints columns.

A summary section at the end lists all published event contracts.

Usage::

    from protean.ir.generators.catalog import generate_catalog

    md = generate_catalog(ir)
"""

from __future__ import annotations

from typing import Any

from protean.ir.generators.base import field_type_label, short_name


# ---------------------------------------------------------------------------
# Field table helpers
# ---------------------------------------------------------------------------


def _constraints_summary(field: dict[str, Any]) -> str:
    """Build a compact constraints string from an IR field dict."""
    parts: list[str] = []
    if field.get("identifier"):
        parts.append("identifier")
    if field.get("unique") and not field.get("identifier"):
        parts.append("unique")
    if field.get("max_length") is not None:
        parts.append(f"max_length={field['max_length']}")
    if field.get("min_length") is not None:
        parts.append(f"min_length={field['min_length']}")
    if field.get("max_value") is not None:
        parts.append(f"max_value={field['max_value']}")
    if field.get("min_value") is not None:
        parts.append(f"min_value={field['min_value']}")
    if field.get("choices"):
        parts.append(f"choices={field['choices']}")
    return ", ".join(parts) if parts else "\u2014"


def _render_field_table(fields: dict[str, dict[str, Any]]) -> list[str]:
    """Render a Markdown table of fields with Type, Required, Constraints."""
    if not fields:
        return ["_No fields._", ""]

    lines: list[str] = [
        "| Field | Type | Required | Constraints |",
        "|-------|------|----------|-------------|",
    ]
    for fname, fspec in sorted(fields.items()):
        ftype = field_type_label(fspec)
        required = "Yes" if fspec.get("required") else "No"
        constraints = _constraints_summary(fspec)
        lines.append(f"| {fname} | {ftype} | {required} | {constraints} |")
    lines.append("")  # trailing blank line
    return lines


# ---------------------------------------------------------------------------
# Message renderers
# ---------------------------------------------------------------------------


def _render_event(fqn: str, event: dict[str, Any]) -> list[str]:
    """Render a single event entry as Markdown."""
    name = short_name(fqn)
    type_str = event.get("__type__", "\u2014")
    version = event.get("__version__", "\u2014")
    published = "Yes" if event.get("published") else "No"
    is_fact = "Yes" if event.get("is_fact_event") else "No"

    lines: list[str] = [
        f"#### {name}",
        "",
        f"- **Type**: `{type_str}`",
        f"- **Version**: {version}",
        f"- **Published**: {published}",
        f"- **Fact Event**: {is_fact}",
        "",
    ]
    lines.extend(_render_field_table(event.get("fields", {})))
    return lines


def _render_command(fqn: str, command: dict[str, Any]) -> list[str]:
    """Render a single command entry as Markdown."""
    name = short_name(fqn)
    type_str = command.get("__type__", "\u2014")
    version = command.get("__version__", "\u2014")

    lines: list[str] = [
        f"#### {name}",
        "",
        f"- **Type**: `{type_str}`",
        f"- **Version**: {version}",
        "",
    ]
    lines.extend(_render_field_table(command.get("fields", {})))
    return lines


# ---------------------------------------------------------------------------
# Cluster section renderer
# ---------------------------------------------------------------------------


def _render_cluster_section(cluster_fqn: str, cluster: dict[str, Any]) -> list[str]:
    """Render events and commands for a single aggregate cluster."""
    agg_name = short_name(cluster_fqn)
    lines: list[str] = [
        f"## {agg_name} (`{cluster_fqn}`)",
        "",
    ]

    # Events
    events = cluster.get("events", {})
    if events:
        lines.append("### Events")
        lines.append("")
        for evt_fqn, evt in sorted(events.items()):
            lines.extend(_render_event(evt_fqn, evt))

    # Commands
    commands = cluster.get("commands", {})
    if commands:
        lines.append("### Commands")
        lines.append("")
        for cmd_fqn, cmd in sorted(commands.items()):
            lines.extend(_render_command(cmd_fqn, cmd))

    return lines


# ---------------------------------------------------------------------------
# Contract summary
# ---------------------------------------------------------------------------


def _render_contract_summary(ir: dict[str, Any]) -> list[str]:
    """Render the published event contracts summary table."""
    contracts = ir.get("contracts", {}).get("events", [])
    if not contracts:
        return []

    lines: list[str] = [
        "---",
        "",
        "## Published Event Contracts",
        "",
        "| Event | Type | Version |",
        "|-------|------|---------|",
    ]
    for contract in sorted(contracts, key=lambda c: c.get("fqn", "")):
        name = short_name(contract.get("fqn", ""))
        type_str = contract.get("type", "\u2014")
        version = contract.get("version", "\u2014")
        lines.append(f"| {name} | `{type_str}` | {version} |")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_catalog(ir: dict[str, Any]) -> str:
    """Generate a Markdown event and command catalog from the IR.

    The catalog is grouped by aggregate cluster.  Each event shows its
    type string, version, published/fact-event flags, and a field table.
    Commands follow the same structure (without published/fact flags).

    A trailing section lists all published event contracts.

    Args:
        ir: The full IR dict.

    Returns:
        A string containing the Markdown catalog.
    """
    clusters = ir.get("clusters", {})
    if not clusters:
        return "# Event & Command Catalog\n\n_No clusters found._\n"

    lines: list[str] = ["# Event & Command Catalog", ""]

    for cfqn, cluster in sorted(clusters.items()):
        lines.extend(_render_cluster_section(cfqn, cluster))

    lines.extend(_render_contract_summary(ir))

    return "\n".join(lines)
