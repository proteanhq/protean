"""CLI commands for inspecting the event store.

Provides commands for reading events, viewing stream statistics,
searching for events by type, and viewing aggregate event histories.

Usage::

    # Read events from a stream
    protean events read "test::user-abc123" --domain=my_domain

    # View stream statistics
    protean events stats --domain=my_domain

    # Search for events by type
    protean events search --type=UserRegistered --domain=my_domain

    # View aggregate event history
    protean events history --aggregate=User --id=abc123 --domain=my_domain
"""

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

import typer
from rich import print
from rich.table import Table
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
    """Inspect and query the event store."""


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


def _resolve_aggregate(domain: "Domain", aggregate_name: str):  # type: ignore[name-defined]
    """Resolve an aggregate class by name from the domain registry."""
    for _, record in domain.registry._elements[DomainObjects.AGGREGATE.value].items():
        if record.cls.__name__ == aggregate_name:
            return record.cls

    print(f"Error: Aggregate '{aggregate_name}' not found in domain.")
    return None


def _format_time(raw_time: Any) -> str:
    """Format a raw time value (datetime or ISO string) for display."""
    if raw_time is None:
        return "-"
    if isinstance(raw_time, datetime):
        return raw_time.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(raw_time, str):
        try:
            return datetime.fromisoformat(raw_time).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return raw_time
    return str(raw_time)


def _data_keys_summary(data: dict | None) -> str:
    """Return a short summary of the data keys."""
    if not data:
        return "-"
    keys = list(data.keys())
    summary = ", ".join(keys[:5])
    if len(keys) > 5:
        summary += f" (+{len(keys) - 5} more)"
    return summary


def _build_events_table(
    messages: list[dict[str, Any]],
    *,
    show_data: bool = False,
    show_stream: bool = False,
) -> Table:
    """Build a Rich Table from a list of raw event dicts."""
    table = Table()
    table.add_column("Position", justify="right", style="cyan")
    table.add_column("Global Pos", justify="right", style="dim")
    table.add_column("Type", style="green")
    if show_stream:
        table.add_column("Stream")
    table.add_column("Time")
    if not show_data:
        table.add_column("Data Keys", style="dim")

    for msg in messages:
        row = [
            str(msg.get("position", "?")),
            str(msg.get("global_position", "?")),
            str(msg.get("type", "<unknown>")),
        ]
        if show_stream:
            row.append(str(msg.get("stream_name", "")))
        row.append(_format_time(msg.get("time")))
        if not show_data:
            row.append(_data_keys_summary(msg.get("data")))
        table.add_row(*row)

    return table


def _print_event_data(messages: list[dict[str, Any]]) -> None:
    """Print the full data payload for each message."""
    for msg in messages:
        event_type = msg.get("type", "<unknown>")
        position = msg.get("position", "?")
        data = msg.get("data", {})
        print(f"\n[bold]Event {position}[/bold] ({event_type}):")
        print(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def read(
    stream: Annotated[
        str,
        typer.Argument(
            help="Stream name (e.g. 'test::user-abc123') or category (e.g. 'test::user')"
        ),
    ],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    position: Annotated[
        int, typer.Option("--from", help="Start reading from this position")
    ] = 0,
    limit: Annotated[
        int, typer.Option(help="Maximum number of events to display")
    ] = 20,
    show_data: Annotated[
        bool, typer.Option("--data/--no-data", help="Show full event data")
    ] = False,
) -> None:
    """Read and display events from a stream."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        store = derived_domain.event_store.store
        messages = store._read(stream, position=position, no_of_messages=limit)

        if not messages:
            print(f"No events found in stream '{stream}'")
            return

        table = _build_events_table(messages, show_data=show_data)
        print(table)

        if show_data:
            _print_event_data(messages)

        print(f"\nShowing {len(messages)} event(s) from position {position}")


@app.command()
def stats(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
) -> None:
    """Show stream statistics across the domain."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        store = derived_domain.event_store.store
        aggregates = derived_domain.registry._elements.get(
            DomainObjects.AGGREGATE.value, {}
        )

        if not aggregates:
            print("No aggregates registered in domain.")
            return

        table = Table()
        table.add_column("Aggregate", style="bold")
        table.add_column("Stream Category")
        table.add_column("ES?", justify="center")
        table.add_column("Instances", justify="right")
        table.add_column("Events", justify="right", style="cyan")
        table.add_column("Latest Type", style="green")
        table.add_column("Latest Time")

        total_events = 0
        total_instances = 0

        for _, record in aggregates.items():
            agg_cls = record.cls
            stream_category = agg_cls.meta_.stream_category
            is_es = "Yes" if agg_cls.meta_.is_event_sourced else "No"

            # Count unique instances
            try:
                identifiers = store._stream_identifiers(stream_category)
                instance_count = len(identifiers)
            except Exception:
                instance_count = 0

            # Count total events and find latest
            try:
                all_events = store._read(stream_category, no_of_messages=1_000_000)
                event_count = len(all_events)
                latest = all_events[-1] if all_events else None
            except Exception:
                event_count = 0
                latest = None

            latest_type = str(latest.get("type", "")) if latest else "-"
            latest_time = _format_time(latest.get("time")) if latest else "-"

            table.add_row(
                agg_cls.__name__,
                stream_category,
                is_es,
                str(instance_count),
                str(event_count),
                latest_type,
                latest_time,
            )

            total_events += event_count
            total_instances += instance_count

        print(table)
        print(
            f"\nTotal: {total_events} event(s) across "
            f"{total_instances} aggregate instance(s)"
        )


@app.command()
def search(
    type_name: Annotated[
        str,
        typer.Option("--type", help="Event type to search for (e.g. 'UserRegistered')"),
    ],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    category: Annotated[
        str, typer.Option(help="Restrict search to a stream category")
    ] = "",
    limit: Annotated[int, typer.Option(help="Maximum number of results")] = 20,
    show_data: Annotated[
        bool, typer.Option("--data/--no-data", help="Show full event data")
    ] = False,
) -> None:
    """Search for events by type across streams."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        store = derived_domain.event_store.store
        stream = category if category else "$all"
        all_messages = store._read(stream, no_of_messages=1_000_000)

        # Filter by type: exact match if dots present, partial otherwise
        if "." in type_name:
            matched = [m for m in all_messages if m.get("type") == type_name]
        else:
            type_lower = type_name.lower()
            matched = [
                m for m in all_messages if type_lower in m.get("type", "").lower()
            ]

        if not matched:
            print(f"No events found matching type '{type_name}'")
            return

        total_matched = len(matched)
        display = matched[:limit]

        table = _build_events_table(display, show_data=show_data, show_stream=True)
        print(table)

        if show_data:
            _print_event_data(display)

        msg = f"\nFound {total_matched} event(s) matching type '{type_name}'"
        if total_matched > limit:
            msg += f" (showing first {limit})"
        print(msg)


@app.command()
def history(
    aggregate: Annotated[str, typer.Option(help="Aggregate class name (e.g. 'User')")],
    identifier: Annotated[
        str, typer.Option("--id", help="Aggregate instance identifier")
    ],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    show_data: Annotated[
        bool, typer.Option("--data/--no-data", help="Show full event data")
    ] = False,
) -> None:
    """Display the event timeline for a specific aggregate instance."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        aggregate_cls = _resolve_aggregate(derived_domain, aggregate)
        if aggregate_cls is None:
            raise typer.Abort()

        store = derived_domain.event_store.store
        stream_category = aggregate_cls.meta_.stream_category
        stream_name = f"{stream_category}-{identifier}"

        messages = store._read(stream_name)

        if not messages:
            print(f"No events found for {aggregate} with identifier '{identifier}'")
            return

        # Build timeline table
        table = Table(title=f"{aggregate} ({identifier})")
        table.add_column("Version", justify="right", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Time")
        if not show_data:
            table.add_column("Data Keys", style="dim")

        for msg in messages:
            row = [
                str(msg.get("position", "?")),
                str(msg.get("type", "<unknown>")),
                _format_time(msg.get("time")),
            ]
            if not show_data:
                row.append(_data_keys_summary(msg.get("data")))
            table.add_row(*row)

        print(table)

        if show_data:
            _print_event_data(messages)

        # Check for snapshot
        snapshot_stream = f"{stream_category}:snapshot-{identifier}"
        snapshot = store._read_last_message(snapshot_stream)
        if snapshot:
            snap_version = snapshot.get("data", {}).get("_version", "?")
            print(f"Snapshot exists at version {snap_version}")

        last_position = messages[-1].get("position", "?")
        print(
            f"\n{aggregate} ({identifier}): "
            f"{len(messages)} event(s), current version: {last_position}"
        )
