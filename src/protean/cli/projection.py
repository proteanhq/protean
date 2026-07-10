"""CLI commands for projection management.

Provides the ``protean projection rebuild`` command for reconstructing
projections by replaying events from the event store through their
associated projectors.

Usage::

    # Rebuild a specific projection
    protean projection rebuild --domain=my_domain --projection=Balances

    # Rebuild all projections
    protean projection rebuild --domain=my_domain
"""

import json as json_mod
from typing import TYPE_CHECKING, Annotated

import typer
from rich import print
from rich.table import Table

from protean.cli._helpers import handle_cli_exceptions, load_domain
from protean.utils import DomainObjects

if TYPE_CHECKING:
    from protean.core.projection import BaseProjection
    from protean.domain import Domain

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback() -> None:
    """Manage projections."""


@app.command()
@handle_cli_exceptions("projection rebuild")
def rebuild(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    projection: Annotated[
        str,
        typer.Option(
            help="Projection class name (e.g. 'UserReport'). "
            "If omitted, rebuilds all projections."
        ),
    ] = "",
    batch_size: Annotated[
        int,
        typer.Option(help="Number of events to read per batch."),
    ] = 500,
) -> None:
    """Rebuild projections by replaying events from the event store.

    Truncates projection data and replays all events through the
    associated projectors. Upcasters are applied automatically.

    Without options, rebuilds ALL projections.
    Use --projection to target a specific projection class.

    Warning: ensure the server is stopped before rebuilding projections
    to avoid conflicts with concurrent event processing.
    """
    derived_domain = load_domain(domain)
    with derived_domain.domain_context():
        if projection:
            _rebuild_single(derived_domain, projection, batch_size)
        else:
            _rebuild_all(derived_domain, batch_size)


def _resolve_projection(
    domain: "Domain", projection_name: str
) -> "type[BaseProjection] | None":
    """Resolve a projection class by name from the domain registry.

    Returns the class or None (with error printed).
    """
    for record in domain.registry._elements[DomainObjects.PROJECTION.value].values():
        projection_cls: type[BaseProjection] = record.cls
        if projection_cls.__name__ == projection_name:
            return projection_cls

    print(f"Error: Projection '{projection_name}' not found in domain.")
    return None


def _rebuild_single(
    domain: "Domain",
    projection_name: str,
    batch_size: int,
) -> None:
    """Rebuild a single projection."""
    projection_cls = _resolve_projection(domain, projection_name)
    if projection_cls is None:
        raise typer.Abort()

    result = domain.rebuild_projection(projection_cls, batch_size)
    if result.success:
        print(
            f"Rebuilt projection '{result.projection_name}': "
            f"{result.events_dispatched} events processed "
            f"through {result.projectors_processed} projector(s) "
            f"across {result.categories_processed} category/categories."
        )
        if result.events_skipped > 0:
            print(f"  ({result.events_skipped} events skipped)")
    else:
        for error in result.errors:
            print(f"Error: {error}")
        raise typer.Abort()


def _rebuild_all(domain: "Domain", batch_size: int) -> None:
    """Rebuild all projections in the domain."""
    results = domain.rebuild_all_projections(batch_size)
    if not results:
        print("No projections found in domain.")
        return

    total_events = 0
    for name, result in results.items():
        if result.success:
            print(f"  {name}: {result.events_dispatched} events processed")
            total_events += result.events_dispatched
        else:
            for error in result.errors:
                print(f"  {name}: ERROR - {error}")

    print(
        f"Rebuilt {len(results)} projection(s), {total_events} total events processed."
    )


def _status_style(status: str) -> str:
    """Return a Rich markup colour for a status string."""
    if status == "ok":
        return "[green]ok[/green]"
    if status == "lagging":
        return "[red]lagging[/red]"
    return "[yellow]unknown[/yellow]"


@app.command()
@handle_cli_exceptions("projection status")
def status(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output raw JSON instead of a table"),
    ] = False,
) -> None:
    """Show staleness, lag, and row count for every projection.

    For each projection (read model) this reports how far behind it is in time
    (``staleness``) and in events (``lag``) across all the projectors that feed it,
    plus its current row count. Does not require the server to be running.
    """
    from protean.server.projection_status import (  # noqa: PLC0415
        collect_projection_statuses,
    )

    derived_domain = load_domain(domain)

    with derived_domain.domain_context():
        statuses = collect_projection_statuses(derived_domain)

    if not statuses:
        if output_json:
            print(json_mod.dumps([]))
        else:
            print("No projections found in domain.")
        return

    if output_json:
        print(json_mod.dumps([s.to_dict() for s in statuses], indent=2, default=str))
        return

    table = Table(title=f"Projections — {derived_domain.name}")
    table.add_column("Projection", style="bold")
    table.add_column("Projectors")
    table.add_column("Last Updated")
    table.add_column("Staleness (s)", justify="right", style="cyan")
    table.add_column("Lag", justify="right")
    table.add_column("Rows", justify="right")
    table.add_column("Status")

    for s in statuses:
        staleness_str = (
            f"{s.staleness_seconds:.0f}" if s.staleness_seconds is not None else "-"
        )
        lag_str = str(s.lag) if s.lag is not None else "-"
        rows_str = str(s.row_count) if s.row_count is not None else "-"

        table.add_row(
            s.projection_name,
            ", ".join(s.projectors) if s.projectors else "-",
            s.last_updated or "-",
            staleness_str,
            lag_str,
            rows_str,
            _status_style(s.status),
        )

    print(table)

    total = len(statuses)
    ok_count = sum(1 for s in statuses if s.status == "ok")
    lagging_count = sum(1 for s in statuses if s.status == "lagging")
    unknown_count = sum(1 for s in statuses if s.status == "unknown")

    summary_parts = [f"{total} projection(s)"]
    if ok_count:
        summary_parts.append(f"[green]{ok_count} ok[/green]")
    if lagging_count:
        summary_parts.append(f"[red]{lagging_count} lagging[/red]")
    if unknown_count:
        summary_parts.append(f"[yellow]{unknown_count} unknown[/yellow]")

    print(f"\n{', '.join(summary_parts)}")
