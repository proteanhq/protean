"""CLI commands for managing dead letter queues.

Provides commands for listing, inspecting, replaying, and purging
messages that failed processing and were moved to DLQ streams.

Usage::

    # List all DLQ messages
    protean dlq list --domain=my_domain

    # List DLQ messages for a specific subscription
    protean dlq list --subscription=order --domain=my_domain

    # Inspect a specific DLQ message
    protean dlq inspect <dlq_id> --domain=my_domain

    # Replay a single message
    protean dlq replay <dlq_id> --subscription=order --domain=my_domain

    # Replay all messages for a subscription
    protean dlq replay-all --subscription=order --domain=my_domain

    # Purge all DLQ messages for a subscription
    protean dlq purge --subscription=order --domain=my_domain
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import typer
from rich import print
from rich.table import Table
from typing_extensions import Annotated

from protean.exceptions import NoDomainException
from protean.port.broker import BrokerCapabilities
from protean.utils.dlq import collect_dlq_streams, discover_subscriptions
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

if TYPE_CHECKING:
    from protean.domain import Domain

logger = get_logger(__name__)

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback():
    """Manage dead letter queues."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_domain(domain_path: str) -> "Domain":
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


def _get_broker(domain: "Domain"):
    """Retrieve the default broker from the domain."""
    broker = domain.brokers.get("default")
    if broker is None:
        print("Error: No default broker configured in domain.")
        raise typer.Abort()
    if not broker.has_capability(BrokerCapabilities.DEAD_LETTER_QUEUE):
        print("Error: Configured broker does not support dead letter queues.")
        raise typer.Abort()
    return broker


def _resolve_dlq_streams(domain: "Domain", subscription: str | None) -> list[str]:
    """Resolve DLQ stream names, optionally filtered by subscription."""
    if subscription:
        # Map subscription name to DLQ stream(s)
        infos = discover_subscriptions(domain)
        streams = []
        for info in infos:
            if info.stream_category == subscription:
                streams.append(info.dlq_stream)
                if info.backfill_dlq_stream:
                    streams.append(info.backfill_dlq_stream)
        if not streams:
            print(f"Error: No subscription found for stream category '{subscription}'.")
            raise typer.Abort()
        return streams
    return collect_dlq_streams(domain)


def _resolve_target_stream(subscription: str) -> str:
    """Derive the target stream name from a subscription (stream category)."""
    return subscription


def _format_time(raw: str | None) -> str:
    """Format an ISO timestamp for display."""
    if not raw:
        return "-"
    try:
        from datetime import datetime

        return datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return raw


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command(name="list")
def list_dlq(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    subscription: Annotated[
        str | None,
        typer.Option(help="Filter by stream category (e.g. 'order')"),
    ] = None,
    limit: Annotated[
        int, typer.Option(help="Maximum number of messages to show")
    ] = 100,
) -> None:
    """List failed messages across DLQ streams."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        broker = _get_broker(derived_domain)
        dlq_streams = _resolve_dlq_streams(derived_domain, subscription)

        if not dlq_streams:
            print("No subscriptions found in domain.")
            return

        entries = broker.dlq_list(dlq_streams, limit=limit)

        if not entries:
            print("No DLQ messages found.")
            return

        table = Table()
        table.add_column("DLQ ID", style="cyan")
        table.add_column("Subscription")
        table.add_column("Consumer Group", style="dim")
        table.add_column("Failure Reason", style="red")
        table.add_column("Failed At")
        table.add_column("Retries", justify="right")

        for entry in entries:
            table.add_row(
                entry.dlq_id[:16] + "..." if len(entry.dlq_id) > 16 else entry.dlq_id,
                entry.stream,
                entry.consumer_group[:30] + "..."
                if len(entry.consumer_group) > 30
                else entry.consumer_group,
                entry.failure_reason,
                _format_time(entry.failed_at),
                str(entry.retry_count),
            )

        print(table)
        print(f"\n{len(entries)} DLQ message(s) found.")


@app.command()
def inspect(
    dlq_id: Annotated[str, typer.Argument(help="DLQ entry identifier")],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    subscription: Annotated[
        str | None,
        typer.Option(help="Stream category to search in"),
    ] = None,
) -> None:
    """Show full details of a DLQ message."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        broker = _get_broker(derived_domain)
        dlq_streams = _resolve_dlq_streams(derived_domain, subscription)

        entry = None
        for dlq_stream in dlq_streams:
            entry = broker.dlq_inspect(dlq_stream, dlq_id)
            if entry:
                break

        if not entry:
            print(f"DLQ message '{dlq_id}' not found.")
            raise typer.Abort()

        print(f"[bold]DLQ ID:[/bold]          {entry.dlq_id}")
        print(f"[bold]Original ID:[/bold]     {entry.original_id}")
        print(f"[bold]Stream:[/bold]          {entry.stream}")
        print(f"[bold]Consumer Group:[/bold]  {entry.consumer_group}")
        print(f"[bold]DLQ Stream:[/bold]      {entry.dlq_stream}")
        print(f"[bold]Failure Reason:[/bold]  {entry.failure_reason}")
        print(f"[bold]Failed At:[/bold]       {_format_time(entry.failed_at)}")
        print(f"[bold]Retry Count:[/bold]     {entry.retry_count}")
        print("\n[bold]Payload:[/bold]")
        # Strip DLQ metadata from display payload for clarity
        display_payload = {
            k: v for k, v in entry.payload.items() if k != "_dlq_metadata"
        }
        print(json.dumps(display_payload, indent=2, default=str))


@app.command()
def replay(
    dlq_id: Annotated[str, typer.Argument(help="DLQ entry identifier to replay")],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    subscription: Annotated[
        str | None,
        typer.Option(help="Stream category to search in"),
    ] = None,
) -> None:
    """Replay a single DLQ message back to its original stream."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        broker = _get_broker(derived_domain)
        dlq_streams = _resolve_dlq_streams(derived_domain, subscription)

        for dlq_stream in dlq_streams:
            entry = broker.dlq_inspect(dlq_stream, dlq_id)
            if entry:
                target_stream = entry.stream
                success = broker.dlq_replay(dlq_stream, dlq_id, target_stream)
                if success:
                    print(f"Replayed message '{dlq_id}' to stream '{target_stream}'.")
                else:
                    print(f"Failed to replay message '{dlq_id}'.")
                return

        print(f"DLQ message '{dlq_id}' not found.")
        raise typer.Abort()


@app.command(name="replay-all")
def replay_all(
    subscription: Annotated[
        str,
        typer.Option(help="Stream category (required)"),
    ],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt")
    ] = False,
) -> None:
    """Replay all DLQ messages for a subscription back to their original stream."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        broker = _get_broker(derived_domain)
        dlq_streams = _resolve_dlq_streams(derived_domain, subscription)
        target_stream = _resolve_target_stream(subscription)

        if not yes:
            typer.confirm(
                f"Replay all DLQ messages for subscription '{subscription}'?",
                abort=True,
            )

        total = 0
        for dlq_stream in dlq_streams:
            total += broker.dlq_replay_all(dlq_stream, target_stream)

        print(f"Replayed {total} message(s) to stream '{target_stream}'.")


@app.command()
def purge(
    subscription: Annotated[
        str,
        typer.Option(help="Stream category (required)"),
    ],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt")
    ] = False,
) -> None:
    """Purge all DLQ messages for a subscription."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        broker = _get_broker(derived_domain)
        dlq_streams = _resolve_dlq_streams(derived_domain, subscription)

        if not yes:
            typer.confirm(
                f"Purge all DLQ messages for subscription '{subscription}'? This cannot be undone.",
                abort=True,
            )

        total = 0
        for dlq_stream in dlq_streams:
            total += broker.dlq_purge(dlq_stream)

        print(f"Purged {total} message(s) from DLQ.")
