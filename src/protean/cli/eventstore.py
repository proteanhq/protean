"""CLI commands for the event store.

Provides ``verify`` (event-store integrity check) and a ``dlq`` group that
surfaces the event-store dead-letter queue.

``dlq`` shows the positions a subscription retried up to ``max_retries`` and then
gave up on (``Exhausted`` records in each subscription's ``failed-*`` stream).
``list`` enumerates those positions per subscription; ``inspect`` re-reads the
failing event so you can see what could not be processed.

Usage::

    # Check the event store's internal consistency
    protean eventstore verify --domain=my_domain

    # Machine-readable result (the shared CLI envelope)
    protean eventstore verify --domain=my_domain --json

    # Rich table of exhausted positions, grouped by subscription
    protean eventstore dlq list --domain=my_domain

    # Only one subscription (by stream category)
    protean eventstore dlq list --subscription=order --domain=my_domain

    # Re-read the failing event behind an exhausted position
    protean eventstore dlq inspect 42 --domain=my_domain

    # Machine-readable JSON (the shared CLI result envelope)
    protean eventstore dlq list --domain=my_domain --json
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any

import typer
from rich import print
from rich.table import Table

from protean.cli._helpers import CTX_LOG_CONFIGURED, handle_cli_exceptions, load_domain
from protean.cli.result import (
    EXIT_FAILURE,
    build_envelope,
    emit_usage_error,
    route_logs_to_stderr,
)
from protean.utils.dlq import collect_failed_streams

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.port.event_store import BaseEventStore
    from protean.utils.dlq import SubscriptionInfo
    from protean.utils.eventing import Message

app = typer.Typer(no_args_is_help=True)
dlq_app = typer.Typer(no_args_is_help=True)
app.add_typer(dlq_app, name="dlq")


@app.callback()
def callback() -> None:
    """Inspect and maintain the event store."""


@app.command()
@handle_cli_exceptions("eventstore verify")
def verify(
    ctx: typer.Context,
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the report as the shared CLI envelope")
    ] = False,
) -> None:
    """Check the event store's internal consistency (read-only).

    Verifies per-stream position gaplessness, store-wide global_position
    monotonicity, message-id uniqueness, and that no snapshot runs ahead of its
    aggregate stream. Exits 0 when clean, 1 when any violation is found.

    ``verify`` checks *internal* consistency only. Physical backup and restore
    stay with the database and its own tooling.
    """
    if as_json:
        # Route logs to stderr before the domain import so a stray import-time
        # log cannot corrupt the machine payload on stdout.
        route_logs_to_stderr(
            log_already_configured=bool((ctx.obj or {}).get(CTX_LOG_CONFIGURED))
        )

    derived_domain = load_domain(domain, as_json=as_json)
    with derived_domain.domain_context():
        store = derived_domain.event_store.store
        assert store is not None  # guaranteed by load_domain -> init()
        report = store.verify()

    if as_json:
        envelope = build_envelope(
            status="pass" if report.ok else "fail",
            data=report.as_dict(),
            diagnostics=[],
        )
        typer.echo(json.dumps(envelope, indent=2, sort_keys=True, default=str))
        if not report.ok:
            raise typer.Exit(code=EXIT_FAILURE)
        return

    if report.ok:
        print(
            f"Event store is consistent: {report.message_count} message(s) across "
            f"{report.stream_count} stream(s), 0 violations."
        )
        return

    table = Table(title="Event store integrity violations")
    table.add_column("Kind", style="red")
    table.add_column("Stream")
    table.add_column("Position", justify="right")
    table.add_column("Detail")
    for violation in report.violations:
        table.add_row(
            violation.kind,
            violation.stream or "-",
            "-" if violation.position is None else str(violation.position),
            violation.detail,
        )
    print(table)
    print(
        f"\n{len(report.violations)} violation(s) across {report.message_count} "
        f"message(s) and {report.stream_count} stream(s)."
    )
    raise typer.Exit(code=EXIT_FAILURE)


@dlq_app.callback()
def dlq_callback() -> None:
    """Inspect event-store dead-letter (exhausted) positions."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _select_failed_streams(
    domain: Domain, subscription: str | None
) -> list[tuple[SubscriptionInfo, str]]:
    """Return the (subscription, failed-stream) pairs, optionally filtered.

    ``subscription`` filters by stream category (the same value ``dlq``'s broker
    commands accept). An unknown category is a usage error handled by the caller.
    """
    pairs = collect_failed_streams(domain)
    if subscription:
        pairs = [p for p in pairs if p[0].stream_category == subscription]
    return pairs


def _exhausted_positions(store: BaseEventStore, failed_stream: str) -> list[int]:
    """Return the positions whose latest record in ``failed_stream`` is Exhausted.

    Reads the whole stream with ``read_all`` (never a single capped ``read``,
    which would silently truncate a large stream) and folds last-status-wins per
    position, so a position that was later resolved or re-failed is not reported
    as exhausted.
    """
    from protean.server.subscription.event_store_subscription import (  # noqa: PLC0415
        FailedPositionStatus,
    )

    latest_status: dict[int, str] = {}
    for message in store.read_all(failed_stream):
        position = message.data.get("position")
        headers = message.metadata.headers if message.metadata else None
        status = headers.type if headers else None
        if position is None or status is None:
            continue
        latest_status[position] = status

    return [
        pos
        for pos, status in latest_status.items()
        if status == FailedPositionStatus.EXHAUSTED.value
    ]


def _find_exhausted_record(
    store: BaseEventStore,
    pairs: list[tuple[SubscriptionInfo, str]],
    position: int,
) -> Message | None:
    """Find the ``Exhausted`` record for ``position`` across the failed streams.

    Returns the record message (from which ``inspect`` reads ``stream_name`` and
    ``stream_position``), or ``None`` if no failed stream holds an ``Exhausted``
    record at that position.
    """
    from protean.server.subscription.event_store_subscription import (  # noqa: PLC0415
        FailedPositionStatus,
    )

    found: Message | None = None
    for _info, failed_stream in pairs:
        for message in store.read_all(failed_stream):
            if message.data.get("position") != position:
                continue
            headers = message.metadata.headers if message.metadata else None
            status = headers.type if headers else None
            if status == FailedPositionStatus.EXHAUSTED.value:
                # Last write wins, defensively; exhaustion is written once.
                found = message
    return found


def _read_failing_event(
    store: BaseEventStore, record: Message, position: int
) -> Message | None:
    """Re-read the event behind an exhausted ``record`` from the event store.

    Prefers the enriched ``stream_name``/``stream_position`` on the record. A
    record written before enrichment carries neither, so it falls back to the
    origin category stream (on the record's ``domain.origin_stream``) read by
    the global ``position``.
    """
    stream_name = record.data.get("stream_name")
    stream_position = record.data.get("stream_position")

    if stream_name and stream_position is not None:
        messages = store.read(stream_name, position=stream_position, no_of_messages=1)
    else:
        domain_meta = record.metadata.domain if record.metadata else None
        origin_stream = domain_meta.origin_stream if domain_meta else None
        if not origin_stream:
            return None
        messages = store.read(origin_stream, position=position, no_of_messages=1)

    return messages[0] if messages else None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@dlq_app.command(name="list")
@handle_cli_exceptions("eventstore dlq list")
def list_dlq(
    ctx: typer.Context,
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    subscription: Annotated[
        str | None,
        typer.Option(help="Filter by stream category (e.g. 'order')"),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output raw JSON instead of a table"),
    ] = False,
) -> None:
    """List exhausted positions, grouped by subscription.

    Under ``--json`` the result is the shared CLI result envelope, with the
    per-subscription list under ``data.subscriptions`` (each carrying
    ``handler``, ``stream_category``, and ``exhausted`` positions).
    """
    if output_json:
        # Route logs to stderr before the domain import so a stray import-time
        # log cannot corrupt the machine payload on stdout.
        route_logs_to_stderr(
            log_already_configured=bool((ctx.obj or {}).get(CTX_LOG_CONFIGURED))
        )

    derived_domain = load_domain(domain, as_json=output_json)

    with derived_domain.domain_context():
        store = derived_domain.event_store.store
        assert store is not None  # guaranteed by load_domain -> init()

        pairs = _select_failed_streams(derived_domain, subscription)
        if subscription and not pairs:
            emit_usage_error(
                as_json=output_json,
                message=f"No event-store subscription found for stream category '{subscription}'.",
            )

        subscriptions: list[dict[str, Any]] = []
        for info, failed_stream in pairs:
            exhausted = sorted(_exhausted_positions(store, failed_stream))
            if not exhausted:
                continue
            subscriptions.append(
                {
                    "handler": info.handler_fqn,
                    "stream_category": info.stream_category,
                    "exhausted": exhausted,
                }
            )

    if output_json:
        envelope = build_envelope(
            status="pass",
            data={"subscriptions": subscriptions},
            diagnostics=[],
        )
        typer.echo(json.dumps(envelope, indent=2, sort_keys=True, default=str))
        return

    if not subscriptions:
        print("No exhausted positions.")
        return

    table = Table(title=f"Exhausted positions — {derived_domain.name}")
    table.add_column("Handler", style="bold")
    table.add_column("Stream Category")
    table.add_column("Exhausted Positions", style="red")

    total = 0
    for sub in subscriptions:
        positions = sub["exhausted"]
        total += len(positions)
        table.add_row(
            sub["handler"],
            sub["stream_category"],
            ", ".join(str(p) for p in positions),
        )

    print(table)
    print(
        f"\n{total} exhausted position(s) across {len(subscriptions)} subscription(s)."
    )


@dlq_app.command()
@handle_cli_exceptions("eventstore dlq inspect")
def inspect(
    ctx: typer.Context,
    position: Annotated[int, typer.Argument(help="Exhausted global position")],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    subscription: Annotated[
        str | None,
        typer.Option(help="Stream category to search in"),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output raw JSON instead of a table"),
    ] = False,
) -> None:
    """Re-read the failing event behind an exhausted position.

    Under ``--json`` the result is the shared CLI result envelope, with
    ``position``, ``type``, ``global_position``, and ``data`` under ``data``.
    """
    if output_json:
        route_logs_to_stderr(
            log_already_configured=bool((ctx.obj or {}).get(CTX_LOG_CONFIGURED))
        )

    derived_domain = load_domain(domain, as_json=output_json)

    with derived_domain.domain_context():
        store = derived_domain.event_store.store
        assert store is not None  # guaranteed by load_domain -> init()

        pairs = _select_failed_streams(derived_domain, subscription)
        if subscription and not pairs:
            emit_usage_error(
                as_json=output_json,
                message=f"No event-store subscription found for stream category '{subscription}'.",
            )

        record = _find_exhausted_record(store, pairs, position)
        if record is None:
            emit_usage_error(
                as_json=output_json,
                message=f"No exhausted position {position} found.",
            )

        event = _read_failing_event(store, record, position)
        if event is None:
            emit_usage_error(
                as_json=output_json,
                message=f"Could not re-read the event for exhausted position {position}.",
            )

        headers = event.metadata.headers if event.metadata else None
        event_type = (headers.type if headers else None) or "unknown"
        es_meta = event.metadata.event_store if event.metadata else None
        global_position = es_meta.global_position if es_meta else None
        event_data = event.data

    if output_json:
        envelope = build_envelope(
            status="pass",
            data={
                "position": position,
                "type": event_type,
                "global_position": global_position,
                "data": event_data,
            },
            diagnostics=[],
        )
        typer.echo(json.dumps(envelope, indent=2, sort_keys=True, default=str))
        return

    print(f"[bold]Position:[/bold]         {position}")
    print(f"[bold]Type:[/bold]             {event_type}")
    print(f"[bold]Global Position:[/bold]  {global_position}")
    print("\n[bold]Data:[/bold]")
    print(json.dumps(event_data, indent=2, default=str))
