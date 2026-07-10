"""CLI commands for event-sourced aggregate snapshotting."""

from typing import TYPE_CHECKING, Annotated, cast

import typer
from rich import print

from protean.cli._helpers import handle_cli_exceptions, load_domain
from protean.exceptions import (
    IncorrectUsageError,
    ObjectNotFoundError,
)
from protean.utils import DomainObjects

if TYPE_CHECKING:
    from protean.core.aggregate import BaseAggregate
    from protean.domain import Domain

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback() -> None:
    """Manage snapshots for event-sourced aggregates."""


@app.command()
@handle_cli_exceptions("snapshot create")
def create(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    aggregate: Annotated[
        str,
        typer.Option(
            help="Aggregate class name (e.g. 'User'). "
            "If omitted, snapshots all event-sourced aggregates."
        ),
    ] = "",
    identifier: Annotated[
        str,
        typer.Option(help="Specific aggregate identifier. Requires --aggregate."),
    ] = "",
) -> None:
    """Create snapshots for event-sourced aggregates.

    Without options, creates snapshots for ALL event-sourced aggregates.
    Use --aggregate to target a specific aggregate class.
    Use --aggregate and --identifier for a single instance.
    """
    if identifier and not aggregate:
        print("Error: --identifier requires --aggregate")
        raise typer.Abort()

    derived_domain = load_domain(domain)
    with derived_domain.domain_context():
        if aggregate and identifier:
            _create_single(derived_domain, aggregate, identifier)
        elif aggregate:
            _create_for_aggregate(derived_domain, aggregate)
        else:
            _create_all(derived_domain)


def _resolve_aggregate(
    domain: "Domain", aggregate_name: str
) -> "type[BaseAggregate] | None":
    """Resolve an aggregate class by name from the domain registry.

    Returns the class or None (with error printed).
    """
    for record in domain.registry._elements[DomainObjects.AGGREGATE.value].values():
        if record.cls.__name__ == aggregate_name:
            # registry stores element classes as ``Any``; narrow to the
            # aggregate class type expected by the snapshot APIs.
            return cast("type[BaseAggregate]", record.cls)

    print(f"Error: Aggregate '{aggregate_name}' not found in domain.")
    return None


def _create_single(domain: "Domain", aggregate_name: str, identifier: str) -> None:
    """Snapshot a single aggregate instance."""
    aggregate_cls = _resolve_aggregate(domain, aggregate_name)
    if aggregate_cls is None:
        raise typer.Abort()

    try:
        domain.create_snapshot(aggregate_cls, identifier)
        print(f"Snapshot created for {aggregate_name} with identifier {identifier}.")
    except (ObjectNotFoundError, IncorrectUsageError) as exc:
        print(f"Error: {exc.args[0]}")
        raise typer.Abort() from exc


def _create_for_aggregate(domain: "Domain", aggregate_name: str) -> None:
    """Snapshot all instances of one aggregate."""
    aggregate_cls = _resolve_aggregate(domain, aggregate_name)
    if aggregate_cls is None:
        raise typer.Abort()

    try:
        count = domain.create_snapshots(aggregate_cls)
        print(f"Created {count} snapshot(s) for {aggregate_name}.")
    except IncorrectUsageError as exc:
        print(f"Error: {exc.args[0]}")
        raise typer.Abort() from exc


def _create_all(domain: "Domain") -> None:
    """Snapshot all event-sourced aggregates in the domain."""
    results = domain.create_all_snapshots()
    if not results:
        print("No event-sourced aggregates found in domain.")
        return

    total = 0
    for agg_name, count in results.items():
        print(f"  {agg_name}: {count} snapshot(s)")
        total += count
    print(f"Created {total} snapshot(s) across {len(results)} aggregate(s).")
