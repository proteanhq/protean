"""CLI commands for documentation generation.

Usage::

    # Generate all docs from a live domain
    protean docs generate --domain=my_app

    # Generate from an IR JSON file
    protean docs generate --ir=domain-ir.json

    # Generate only cluster diagrams
    protean docs generate --domain=my_app --type=clusters

    # Generate raw Mermaid (no Markdown fences)
    protean docs generate --domain=my_app --type=events --format=mermaid

    # Write output to a file
    protean docs generate --domain=my_app --output=docs/architecture.md

    # Filter to a specific cluster
    protean docs generate --domain=my_app --type=clusters --cluster=app.Order

    # Run the mkdocs live preview server
    protean docs preview
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import typer
from rich import print
from typing_extensions import Annotated

from protean.cli._ir_utils import load_domain_ir, load_ir_file
from protean.ir.generators.base import mermaid_fence

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback():
    """Generate and preview architecture documentation."""


@app.command()
def preview():
    """Run a live preview server"""
    try:
        subprocess.call(
            [
                sys.executable,
                "-m",
                "mkdocs",
                "serve",
                "--livereload",
                "--dev-addr=0.0.0.0:8000",
            ]
        )
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# ``protean docs generate``
# ---------------------------------------------------------------------------

_VALID_TYPES = ("clusters", "events", "handlers", "catalog", "all")


@app.command()
def generate(
    domain: Annotated[
        str,
        typer.Option(
            "--domain",
            "-d",
            help="Path to the domain module (e.g. 'my_app.domain')",
        ),
    ] = "",
    ir: Annotated[
        str,
        typer.Option(
            "--ir",
            help="Path to an IR JSON file",
        ),
    ] = "",
    type: Annotated[
        str,
        typer.Option(
            "--type",
            "-t",
            help="Generator type: clusters, events, handlers, catalog, or all (default)",
        ),
    ] = "all",
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: 'markdown' (fenced code blocks) or 'mermaid' (raw diagrams)",
        ),
    ] = "markdown",
    output: Annotated[
        str,
        typer.Option(
            "--output",
            "-o",
            help="Write output to file instead of stdout",
        ),
    ] = "",
    cluster: Annotated[
        str,
        typer.Option(
            "--cluster",
            help="Filter to a specific cluster FQN (for --type=clusters or --type=all)",
        ),
    ] = "",
) -> None:
    """Generate architecture documentation from a Protean domain or IR file."""
    # --- Validate inputs --------------------------------------------------
    if not domain and not ir:
        print("[red]Error:[/red] provide either --domain or --ir")
        raise typer.Abort()

    if domain and ir:
        print("[red]Error:[/red] --domain and --ir are mutually exclusive")
        raise typer.Abort()

    if type not in _VALID_TYPES:
        print(
            f"[red]Error:[/red] invalid --type: {type!r}. "
            f"Choose from: {', '.join(_VALID_TYPES)}"
        )
        raise typer.Abort()

    if format not in ("markdown", "mermaid"):
        print(
            f"[red]Error:[/red] invalid --format: {format!r}. "
            "Choose 'markdown' or 'mermaid'"
        )
        raise typer.Abort()

    if cluster and type not in ("clusters", "all"):
        print(
            "[red]Error:[/red] --cluster can only be used with --type=clusters or --type=all"
        )
        raise typer.Abort()

    if format == "mermaid" and type == "catalog":
        print(
            "[red]Error:[/red] --format=mermaid is not supported for --type=catalog "
            "(catalog outputs Markdown tables, not Mermaid diagrams)"
        )
        raise typer.Abort()

    # --- Load IR ----------------------------------------------------------
    if domain:
        ir_data = load_domain_ir(domain)
    else:
        ir_data = load_ir_file(ir)

    # --- Generate output --------------------------------------------------
    content = _generate_output(
        ir_data,
        doc_type=type,
        output_format=format,
        cluster_fqn=cluster,
    )

    # --- Emit output ------------------------------------------------------
    if output:
        _write_output(output, content)
        print(f"[green]Documentation written to {output}[/green]")
    else:
        typer.echo(content)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_output(
    ir_data: dict[str, Any],
    *,
    doc_type: str,
    output_format: str,
    cluster_fqn: str,
) -> str:
    """Dispatch to the appropriate generator(s) and assemble the result."""
    sections: list[str] = []

    if doc_type in ("clusters", "all"):
        sections.append(_generate_clusters(ir_data, output_format, cluster_fqn))

    if doc_type in ("events", "all"):
        sections.append(_generate_events(ir_data, output_format))

    if doc_type in ("handlers", "all"):
        sections.append(_generate_handlers(ir_data, output_format))

    if doc_type in ("catalog", "all"):
        sections.append(_generate_catalog(ir_data))

    return "\n\n".join(sections)


def _generate_clusters(
    ir_data: dict[str, Any],
    output_format: str,
    cluster_fqn: str,
) -> str:
    """Generate cluster diagrams."""
    from protean.ir.generators.clusters import generate_cluster_diagram

    if cluster_fqn:
        raw = generate_cluster_diagram(ir_data, cluster_fqn=cluster_fqn)
        if output_format == "mermaid":
            return raw
        return mermaid_fence(raw, title="Aggregate Cluster")

    # For --type=all or --type=clusters without --cluster filter.
    clusters = ir_data.get("clusters", {})

    if output_format == "mermaid":
        # Raw Mermaid: emit a single combined classDiagram (multiple
        # top-level classDiagram declarations are invalid Mermaid).
        return generate_cluster_diagram(ir_data)

    # Markdown: one fenced diagram per cluster for readability.
    if not clusters:
        raw = generate_cluster_diagram(ir_data)
        return mermaid_fence(raw, title="Aggregate Clusters")

    parts: list[str] = []
    for cfqn in sorted(clusters):
        raw = generate_cluster_diagram(ir_data, cluster_fqn=cfqn)
        cluster_name = cfqn.rsplit(".", 1)[-1] if "." in cfqn else cfqn
        parts.append(mermaid_fence(raw, title=f"Cluster: {cluster_name}"))

    return "\n\n".join(parts)


def _generate_events(ir_data: dict[str, Any], output_format: str) -> str:
    """Generate event flow diagram."""
    from protean.ir.generators.events import generate_event_flow_diagram

    raw = generate_event_flow_diagram(ir_data)
    if output_format == "mermaid":
        return raw
    return mermaid_fence(raw, title="Event Flows")


def _generate_handlers(ir_data: dict[str, Any], output_format: str) -> str:
    """Generate handler wiring diagram."""
    from protean.ir.generators.handlers import generate_handler_wiring_diagram

    raw = generate_handler_wiring_diagram(ir_data)
    if output_format == "mermaid":
        return raw
    return mermaid_fence(raw, title="Handler Wiring")


def _generate_catalog(ir_data: dict[str, Any]) -> str:
    """Generate event/command catalog (always Markdown)."""
    from protean.ir.generators.catalog import generate_catalog

    return generate_catalog(ir_data)


def _write_output(path: str, content: str) -> None:
    """Write content to a file, creating parent directories as needed."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
