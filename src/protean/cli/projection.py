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

from typing import TYPE_CHECKING

import typer
from rich import print
from typing_extensions import Annotated

from protean.exceptions import NoDomainException
from protean.utils import DomainObjects
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

if TYPE_CHECKING:
    from protean.domain import Domain

logger = get_logger(__name__)

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback():
    """Manage projections."""


@app.command()
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
        if projection:
            _rebuild_single(derived_domain, projection, batch_size)
        else:
            _rebuild_all(derived_domain, batch_size)


def _resolve_projection(domain: "Domain", projection_name: str):
    """Resolve a projection class by name from the domain registry.

    Returns the class or None (with error printed).
    """
    for _, record in domain.registry._elements[DomainObjects.PROJECTION.value].items():
        if record.cls.__name__ == projection_name:
            return record.cls

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
