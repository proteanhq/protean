"""CLI commands for the domain IR (Intermediate Representation).

Usage::

    # Show full IR as JSON
    protean ir show --domain=my_domain

    # Show IR summary with element counts
    protean ir show --domain=my_domain --format=summary
"""

import json

import typer
from rich import print
from rich.table import Table
from typing_extensions import Annotated

from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

logger = get_logger(__name__)

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback():
    """Inspect the domain's Intermediate Representation (IR)."""


@app.command()
def show(
    domain: Annotated[
        str,
        typer.Option(
            "--domain",
            "-d",
            help="Path to the domain module (e.g. 'my_app.domain')",
        ),
    ],
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: 'json' (default) or 'summary'",
        ),
    ] = "json",
) -> None:
    """Show the domain's IR."""
    try:
        derived_domain = derive_domain(domain)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(msg)
        logger.error(msg)
        raise typer.Abort()

    assert derived_domain is not None
    derived_domain.init()

    ir = derived_domain.to_ir()

    if format == "summary":
        _print_summary(ir)
    else:
        typer.echo(json.dumps(ir, indent=2, sort_keys=True))


def _print_summary(ir: dict) -> None:
    """Print a human-readable summary of the IR."""
    print(f"\n[bold]Domain:[/bold] {ir['domain']['name']}")
    print(f"[bold]IR Version:[/bold] {ir['ir_version']}")
    print(f"[bold]Checksum:[/bold] {ir['checksum']}")
    print()

    # Element counts
    table = Table(title="Element Counts")
    table.add_column("Element Type", style="cyan")
    table.add_column("Count", justify="right", style="green")

    for etype, fqn_list in sorted(ir.get("elements", {}).items()):
        table.add_row(etype, str(len(fqn_list)))

    print(table)

    # Cluster summary
    clusters = ir.get("clusters", {})
    if clusters:
        print(f"\n[bold]Clusters:[/bold] {len(clusters)}")
        for cluster_fqn, cluster in sorted(clusters.items()):
            agg_name = cluster["aggregate"]["name"]
            entity_count = len(cluster.get("entities", {}))
            vo_count = len(cluster.get("value_objects", {}))
            cmd_count = len(cluster.get("commands", {}))
            evt_count = len(cluster.get("events", {}))
            print(
                f"  {agg_name}: "
                f"{entity_count} entities, {vo_count} VOs, "
                f"{cmd_count} commands, {evt_count} events"
            )

    # Diagnostics
    diagnostics = ir.get("diagnostics", [])
    if diagnostics:
        print(f"\n[bold yellow]Diagnostics:[/bold yellow] {len(diagnostics)}")
        for diag in diagnostics:
            print(f"  [{diag['level']}] {diag['code']}: {diag['message']}")
