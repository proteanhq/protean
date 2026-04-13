"""CLI commands for monitoring subscription lag.

Provides a ``status`` command that displays lag, pending, and DLQ depth
for every subscription (event handlers, command handlers, projectors,
process managers, broker subscribers, and outbox processors).

Usage::

    # Rich table output
    protean subscriptions status --domain=my_domain

    # Machine-readable JSON
    protean subscriptions status --domain=my_domain --json
"""

import json as json_mod

import typer
from rich import print
from rich.table import Table
from typing_extensions import Annotated

from protean.cli._helpers import handle_cli_exceptions
from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

logger = get_logger(__name__)

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback():
    """Monitor subscription lag and health."""


def _load_domain(domain_path: str):
    """Load and initialize a domain, handling errors consistently."""
    try:
        derived_domain = derive_domain(domain_path)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(msg)
        logger.error(msg)
        raise typer.Abort()

    assert derived_domain is not None
    derived_domain.init()
    return derived_domain


def _status_style(status: str) -> str:
    """Return a Rich markup colour for a status string."""
    if status == "ok":
        return "[green]ok[/green]"
    if status == "lagging":
        return "[red]lagging[/red]"
    return "[yellow]unknown[/yellow]"


@app.command()
@handle_cli_exceptions("subscriptions status")
def status(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output raw JSON instead of a table"),
    ] = False,
) -> None:
    """Show subscription lag status for all handlers."""
    from protean.server.subscription_status import collect_subscription_statuses

    derived_domain = _load_domain(domain)

    with derived_domain.domain_context():
        statuses = collect_subscription_statuses(derived_domain)

    if not statuses:
        if output_json:
            print(json_mod.dumps([]))
        else:
            print("No subscriptions found in domain.")
        return

    if output_json:
        print(json_mod.dumps([s.to_dict() for s in statuses], indent=2, default=str))
        return

    # Rich table
    table = Table(title=f"Subscriptions — {derived_domain.name}")
    table.add_column("Handler", style="bold")
    table.add_column("Type")
    table.add_column("Stream")
    table.add_column("Lag", justify="right", style="cyan")
    table.add_column("Pending", justify="right")
    table.add_column("DLQ", justify="right")
    table.add_column("Consumers", justify="right")
    table.add_column("Status")

    for s in statuses:
        lag_str = str(s.lag) if s.lag is not None else "-"
        dlq_str = str(s.dlq_depth) if s.dlq_depth else "-"
        consumers_str = str(s.consumer_count) if s.consumer_count else "-"

        table.add_row(
            s.handler_name,
            s.subscription_type,
            s.stream_category,
            lag_str,
            str(s.pending),
            dlq_str,
            consumers_str,
            _status_style(s.status),
        )

    print(table)

    # Summary line
    total = len(statuses)
    ok_count = sum(1 for s in statuses if s.status == "ok")
    lagging_count = sum(1 for s in statuses if s.status == "lagging")
    unknown_count = sum(1 for s in statuses if s.status == "unknown")
    total_lag = sum(s.lag or 0 for s in statuses)

    summary_parts = [f"{total} subscription(s)"]
    if ok_count:
        summary_parts.append(f"[green]{ok_count} ok[/green]")
    if lagging_count:
        summary_parts.append(f"[red]{lagging_count} lagging[/red]")
    if unknown_count:
        summary_parts.append(f"[yellow]{unknown_count} unknown[/yellow]")
    if total_lag:
        summary_parts.append(f"total lag: {total_lag}")

    print(f"\n{', '.join(summary_parts)}")
