"""CLI commands for the transactional outbox.

Usage::

    # Create outbox rows for events durable in the event store that are missing
    # their outbox row (recovers the ADR-0015 crash window).
    protean outbox reconcile --domain=my_domain
"""

from __future__ import annotations

import typer
from rich import print
from typing_extensions import Annotated

from protean.cli._helpers import handle_cli_exceptions, load_domain
from protean.utils.outbox import reconcile_outbox

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback() -> None:
    """Manage the transactional outbox."""


@app.command()
@handle_cli_exceptions("outbox reconcile")
def reconcile(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    provider: Annotated[
        str, typer.Option(help="Provider whose outbox to reconcile")
    ] = "default",
    limit: Annotated[
        int, typer.Option(help="Most recent events to scan for gaps")
    ] = 1000,
) -> None:
    """Create outbox rows for events in the event store that are missing them.

    Recovers the ADR-0015 crash window: an event appended to the event store
    (the durable anchor) whose relational outbox commit did not land, so the
    event is durable but would never be published.
    """
    derived_domain = load_domain(domain)
    with derived_domain.domain_context():
        if not derived_domain.has_outbox:
            print("Outbox is not enabled for this domain (set enable_outbox=True).")
            raise typer.Abort()

        created = reconcile_outbox(derived_domain, provider_name=provider, limit=limit)
        if created:
            print(f"Reconciled {created} outbox row(s) from the event store.")
        else:
            print(
                "Nothing to reconcile: the outbox is consistent with the event store."
            )
