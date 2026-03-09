"""CLI commands for the domain IR (Intermediate Representation).

Usage::

    # Show full IR as JSON
    protean ir show --domain=my_domain

    # Show IR summary with element counts
    protean ir show --domain=my_domain --format=summary

    # Diff two IR snapshots
    protean ir diff --left=baseline.json --right=current.json

    # Diff live domain against a saved baseline
    protean ir diff --domain=my_app --right=baseline.json
"""

import json
from pathlib import Path
from typing import Any

import typer
from rich import print
from rich.console import Console
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


@app.command()
def diff(
    left: Annotated[
        str,
        typer.Option(
            "--left",
            "-l",
            help="Path to the left (baseline) IR JSON file",
        ),
    ] = "",
    right: Annotated[
        str,
        typer.Option(
            "--right",
            "-r",
            help="Path to the right (current) IR JSON file",
        ),
    ] = "",
    domain: Annotated[
        str,
        typer.Option(
            "--domain",
            "-d",
            help="Load live domain IR as the left side (alternative to --left)",
        ),
    ] = "",
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: 'text' (default) or 'json'",
        ),
    ] = "text",
) -> None:
    """Compare two IR snapshots and show differences."""
    from protean.ir.diff import diff_ir

    # Validate arguments
    if not right:
        print("[red]Error:[/red] --right is required")
        raise typer.Abort()

    if left and domain:
        print("[red]Error:[/red] --left and --domain are mutually exclusive")
        raise typer.Abort()

    if not left and not domain:
        print("[red]Error:[/red] provide either --left or --domain")
        raise typer.Abort()

    # Load left IR
    if domain:
        left_ir = _load_domain_ir(domain)
    else:
        left_ir = _load_ir_file(left)

    # Load right IR
    right_ir = _load_ir_file(right)

    # Compute diff
    result = diff_ir(left_ir, right_ir)

    if format == "json":
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_diff_text(result)


def _load_ir_file(path: str) -> dict[str, Any]:
    """Load an IR dict from a JSON file."""
    file_path = Path(path)
    if not file_path.exists():
        print(f"[red]Error:[/red] file not found: {path}")
        raise typer.Abort()
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[red]Error:[/red] invalid JSON in {path}: {exc}")
        raise typer.Abort()


def _load_domain_ir(domain_path: str) -> dict[str, Any]:
    """Build and return the IR from a live domain."""
    try:
        derived_domain = derive_domain(domain_path)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(msg)
        logger.error(msg)
        raise typer.Abort()

    assert derived_domain is not None
    derived_domain.init()
    return derived_domain.to_ir()


# ------------------------------------------------------------------
# Text formatting for diff output
# ------------------------------------------------------------------

_CONSOLE = Console()


def _print_diff_text(result: dict[str, Any]) -> None:
    """Print a rich-formatted text diff to the terminal."""
    summary = result.get("summary", {})

    if not summary.get("has_changes", False):
        print("[green]No changes detected.[/green]")
        return

    # Header
    print(
        f"\n[bold]IR Diff[/bold]  "
        f"left={summary.get('left_checksum', '?')[:16]}  "
        f"right={summary.get('right_checksum', '?')[:16]}"
    )

    counts = summary.get("counts", {})
    print(
        f"  [green]+{counts.get('added', 0)} added[/green]  "
        f"[red]-{counts.get('removed', 0)} removed[/red]  "
        f"[yellow]~{counts.get('changed', 0)} changed[/yellow]"
    )

    # Breaking changes (prominent)
    breaking = result.get("contracts", {}).get("breaking_changes", [])
    if breaking:
        print(f"\n[bold red]Breaking Changes ({len(breaking)}):[/bold red]")
        for bc in breaking:
            print(f"  [red]! {bc['message']}[/red]")

    # Clusters
    clusters = result.get("clusters", {})
    if clusters:
        print("\n[bold]Clusters[/bold]")
        _print_section_changes(clusters)

    # Projections
    projections = result.get("projections", {})
    if projections:
        print("\n[bold]Projections[/bold]")
        _print_section_changes(projections)

    # Flows
    flows = result.get("flows", {})
    if flows:
        print("\n[bold]Flows[/bold]")
        for sub_name in ("domain_services", "process_managers", "subscribers"):
            sub = flows.get(sub_name, {})
            if sub:
                label = sub_name.replace("_", " ").title()
                print(f"  [dim]{label}[/dim]")
                _print_section_changes(sub, indent=4)

    # Contracts (non-breaking additions)
    contracts = result.get("contracts", {})
    contract_added = contracts.get("added", [])
    contract_removed = contracts.get("removed", [])
    if contract_added or contract_removed:
        print("\n[bold]Contracts[/bold]")
        for evt in contract_added:
            print(
                f"  [green]+ published event: {evt.get('__type__', evt.get('fqn'))}[/green]"
            )
        for evt in contract_removed:
            print(
                f"  [red]- published event: {evt.get('__type__', evt.get('fqn'))}[/red]"
            )

    # Diagnostics
    diagnostics = result.get("diagnostics", {})
    if diagnostics:
        print("\n[bold]Diagnostics[/bold]")
        for diag in diagnostics.get("added", []):
            print(f"  [yellow]+ {diag['code']}: {diag['message']}[/yellow]")
        for diag in diagnostics.get("resolved", []):
            print(f"  [green]- resolved: {diag['code']}: {diag['message']}[/green]")

    # Domain config
    domain_diff = result.get("domain", {})
    domain_changed = domain_diff.get("changed", {})
    if domain_changed:
        print("\n[bold]Domain Config[/bold]")
        for key, vals in sorted(domain_changed.items()):
            print(f"  [yellow]~ {key}: {vals['left']} → {vals['right']}[/yellow]")

    print()


def _print_section_changes(
    section: dict[str, Any],
    indent: int = 2,
) -> None:
    """Print added/removed/changed for a keyed section."""
    pad = " " * indent

    for fqn, info in sorted(section.get("added", {}).items()):
        name = info.get("name", fqn.rsplit(".", 1)[-1])
        etype = info.get("element_type", "")
        label = f"{name} ({etype})" if etype else name
        print(f"{pad}[green]+ {label}[/green]")

    for fqn, info in sorted(section.get("removed", {}).items()):
        name = info.get("name", fqn.rsplit(".", 1)[-1])
        etype = info.get("element_type", "")
        label = f"{name} ({etype})" if etype else name
        print(f"{pad}[red]- {label}[/red]")

    for fqn, changes in sorted(section.get("changed", {}).items()):
        name = fqn.rsplit(".", 1)[-1]
        print(f"{pad}[yellow]~ {name}[/yellow]")
        _print_element_changes(changes, indent + 4)


def _print_element_changes(
    changes: dict[str, Any],
    indent: int,
) -> None:
    """Print field-level and attribute-level changes for an element."""
    pad = " " * indent

    # Aggregate-level changes within a cluster
    if "aggregate" in changes:
        print(f"{pad}[dim]aggregate:[/dim]")
        _print_element_changes(changes["aggregate"], indent + 2)

    # Fields
    fields = changes.get("fields", {})
    if fields:
        for name, field_info in sorted(fields.get("added", {}).items()):
            kind = field_info.get("type", field_info.get("kind", ""))
            req = ", required" if field_info.get("required") else ""
            print(f"{pad}[green]+ field: {name} ({kind}{req})[/green]")

        for name, field_info in sorted(fields.get("removed", {}).items()):
            kind = field_info.get("type", field_info.get("kind", ""))
            print(f"{pad}[red]- field: {name} ({kind})[/red]")

        for name, attrs in sorted(fields.get("changed", {}).items()):
            for attr, vals in sorted(attrs.items()):
                print(
                    f"{pad}[yellow]~ field {name}.{attr}: "
                    f"{vals['left']} → {vals['right']}[/yellow]"
                )

    # Options
    options = changes.get("options", {})
    for key, vals in sorted(options.get("changed", {}).items()):
        print(f"{pad}[yellow]~ option {key}: {vals['left']} → {vals['right']}[/yellow]")

    # Handlers
    handlers = changes.get("handlers", {})
    if handlers:
        for type_key in sorted(handlers.get("added", {})):
            print(f"{pad}[green]+ handles: {type_key}[/green]")
        for type_key in sorted(handlers.get("removed", {})):
            print(f"{pad}[red]- handles: {type_key}[/red]")

    # Invariants
    invariants = changes.get("invariants", {})
    for category in ("pre", "post"):
        cat_changes = invariants.get(category, {})
        for name in cat_changes.get("added", []):
            print(f"{pad}[green]+ invariant ({category}): {name}[/green]")
        for name in cat_changes.get("removed", []):
            print(f"{pad}[red]- invariant ({category}): {name}[/red]")

    # Sub-sections (entities, commands, events, etc. within a cluster)
    for sub in (
        "entities",
        "value_objects",
        "commands",
        "events",
        "command_handlers",
        "event_handlers",
        "repositories",
        "database_models",
        "application_services",
        "projectors",
        "queries",
        "query_handlers",
    ):
        sub_changes = changes.get(sub, {})
        if sub_changes:
            label = sub.replace("_", " ")
            print(f"{pad}[dim]{label}:[/dim]")
            _print_section_changes(sub_changes, indent + 2)


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
