"""CLI commands for event-sourced aggregate snapshotting."""

import typer
from rich import print
from typing_extensions import Annotated

from protean.exceptions import (
    IncorrectUsageError,
    NoDomainException,
    ObjectNotFoundError,
)
from protean.utils import DomainObjects
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

logger = get_logger(__name__)

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback():
    """Manage snapshots for event-sourced aggregates."""


@app.command()
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

    try:
        derived_domain = derive_domain(domain)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(msg)
        logger.error(msg)
        raise typer.Abort()

    assert derived_domain is not None

    derived_domain.init()
    with derived_domain.domain_context():
        if aggregate and identifier:
            _create_single(derived_domain, aggregate, identifier)
        elif aggregate:
            _create_for_aggregate(derived_domain, aggregate)
        else:
            _create_all(derived_domain)


def _resolve_aggregate(domain: "Domain", aggregate_name: str):  # type: ignore[name-defined]  # noqa: F821
    """Resolve an aggregate class by name from the domain registry.

    Returns the class or None (with error printed).
    """
    for _, record in domain.registry._elements[DomainObjects.AGGREGATE.value].items():
        if record.cls.__name__ == aggregate_name:
            return record.cls

    print(f"Error: Aggregate '{aggregate_name}' not found in domain.")
    return None


def _create_single(domain: "Domain", aggregate_name: str, identifier: str) -> None:  # type: ignore[name-defined]  # noqa: F821
    """Snapshot a single aggregate instance."""
    aggregate_cls = _resolve_aggregate(domain, aggregate_name)
    if aggregate_cls is None:
        raise typer.Abort()

    try:
        domain.create_snapshot(aggregate_cls, identifier)
        print(f"Snapshot created for {aggregate_name} with identifier {identifier}.")
    except (ObjectNotFoundError, IncorrectUsageError) as exc:
        print(f"Error: {exc.args[0]}")
        raise typer.Abort()


def _create_for_aggregate(domain: "Domain", aggregate_name: str) -> None:  # type: ignore[name-defined]  # noqa: F821
    """Snapshot all instances of one aggregate."""
    aggregate_cls = _resolve_aggregate(domain, aggregate_name)
    if aggregate_cls is None:
        raise typer.Abort()

    try:
        count = domain.create_snapshots(aggregate_cls)
        print(f"Created {count} snapshot(s) for {aggregate_name}.")
    except IncorrectUsageError as exc:
        print(f"Error: {exc.args[0]}")
        raise typer.Abort()


def _create_all(domain: "Domain") -> None:  # type: ignore[name-defined]  # noqa: F821
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
