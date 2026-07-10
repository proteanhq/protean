"""CLI commands for consume-side idempotency (the ProcessedMessage marker).

Usage::

    # Prune idempotency markers older than the retention window (run from cron).
    protean idempotency cleanup --domain=my_domain
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich import print

from protean.cli._helpers import handle_cli_exceptions, load_domain
from protean.utils.consume_idempotency import cleanup_processed_messages

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback() -> None:
    """Manage consume-side idempotency markers."""


@app.command()
@handle_cli_exceptions("idempotency cleanup")
def cleanup(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    retention_hours: Annotated[
        int | None,
        typer.Option(help="Prune markers older than this many hours"),
    ] = None,
    batch_size: Annotated[
        int | None, typer.Option(help="Rows deleted per bounded batch")
    ] = None,
) -> None:
    """Prune consume-side idempotency markers older than the retention window.

    A marker is only useful while its event can still be redelivered, so older
    markers are safe to delete. Defaults come from ``[consume_idempotency.cleanup]``
    (7 days / 5000 rows per batch). Run periodically from a cron job.
    """
    derived_domain = load_domain(domain)
    deleted = cleanup_processed_messages(
        derived_domain, retention_hours=retention_hours, batch_size=batch_size
    )
    if deleted:
        print(f"Deleted {deleted} idempotency marker(s).")
    else:
        print("No idempotency markers to clean up.")
