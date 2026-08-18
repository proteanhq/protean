"""CLI command for recovering after an event-store restore.

Usage::

    # Flag checkpoints that point past the restored stream head
    protean recover --verify-checkpoints --domain=my_domain

    # Machine-readable JSON
    protean recover --verify-checkpoints --domain=my_domain --json

Restoring an event store from a backup can leave a subscription's checkpoint
ahead of the stream it consumes: the checkpoint stream was backed up after the
category stream, so it names a position the restored store no longer holds. Such
a subscription would skip every event between the head and the stale checkpoint.
``--verify-checkpoints`` reports those subscriptions so an operator can reset
them before starting the engine.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated

import typer
from rich import print
from rich.table import Table

from protean.cli._helpers import CTX_LOG_CONFIGURED, handle_cli_exceptions, load_domain
from protean.cli.result import (
    EXIT_FAILURE,
    EXIT_OK,
    build_envelope,
    route_logs_to_stderr,
)

if TYPE_CHECKING:
    from protean.server.subscription_status import SubscriptionStatus

app = typer.Typer(no_args_is_help=True)


def _parse_position(position: str | None) -> int | None:
    """Parse a stored position string to an int, or ``None`` if it cannot.

    Event-store positions are numeric strings (``"-1"``, ``"42"``), but this
    command runs against restored or foreign stores, so a position can be
    missing (``None`` from ``_unknown_status``) or non-numeric (``"5.0"``,
    ``""``, ``"abc"``). Either way it cannot be compared, so treat it as
    unknown instead of raising.
    """
    if position is None:
        return None
    try:
        return int(position)
    except (TypeError, ValueError):
        return None


def _beyond_head(status: SubscriptionStatus) -> bool | None:
    """Return whether this event-store checkpoint points past the stream head.

    ``True`` when the recorded checkpoint is strictly ahead of the head (the
    restore left it stale), ``False`` when it is caught up or behind. ``None``
    when either position is missing or unparseable (an unreachable store returns
    ``_unknown_status`` with ``None`` positions, and a foreign store can hold a
    non-numeric position), so the caller can report it as unknown rather than
    parse ``int(None)`` or crash on ``int("abc")``.

    This is the un-clamped inverse of the lag formula ``lag = max(0, head -
    current)``, which clamps a beyond-head checkpoint to ``lag == 0`` and hides
    exactly the case this command exists to find. A fresh subscription carries
    ``current_position == "-1"`` (no checkpoint written yet); against any real
    head ``>= 0`` that reads as consistent.
    """
    current = _parse_position(status.current_position)
    head = _parse_position(status.head_position)
    if current is None or head is None:
        return None
    return current > head


def _verdict(status: SubscriptionStatus) -> str:
    """Map an event-store subscription to a verdict token.

    ``"beyond_head"`` when its checkpoint points past the head, ``"consistent"``
    when it is caught up or behind, ``"unknown"`` when either position is missing
    or unparseable. The token drives both the human table and the JSON payload so
    they cannot disagree.
    """
    beyond = _beyond_head(status)
    if beyond is None:
        return "unknown"
    return "beyond_head" if beyond else "consistent"


@app.command()
@handle_cli_exceptions("recover")
def recover(
    ctx: typer.Context,
    verify_checkpoints: Annotated[
        bool,
        typer.Option(
            "--verify-checkpoints",
            help="Flag checkpoints that point past the restored stream head",
        ),
    ] = False,
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output raw JSON instead of a table"),
    ] = False,
) -> None:
    """Recover a domain after an event-store restore.

    With ``--verify-checkpoints`` this reports every event-store subscription
    whose checkpoint points past the head of the stream it consumes, which a
    restore from an inconsistent backup can leave behind. It exits ``1`` when
    any such subscription exists, ``0`` when all checkpoints are consistent.
    Only event-store subscriptions track checkpoints, so broker and stream
    subscriptions are not examined.

    Under ``--json`` the result is the shared CLI result envelope, with the
    per-subscription list under ``data.subscriptions`` and counts under
    ``data.summary``.
    """
    if not verify_checkpoints:
        # ``--verify-checkpoints`` is the only supported action today; the write
        # path (resetting stale checkpoints) is its own issue. Without the flag
        # there is nothing to do, so print the hint and exit cleanly.
        print(
            "Nothing to do. Pass --verify-checkpoints to report checkpoints "
            "that point past the restored stream head."
        )
        return

    if output_json:
        # Route logs to stderr before the domain import so a stray import-time
        # log cannot corrupt the machine payload on stdout.
        route_logs_to_stderr(
            log_already_configured=bool((ctx.obj or {}).get(CTX_LOG_CONFIGURED))
        )

    from protean.server.subscription_status import (  # noqa: PLC0415
        collect_subscription_statuses,
    )

    derived_domain = load_domain(domain, as_json=output_json)

    with derived_domain.domain_context():
        statuses = collect_subscription_statuses(derived_domain)

    # Only event-store subscriptions track checkpoints; broker and stream
    # subscriptions do not, so "beyond the restored head" does not apply.
    event_store_statuses = [s for s in statuses if s.subscription_type == "event_store"]
    verdicts = [_verdict(s) for s in event_store_statuses]
    total = len(event_store_statuses)
    beyond = verdicts.count("beyond_head")
    unknown = verdicts.count("unknown")
    consistent = verdicts.count("consistent")

    if output_json:
        subscriptions = [
            {
                "name": s.name,
                "handler_name": s.handler_name,
                "stream_category": s.stream_category,
                "checkpoint_position": s.current_position,
                "head_position": s.head_position,
                "beyond_head": v == "beyond_head",
                "verdict": v,
            }
            for s, v in zip(event_store_statuses, verdicts, strict=True)
        ]
        summary = {
            "checked": total,
            "consistent": consistent,
            "beyond_head": beyond,
            "unknown": unknown,
        }
        envelope = build_envelope(
            status="fail" if beyond else "pass",
            data={"subscriptions": subscriptions, "summary": summary},
            diagnostics=[],
        )
        typer.echo(json.dumps(envelope, indent=2, sort_keys=True, default=str))
        raise typer.Exit(code=EXIT_FAILURE if beyond else EXIT_OK)

    if not event_store_statuses:
        print("No event-store subscriptions found in domain.")
        return

    table = Table(title=f"Checkpoint verification: {derived_domain.name}")
    table.add_column("Handler", style="bold")
    table.add_column("Stream")
    table.add_column("Checkpoint", justify="right")
    table.add_column("Head", justify="right")
    table.add_column("Verdict")

    _VERDICT_CELL = {
        "beyond_head": "[red]beyond head[/red]",
        "unknown": "[yellow]unknown[/yellow]",
        "consistent": "[green]consistent[/green]",
    }
    for s, v in zip(event_store_statuses, verdicts, strict=True):
        table.add_row(
            s.handler_name,
            s.stream_category,
            s.current_position if s.current_position is not None else "-",
            s.head_position if s.head_position is not None else "-",
            _VERDICT_CELL[v],
        )

    print(table)

    # An unknown row was never actually verified, so a summary that folds it into
    # "consistent" would state a falsehood in the exact scenario this command
    # guards. Report the counts apart. Unknown is not a violation (the store may
    # simply be offline), so it does not change the exit code.
    unverified = (
        f" [yellow]{unknown} could not be verified (store unreachable).[/yellow]"
        if unknown
        else ""
    )
    if beyond:
        print(
            f"\n[red]{beyond} of {total} checkpoint(s) point past the "
            f"restored head.[/red] Reset them before starting the engine."
            f"{unverified}"
        )
        raise typer.Exit(code=EXIT_FAILURE)

    if unknown:
        print(
            f"\n[green]{consistent} checkpoint(s) consistent with the stream "
            f"head.[/green]{unverified}"
        )
        return

    print(
        f"\n[green]All {total} checkpoint(s) consistent with the stream head.[/green]"
    )
