"""CLI commands for inspecting the event store.

Provides commands for reading events, viewing stream statistics,
searching for events by type, viewing aggregate event histories,
and tracing causation chains.

Usage::

    # Read events from a stream
    protean events read "test::user-abc123" --domain=my_domain

    # View stream statistics
    protean events stats --domain=my_domain

    # Search for events by type
    protean events search --type=UserRegistered --domain=my_domain

    # View aggregate event history
    protean events history --aggregate=User --id=abc123 --domain=my_domain

    # Trace causation chain (tree view)
    protean events trace <correlation_id> --domain=my_domain

    # Trace causation chain (flat table)
    protean events trace <correlation_id> --flat --domain=my_domain
"""

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

import typer
from rich import print
from rich.table import Table
from rich.tree import Tree as RichTree
from typing_extensions import Annotated

from protean.cli._helpers import handle_cli_exceptions
from protean.cli._ir_utils import load_domain_ir, load_ir_file
from protean.exceptions import NoDomainException
from protean.utils import DomainObjects
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.port.event_store import CausationNode

logger = get_logger(__name__)

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback() -> None:
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


def _resolve_aggregate(domain: "Domain", aggregate_name: str) -> Any:
    """Resolve an aggregate class by name from the domain registry.

    Returns the aggregate class (registry entries are untyped ``Any``) or
    ``None`` when no aggregate matches the given name.
    """
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


def _data_keys_summary(data: dict[str, Any] | None) -> str:
    """Return a short summary of the data keys."""
    if not data:
        return "-"
    keys = list(data.keys())
    summary = ", ".join(keys[:5])
    if len(keys) > 5:
        summary += f" (+{len(keys) - 5} more)"
    return summary


def _extract_trace_ids(msg: dict[str, Any]) -> tuple[str, str]:
    """Extract correlation and causation IDs from message metadata."""
    metadata = msg.get("metadata")
    if not metadata or not isinstance(metadata, dict):
        return ("", "")
    domain_meta = metadata.get("domain")
    if not domain_meta or not isinstance(domain_meta, dict):
        return ("", "")
    correlation_id = str(domain_meta.get("correlation_id", "") or "")
    causation_id = str(domain_meta.get("causation_id", "") or "")
    return (correlation_id, causation_id)


def _truncate_id(value: str, length: int = 8) -> str:
    """Truncate an ID for display, appending '...' if shortened."""
    if len(value) > length:
        return value[:length] + "..."
    return value


def _build_events_table(
    messages: list[dict[str, Any]],
    *,
    show_data: bool = False,
    show_stream: bool = False,
    show_trace: bool = False,
) -> Table:
    """Build a Rich Table from a list of raw event dicts."""
    table = Table()
    table.add_column("Position", justify="right", style="cyan")
    table.add_column("Global Pos", justify="right", style="dim")
    table.add_column("Type", style="green")
    if show_stream:
        table.add_column("Stream")
    table.add_column("Time")
    if show_trace:
        table.add_column("Correlation ID", style="yellow")
        table.add_column("Causation ID", style="dim yellow")
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
        if show_trace:
            correlation_id, causation_id = _extract_trace_ids(msg)
            row.append(_truncate_id(correlation_id))
            row.append(causation_id)
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


def _build_rich_tree(node: "CausationNode") -> RichTree:
    """Build a Rich Tree from a CausationNode for CLI display."""
    kind_badge = "[bold cyan]CMD[/]" if node.kind == "COMMAND" else "[bold green]EVT[/]"
    time_str = f" @ {_format_time(node.time)}" if node.time else ""

    # Handler attribution and timing
    handler_str = f" [yellow]→ {node.handler}[/]" if node.handler else ""
    duration_str = (
        f" [magenta]{node.duration_ms:.1f}ms[/]" if node.duration_ms is not None else ""
    )
    delta_str = f" [dim]+{node.delta_ms:.1f}ms[/]" if node.delta_ms is not None else ""

    label = (
        f"{kind_badge} {node.message_type}{handler_str}{duration_str}{delta_str} "
        f"[dim]({_truncate_id(node.message_id, 40)}){time_str}[/]"
    )

    tree = RichTree(label)
    for child in node.children:
        tree.add(_build_rich_tree(child))
    return tree


def _count_nodes(node: "CausationNode") -> int:
    """Count all nodes in a CausationNode tree."""
    return 1 + sum(_count_nodes(c) for c in node.children)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
@handle_cli_exceptions("events read")
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
    show_trace: Annotated[
        bool,
        typer.Option("--trace/--no-trace", help="Show correlation and causation IDs"),
    ] = False,
) -> None:
    """Read and display events from a stream."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        store = derived_domain.event_store.store
        assert store is not None  # guaranteed by _load_domain -> init()
        messages = store._read(stream, position=position, no_of_messages=limit)

        if not messages:
            print(f"No events found in stream '{stream}'")
            return

        table = _build_events_table(
            messages, show_data=show_data, show_trace=show_trace
        )
        print(table)

        if show_data:
            _print_event_data(messages)

        print(f"\nShowing {len(messages)} event(s) from position {position}")


@app.command()
@handle_cli_exceptions("events stats")
def stats(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
) -> None:
    """Show stream statistics across the domain."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        store = derived_domain.event_store.store
        assert store is not None  # guaranteed by _load_domain -> init()
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
@handle_cli_exceptions("events search")
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
    show_trace: Annotated[
        bool,
        typer.Option("--trace/--no-trace", help="Show correlation and causation IDs"),
    ] = False,
) -> None:
    """Search for events by type across streams."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        store = derived_domain.event_store.store
        assert store is not None  # guaranteed by _load_domain -> init()
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

        table = _build_events_table(
            display, show_data=show_data, show_stream=True, show_trace=show_trace
        )
        print(table)

        if show_data:
            _print_event_data(display)

        msg = f"\nFound {total_matched} event(s) matching type '{type_name}'"
        if total_matched > limit:
            msg += f" (showing first {limit})"
        print(msg)


@app.command()
@handle_cli_exceptions("events history")
def history(
    aggregate: Annotated[str, typer.Option(help="Aggregate class name (e.g. 'User')")],
    identifier: Annotated[
        str, typer.Option("--id", help="Aggregate instance identifier")
    ],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    show_data: Annotated[
        bool, typer.Option("--data/--no-data", help="Show full event data")
    ] = False,
    show_trace: Annotated[
        bool,
        typer.Option("--trace/--no-trace", help="Show correlation and causation IDs"),
    ] = False,
) -> None:
    """Display the event timeline for a specific aggregate instance."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        aggregate_cls = _resolve_aggregate(derived_domain, aggregate)
        if aggregate_cls is None:
            raise typer.Abort()

        store = derived_domain.event_store.store
        assert store is not None  # guaranteed by _load_domain -> init()
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
        if show_trace:
            table.add_column("Correlation ID", style="yellow")
            table.add_column("Causation ID", style="dim yellow")
        if not show_data:
            table.add_column("Data Keys", style="dim")

        for msg in messages:
            row = [
                str(msg.get("position", "?")),
                str(msg.get("type", "<unknown>")),
                _format_time(msg.get("time")),
            ]
            if show_trace:
                correlation_id, causation_id = _extract_trace_ids(msg)
                row.append(_truncate_id(correlation_id))
                row.append(causation_id)
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


@app.command()
@handle_cli_exceptions("events trace")
def trace(
    correlation_id: Annotated[str, typer.Argument(help="Correlation ID to trace")],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    show_data: Annotated[
        bool, typer.Option("--data/--no-data", help="Show full event data")
    ] = False,
    flat: Annotated[
        bool,
        typer.Option("--flat/--tree", help="Show flat table instead of causation tree"),
    ] = False,
) -> None:
    """Follow the full causal chain for a correlation ID across all streams."""
    derived_domain = _load_domain(domain)
    with derived_domain.domain_context():
        store = derived_domain.event_store.store
        assert store is not None  # guaranteed by _load_domain -> init()

        if flat:
            # Flat table display (original behavior)
            all_messages = store._read("$all", no_of_messages=1_000_000)

            matched = [
                m for m in all_messages if _extract_trace_ids(m)[0] == correlation_id
            ]

            if not matched:
                print(f"No events found for correlation ID '{correlation_id}'")
                return

            table = _build_events_table(
                matched, show_data=show_data, show_stream=True, show_trace=True
            )
            print(table)

            if show_data:
                _print_event_data(matched)

            print(
                f"\nFound {len(matched)} event(s) for correlation ID '{correlation_id}'"
            )
        else:
            # Tree display (default)
            root_node = store.build_causation_tree(correlation_id)
            if root_node is None:
                print(f"No events found for correlation ID '{correlation_id}'")
                return

            tree = _build_rich_tree(root_node)
            print(tree)

            total = _count_nodes(root_node)
            print(
                f"\nCausation tree: {total} message(s) for correlation ID "
                f"'{correlation_id}'"
            )


# ---------------------------------------------------------------------------
# Catalog (IR-sourced event contract view)
# ---------------------------------------------------------------------------


def _format_deprecated(deprecated: Any) -> str:
    """Render an event's ``deprecated`` marker for the catalog table.

    A missing marker (``None``) renders as ``-``; any *present* value — even an
    empty dict — means the event is deprecated (``build_event_catalog`` passes
    ``None`` when the IR omits the key, so ``{}`` only occurs for a declared but
    detail-less deprecation).
    """
    if deprecated is None:
        return "-"
    if isinstance(deprecated, dict):
        since = deprecated.get("since")
        removal = deprecated.get("removal")
        if since and removal:
            return f"since {since}, removal {removal}"
        if since:
            return f"since {since}"
        if removal:
            return f"removal {removal}"
        return "yes"
    return str(deprecated)


def _format_upcaster_chain(edges: list[dict[str, Any]]) -> str:
    """Render an upcaster chain as ``v1→v2→v3``.

    ``edges`` is a list of ``{from_version, to_version}`` dicts for one event.
    A domain-sourced chain is contiguous and sorted, but a hand-authored ``--ir``
    file may not be, so this is defensive: malformed edges (missing a version)
    are skipped, edges are sorted, and a discontinuity is shown as ``…`` rather
    than silently collapsed — never crashing on bad input.
    """
    pairs = sorted(
        (edge["from_version"], edge["to_version"])
        for edge in edges
        if "from_version" in edge and "to_version" in edge
    )
    if not pairs:
        return "-"

    parts = [f"v{pairs[0][0]}"]
    prev_to = pairs[0][0]
    for frm, to in pairs:
        if frm != prev_to:
            parts.append("…")  # gap: versions between prev_to and frm have no upcaster
            parts.append(f"v{frm}")
        parts.append(f"v{to}")
        prev_to = to
    return "→".join(parts)


def _build_catalog_table(entries: list[dict[str, Any]]) -> Table:
    """Build a Rich table of event catalog entries."""
    table = Table(title="Event Catalog")
    table.add_column("Event", style="green")
    table.add_column("Type", style="cyan")
    table.add_column("Ver", justify="right")
    table.add_column("Deprecated")
    table.add_column("Superseded By")
    table.add_column("Upcasters")
    table.add_column("Consumers", style="dim")

    for entry in entries:
        table.add_row(
            entry["name"],
            entry["type"],
            str(entry["version"]),
            _format_deprecated(entry["deprecated"]),
            entry["superseded_by"] or "-",
            _format_upcaster_chain(entry["upcasters"]),
            ", ".join(entry["consumers"]) if entry["consumers"] else "-",
        )
    return table


@app.command()
@handle_cli_exceptions("events catalog")
def catalog(
    domain: Annotated[
        str, typer.Option("--domain", "-d", help="Domain module path")
    ] = "",
    ir: Annotated[str, typer.Option("--ir", help="Path to an IR JSON file")] = "",
    as_json: Annotated[
        bool, typer.Option("--json", help="Output the catalog as JSON")
    ] = False,
) -> None:
    """List every event with version, deprecation, upcasters, and consumers.

    Sourced from the domain IR (contracts), not the event store, so it works
    from a live domain (``--domain``) or a serialized IR file (``--ir``). Use
    ``protean schema generate --format all`` to emit the matching versioned
    schema tree (JSON + Avro + Protobuf) — together they form the local
    registry on-ramp.
    """
    if not domain and not ir:
        print("[red]Error:[/red] provide either --domain or --ir")
        raise typer.Abort()
    if domain and ir:
        print("[red]Error:[/red] --domain and --ir are mutually exclusive")
        raise typer.Abort()

    from protean.ir.generators.catalog import build_event_catalog  # noqa: PLC0415

    ir_data = load_domain_ir(domain) if domain else load_ir_file(ir)
    entries = build_event_catalog(ir_data)

    if as_json:
        typer.echo(json.dumps(entries, indent=2, default=str))
        return

    if not entries:
        print("No events found in domain.")
        return

    print(_build_catalog_table(entries))
    print(f"\n{len(entries)} event(s)")
