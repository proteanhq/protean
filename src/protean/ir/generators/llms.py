"""Versioned ``llms.txt`` context pack generator.

Produces a two-layer context pack for LLM agents, following the llms.txt
convention (https://llmstxt.org): an H1 naming Protean and its version, a
one-line summary blockquote, and a "Core documentation" section of Markdown
links to the published docs site.

The pack has two layers:

- **Framework layer** (always present): the title, version, summary, and the
  curated core-documentation links. It is constant for a given Protean version,
  so it is byte-stable by construction.
- **Project overlay** (present only when an IR is passed): a section derived
  from the loaded IR listing the project's own aggregate clusters, their
  commands and events, their command and event handlers, and its projections,
  so an agent sees the actual shape of the project alongside the framework docs.

The overlay is keyed only on stable, structural parts of the IR. It never reads
``generated_at`` or ``checksum`` (both fold in a timestamp), and it sorts every
dict traversal, so generating twice for the same IR yields identical bytes.

Usage::

    from protean.ir.generators.llms import generate_llms_txt

    txt = generate_llms_txt(None, version="0.17.0")      # framework layer only
    txt = generate_llms_txt(ir_data, version="0.17.0")   # + project overlay
"""

from __future__ import annotations

from typing import Any

from protean.ir.generators.base import short_name

# ---------------------------------------------------------------------------
# Framework layer
# ---------------------------------------------------------------------------

_DOCS_BASE = "https://docs.proteanhq.com"

_SUMMARY = (
    "Protean is a Python framework for building domain-driven, event-native "
    "applications that can evolve without a rewrite."
)

# Curated links to the core documentation the pack points an agent at:
# aggregate clusters, events, command and event handlers, projections, and
# event evolution. Each entry is a (label, docs-site path) pair; paths use
# mkdocs directory URLs.
_CORE_DOCS: tuple[tuple[str, str], ...] = (
    ("Aggregate clusters", "guides/domain-definition/aggregates/"),
    ("Events", "guides/domain-definition/events/"),
    ("Commands and command handlers", "guides/change-state/command-handlers/"),
    ("Event handlers", "guides/consume-state/event-handlers/"),
    ("Projections", "guides/consume-state/projections/"),
    ("Event evolution", "guides/evolving-events/"),
)


def _framework_layer(version: str) -> list[str]:
    """Render the version-stamped framework layer.

    Constant for a given *version*: the title carries the version, the summary
    is fixed, and the links are a fixed curated set. Nothing here reads the IR.
    """
    lines: list[str] = [
        f"# Protean {version}",
        "",
        f"> {_SUMMARY}",
        "",
        "## Core documentation",
        "",
    ]
    for label, path in _CORE_DOCS:
        lines.append(f"- [{label}]({_DOCS_BASE}/{path})")
    return lines


# ---------------------------------------------------------------------------
# Project overlay
# ---------------------------------------------------------------------------


def _handler_names(cluster: dict[str, Any]) -> list[str]:
    """Return the sorted short names of a cluster's command and event handlers."""
    names: set[str] = set()
    for section in ("command_handlers", "event_handlers"):
        for fqn in cluster.get(section, {}):
            names.add(short_name(fqn))
    return sorted(names)


def _cluster_lines(cluster_fqn: str, cluster: dict[str, Any]) -> list[str]:
    """Render one aggregate cluster's aggregate, commands, events, and handlers."""
    aggregate = cluster.get("aggregate", {})
    agg_name = aggregate.get("name") or short_name(cluster_fqn)

    lines = [f"- **{agg_name}** (`{cluster_fqn}`)"]

    commands = sorted(short_name(fqn) for fqn in cluster.get("commands", {}))
    if commands:
        lines.append(f"  - Commands: {', '.join(commands)}")

    events = sorted(short_name(fqn) for fqn in cluster.get("events", {}))
    if events:
        lines.append(f"  - Events: {', '.join(events)}")

    handlers = _handler_names(cluster)
    if handlers:
        lines.append(f"  - Handlers: {', '.join(handlers)}")

    return lines


def _project_overlay(ir_data: dict[str, Any]) -> list[str]:
    """Render the IR-derived project overlay.

    Lists the project's aggregate clusters (with their commands, events, and
    handlers) and its projections. Derives only from stable structural parts of
    the IR and sorts every traversal, so it is byte-stable run to run.
    """
    domain_name = ir_data.get("domain", {}).get("name", "")
    heading = f"Project: {domain_name}" if domain_name else "Project"

    lines: list[str] = ["", f"## {heading}", ""]

    clusters = ir_data.get("clusters", {})
    lines.append("### Aggregate clusters")
    lines.append("")
    if clusters:
        for cfqn in sorted(clusters):
            lines.extend(_cluster_lines(cfqn, clusters[cfqn]))
    else:
        lines.append("_No aggregate clusters._")

    projections = ir_data.get("projections", {})
    if projections:
        lines.append("")
        lines.append("### Projections")
        lines.append("")
        for pfqn in sorted(projections):
            proj = projections[pfqn].get("projection", {})
            name = proj.get("name") or short_name(pfqn)
            lines.append(f"- **{name}** (`{pfqn}`)")

    return lines


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_llms_txt(ir_data: dict[str, Any] | None, *, version: str) -> str:
    """Build the versioned ``llms.txt`` context pack.

    Always renders the framework layer: an H1 naming Protean and *version*, a
    one-line summary blockquote, and the curated core-documentation links. When
    *ir_data* is not ``None``, appends a project overlay derived from the IR.
    An empty dict counts as an IR source, so it renders the overlay with its
    empty-section sentinel instead of being skipped.

    The output is deterministic: the framework layer is constant per version,
    and the overlay sorts every traversal and reads no volatile IR field
    (``generated_at``/``checksum``), so generating twice for the same input
    yields byte-identical output.

    Args:
        ir_data: The full IR dict, or ``None`` for the framework layer alone.
        version: The Protean version string to stamp into the title.

    Returns:
        The ``llms.txt`` content as a single string.
    """
    lines = _framework_layer(version)
    if ir_data is not None:
        lines.extend(_project_overlay(ir_data))
    return "\n".join(lines) + "\n"
