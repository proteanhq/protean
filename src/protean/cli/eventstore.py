"""CLI commands for the event store.

Provides ``verify`` (event-store integrity check) and a ``dlq`` group that
manages the event-store dead-letter queue.

``dlq`` covers the positions a subscription retried up to ``max_retries`` and
then gave up on (``Exhausted`` records in each subscription's ``failed-*``
stream). ``list`` enumerates those positions per subscription; ``inspect``
re-reads the failing event so you can see what could not be processed;
``replay`` re-drives one position through its handler; ``purge`` clears one with
a terminal ``Purged`` marker.

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

    # Re-drive an exhausted position through its handler
    protean eventstore dlq replay 42 --domain=my_domain

    # Clear an exhausted position with a terminal Purged marker
    protean eventstore dlq purge 42 --domain=my_domain

    # Machine-readable JSON (the shared CLI result envelope)
    protean eventstore dlq list --domain=my_domain --json
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import contextmanager
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
    from protean.server.engine import Engine
    from protean.server.subscription.event_store_subscription import (
        EventStoreSubscription,
    )
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
    """Manage event-store dead-letter (exhausted) positions."""


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


def _exhausted_owners(
    store: BaseEventStore,
    pairs: list[tuple[SubscriptionInfo, str]],
    position: int,
) -> list[tuple[SubscriptionInfo, str, Message]]:
    """Return every (subscription, failed-stream, record) whose *latest* status for ``position`` is Exhausted.

    Different handlers on the same stream process the same events, so one global
    position can be exhausted in more than one subscription's failed stream;
    ``replay`` and ``purge`` act on a single handler's copy, so the caller uses
    this to detect that ambiguity.

    Folds last-status-wins (via ``_exhausted_positions``) before reading the
    record, so a position already resolved or purged is not returned: acting on
    it again would re-run a handler or re-mark a position the operator already
    cleared.
    """
    owners: list[tuple[SubscriptionInfo, str, Message]] = []
    for info, failed_stream in pairs:
        if position not in _exhausted_positions(store, failed_stream):
            continue
        # The position's latest status is Exhausted (it is in
        # ``_exhausted_positions``), so its Exhausted record exists.
        record = _find_exhausted_record(store, [(info, failed_stream)], position)
        assert record is not None
        owners.append((info, failed_stream, record))
    return owners


def _resolve_exhausted_owner(
    store: BaseEventStore,
    domain: Domain,
    subscription: str | None,
    handler: str | None,
    position: int,
) -> tuple[SubscriptionInfo, str, Message]:
    """Resolve the single subscription that owns an exhausted ``position``, or abort.

    ``subscription`` filters by stream category and ``handler`` by the handler
    identity ``list`` prints (its ``subscription_fqn``, or the shorter class
    name). Aborts with a usage error when ``--subscription`` names no event-store
    subscription, when no subscription lists the position as exhausted, or when
    more than one still does after both filters (two handlers on one stream share
    a category, so ``--handler`` is the one that separates them).
    """
    pairs = _select_failed_streams(domain, subscription)
    if subscription and not pairs:
        emit_usage_error(
            as_json=False,
            message=f"No event-store subscription found for stream category '{subscription}'.",
        )
    if handler:
        pairs = [
            p for p in pairs if handler in (p[0].subscription_fqn, p[0].handler_name)
        ]
        if not pairs:
            emit_usage_error(
                as_json=False,
                message=f"No event-store subscription found for handler '{handler}'.",
            )

    owners = _exhausted_owners(store, pairs, position)
    if not owners:
        emit_usage_error(
            as_json=False, message=f"No exhausted position {position} found."
        )
    if len(owners) > 1:
        handlers = ", ".join(sorted(o[0].subscription_fqn for o in owners))
        emit_usage_error(
            as_json=False,
            message=(
                f"Position {position} is exhausted in multiple subscriptions "
                f"({handlers}). Pass --handler to choose one."
            ),
        )
    return owners[0]


def _still_exhausted_or_abort(
    store: BaseEventStore, failed_stream: str, position: int
) -> None:
    """Re-read ``failed_stream`` and abort unless ``position`` is still Exhausted.

    ``replay`` and ``purge`` resolve the owner before they prompt, and the
    operator can sit on that prompt for a while. Another operator's replay or
    purge can resolve or purge the same position in the meantime, so both
    commands re-read the latest status here, immediately before they act, and
    refuse a position that is no longer exhausted. The re-read and the action are
    still two steps against an append-only stream, so this narrows the window
    rather than closing it; closing it needs a conditional append the failed
    streams do not have.
    """
    if position not in _exhausted_positions(store, failed_stream):
        emit_usage_error(
            as_json=False,
            message=(
                f"Position {position} is no longer exhausted: another replay or "
                f"purge cleared it while this command was waiting. Nothing was done."
            ),
        )


@contextmanager
def _redrive_engine(domain: Domain) -> Iterator[Engine]:
    """Build an engine for ``replay``'s re-drive, then close its event loop.

    ``replay`` reuses the engine's already-wired subscriptions (a
    ``CommandDispatcher`` for a command stream, the handler class otherwise) so
    it can dispatch through the real handler. ``Engine()`` opens its own event
    loop that ``asyncio.run`` never uses, so close it in every case; the
    in-process CLI test runner would otherwise leak a loop per invocation. A
    construction that fails closes its own loop (``Engine.__init__``), so it
    needs no handling here.
    """
    from protean.server import Engine  # noqa: PLC0415

    engine = Engine(domain, test_mode=True)
    try:
        yield engine
    finally:
        engine.loop.close()


def _owner_subscription(
    engine: Engine, failed_stream: str
) -> EventStoreSubscription | None:
    """Return the engine's event-store subscription writing to ``failed_stream``.

    Matches on the failed-positions stream name, the one string both the writer
    (the subscription) and the reader (``collect_failed_streams``) derive, so a
    command stream resolves to its ``CommandDispatcher`` subscription. Returns
    ``None`` if no subscription owns the stream.
    """
    from protean.server.subscription.event_store_subscription import (  # noqa: PLC0415
        EventStoreSubscription,
    )

    for sub in engine.subscriptions.values():
        if (
            isinstance(sub, EventStoreSubscription)
            and sub.failed_positions_stream == failed_stream
        ):
            return sub
    return None


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
                    "handler": info.subscription_fqn,
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


def _double_apply_line(info: SubscriptionInfo, event: Message, position: int) -> str:
    """Describe replay's double-apply risk for the confirmation prompt.

    Every replay re-runs the handler and can apply its side effects again: replay
    dispatches out-of-band and never consults the idempotency store, and an
    exhausted command never recorded a success to deduplicate against anyway. The
    line names the target so the operator knows what they are re-running, and
    calls out an idempotency key where one is present, since it is the only lever
    the operator has to make the re-run idempotent.
    """
    headers = event.metadata.headers if event.metadata else None
    idempotency_key = headers.idempotency_key if headers else None
    if info.is_command_handler and idempotency_key:
        return (
            f"Position {position} targets a command with an idempotency key. Replay "
            f"dispatches out-of-band without the idempotency store, so it re-runs "
            f"the handler; its side effects apply again unless the handler itself "
            f"honours the key."
        )
    if info.is_command_handler:
        return (
            f"Position {position} targets a command with no idempotency key. Replay "
            f"re-runs its handler and can apply side effects a second time."
        )
    return (
        f"Position {position} targets an event handler. Replay re-runs its handler "
        f"and can apply side effects a second time."
    )


@dlq_app.command()
@handle_cli_exceptions("eventstore dlq replay")
def replay(
    position: Annotated[
        int, typer.Argument(help="Exhausted global position to replay")
    ],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    subscription: Annotated[
        str | None,
        typer.Option(help="Stream category to search in"),
    ] = None,
    handler: Annotated[
        str | None,
        typer.Option(
            help="Handler (its fqn or class name) when a position is exhausted in more than one"
        ),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt")
    ] = False,
) -> None:
    """Re-drive one exhausted position through its handler.

    Reads the failing event and dispatches it to the handler exactly once. On
    success it records a resolution so the position stops being listed as
    exhausted and exits 0; on a repeat failure it reopens the position for the
    recovery pass and exits 1 (the handler reason is in the logs). The
    subscription read cursor is never moved.

    Replay re-runs handler side effects, so it confirms first, naming the target
    (an event handler, or a command with or without an idempotency key). Pass
    ``--yes`` to skip the prompt. The position's latest status is re-read right
    before the dispatch, so a position another replay or purge cleared while the
    prompt was open is refused.
    """
    derived_domain = load_domain(domain)

    with derived_domain.domain_context():
        store = derived_domain.event_store.store
        assert store is not None  # guaranteed by load_domain -> init()

        info, failed_stream, record = _resolve_exhausted_owner(
            store, derived_domain, subscription, handler, position
        )

        event = _read_failing_event(store, record, position)
        if event is None:
            emit_usage_error(
                as_json=False,
                message=f"Could not re-read the event for exhausted position {position}.",
            )

        # A command whose deadline elapsed is skipped by the engine (the handler
        # never runs) yet reported as handled, so a replay would falsely resolve
        # it. Refuse and point the operator at purge, before any dispatch.
        headers = event.metadata.headers if event.metadata else None
        if headers and headers.is_expired():
            emit_usage_error(
                as_json=False,
                message=(
                    f"Position {position} targets a command whose deadline has "
                    f"passed; the engine would skip its handler. Purge it instead."
                ),
            )

        print(f"[yellow]{_double_apply_line(info, event, position)}[/yellow]")
        if not yes:
            typer.confirm(f"Replay exhausted position {position}?", abort=True)

        event_type = (headers.type if headers else None) or "unknown"
        event_id = (headers.id if headers else None) or "unknown"

        with _redrive_engine(derived_domain) as engine:
            owner_sub = _owner_subscription(engine, failed_stream)
            if (
                owner_sub is None
            ):  # pragma: no cover (every failed stream has a live subscription)
                emit_usage_error(
                    as_json=False,
                    message=f"No live subscription owns the failed stream for position {position}.",
                )
            _still_exhausted_or_abort(store, failed_stream, position)
            resolved = asyncio.run(
                owner_sub.replay_exhausted(
                    event,
                    position,
                    message_type=event_type,
                    message_id=event_id,
                    stream_name=record.data.get("stream_name"),
                    stream_position=record.data.get("stream_position"),
                    retry_count=record.data.get("retry_count", 0),
                )
            )

    if resolved:
        print(f"Replayed position {position}: handler succeeded, position resolved.")
        return
    # Reopened: the handler failed again. Exit non-zero so a script can tell a
    # reopen from a resolution; the failure reason is in the engine logs.
    print(
        f"Replayed position {position}: handler failed again, position reopened "
        f"for recovery."
    )
    raise typer.Exit(code=EXIT_FAILURE)


@dlq_app.command()
@handle_cli_exceptions("eventstore dlq purge")
def purge(
    position: Annotated[int, typer.Argument(help="Exhausted global position to purge")],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    subscription: Annotated[
        str | None,
        typer.Option(help="Stream category to search in"),
    ] = None,
    handler: Annotated[
        str | None,
        typer.Option(
            help="Handler (its fqn or class name) when a position is exhausted in more than one"
        ),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt")
    ] = False,
) -> None:
    """Clear an exhausted position by appending a terminal Purged marker.

    The ``failed-*`` streams are append-only, so purge keeps the record history
    and writes a new ``Purged`` record after the ``Exhausted`` one. The position
    stops being listed as exhausted and a later rebuild does not re-track it.
    Purge does not re-run the handler, so it needs no engine. Pass ``--yes`` to
    skip the prompt. The position's latest status is re-read right before the
    marker is appended, so a position another replay or purge cleared while the
    prompt was open is refused.
    """
    from protean.server.subscription.event_store_subscription import (  # noqa: PLC0415
        FailedPositionStatus,
        write_recovery_status_record,
    )

    derived_domain = load_domain(domain)

    with derived_domain.domain_context():
        store = derived_domain.event_store.store
        assert store is not None  # guaranteed by load_domain -> init()

        info, failed_stream, record = _resolve_exhausted_owner(
            store, derived_domain, subscription, handler, position
        )

        if not yes:
            typer.confirm(
                f"Purge exhausted position {position}? This appends a terminal marker; "
                f"the record history is kept.",
                abort=True,
            )

        _still_exhausted_or_abort(store, failed_stream, position)
        write_recovery_status_record(
            store,
            failed_stream,
            info.stream_category,
            derived_domain.clock.now().isoformat(),
            position,
            FailedPositionStatus.PURGED,
            retry_count=record.data.get("retry_count", 0),
            message_type=record.data.get("message_type", "unknown"),
            message_id=record.data.get("message_id", "unknown"),
            stream_name=record.data.get("stream_name"),
            stream_position=record.data.get("stream_position"),
        )

    print(f"Purged position {position}.")
