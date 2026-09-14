"""CLI command for recovering after an event-store restore.

Usage::

    # Flag checkpoints that point past the restored stream head
    protean recover --verify-checkpoints --domain=my_domain

    # Machine-readable JSON
    protean recover --verify-checkpoints --domain=my_domain --json

    # Snap any beyond-head checkpoint back to the stream head
    protean recover --verify-checkpoints --reset-beyond-head --domain=my_domain

Restoring an event store from a backup can leave a subscription's checkpoint
ahead of the stream it consumes: the checkpoint stream was backed up after the
category stream, so it names a position the restored store no longer holds. Such
a subscription would skip every event between the head and the stale checkpoint.
``--verify-checkpoints`` reports those subscriptions so an operator can reset
them before starting the engine. ``--reset-beyond-head`` snaps each beyond-head
checkpoint back to the stream head. Without it, no run modifies any checkpoint.
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
    EXIT_OK,
    EXIT_USAGE,
    EnvelopeStatus,
    build_envelope,
    emit_usage_error,
    route_logs_to_stderr,
)
from protean.utils.logging import get_logger

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.server.subscription_status import (
        RecoveryCheckpointStatus,
        SubscriptionStatus,
    )

logger = get_logger(__name__)


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


def _perform_resets(
    domain: Domain,
    statuses: list[SubscriptionStatus],
    verdicts: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Snap every beyond-head checkpoint back to its stream head.

    Resets only the ``beyond_head`` subscriptions; a ``consistent`` one needs no
    reset and an ``unknown`` one was never verified, so neither is touched.
    Returns two lists: the resets that succeeded (each naming the subscription,
    its stale checkpoint, and the head it was snapped to) and the resets that
    failed (each naming the subscription and the error). A write that fails is
    recorded and the loop moves on, so one unreachable checkpoint does not strand
    the rest. Each successful write is durable on its own, and re-running the
    command finds fewer beyond-head checkpoints.
    """
    from protean.server.subscription_status import (  # noqa: PLC0415
        reset_checkpoint_to_head,
    )

    resets: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for status, verdict in zip(statuses, verdicts, strict=True):
        if verdict != "beyond_head":
            continue
        try:
            new_position = reset_checkpoint_to_head(domain, status)
        except Exception as exc:
            # A write can fail (store down, IO error). Record it and carry on so
            # the reachable checkpoints still get reset; the run reports the
            # failure and exits non-zero.
            logger.exception(
                "recover.reset_failed",
                subscription=status.name,
                stream=status.stream_category,
            )
            failures.append(
                {
                    "name": status.name,
                    "handler_name": status.handler_name,
                    "stream_category": status.stream_category,
                    "error": str(exc),
                }
            )
            continue
        resets.append(
            {
                "name": status.name,
                "handler_name": status.handler_name,
                "stream_category": status.stream_category,
                "previous_position": status.current_position,
                "new_position": str(new_position),
            }
        )
    return resets, failures


def _perform_recovery_resets(
    domain: Domain,
    findings: list[RecoveryCheckpointStatus],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop every beyond-head recovery-tracking entry from each finding.

    Returns two lists: the resets that succeeded (each naming the subscription
    and the positions cleared) and the resets that failed (each naming the
    subscription and the error). A write that fails is recorded and the loop
    moves on, so one unreachable checkpoint does not strand the rest. Each
    successful write is durable on its own, and re-running the command finds
    fewer stale entries.
    """
    from protean.server.subscription_status import (  # noqa: PLC0415
        reset_recovery_checkpoint,
    )

    resets: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for finding in findings:
        try:
            cleared = reset_recovery_checkpoint(domain, finding)
        except Exception as exc:
            # A write can fail (store down, IO error). Record it and carry on so
            # the reachable checkpoints still get pruned; the run reports the
            # failure and exits non-zero.
            logger.exception(
                "recover.recovery_reset_failed",
                subscription=finding.name,
                stream=finding.stream_category,
            )
            failures.append(
                {
                    "name": finding.name,
                    "handler_name": finding.handler_name,
                    "stream_category": finding.stream_category,
                    "error": str(exc),
                }
            )
            continue
        resets.append(
            {
                "name": finding.name,
                "handler_name": finding.handler_name,
                "stream_category": finding.stream_category,
                "cleared_positions": cleared,
            }
        )
    return resets, failures


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
    reset_beyond_head: Annotated[
        bool,
        typer.Option(
            "--reset-beyond-head",
            help=(
                "Snap each beyond-head checkpoint back to the stream head "
                "(requires --verify-checkpoints)"
            ),
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
    restore from an inconsistent backup can leave behind. It also reports any
    subscription whose recovery pass tracks a failed position past the restored
    head (which the pass would re-read and retry forever), and any whose recovery
    streams could not be read. It exits ``1`` when a checkpoint or a
    recovery-tracking entry is beyond head, ``0`` when all are consistent. Only
    event-store subscriptions track checkpoints, so broker and stream
    subscriptions are not examined.

    Add ``--reset-beyond-head`` to snap each beyond-head checkpoint back to the
    stream head and clear each stale recovery-tracking entry. The reset run
    reports what it changed and exits ``0``; a later ``--verify-checkpoints`` run
    then finds those subscriptions consistent. ``--reset-beyond-head`` needs
    ``--verify-checkpoints`` (that pass finds what to reset), and without it no
    run modifies any checkpoint or recovery-tracking stream.

    Under ``--json`` the result is the shared CLI result envelope, with the
    per-subscription list under ``data.subscriptions`` and counts under
    ``data.summary``. A recovery-tracking finding adds a ``data.recovery`` list
    and ``data.summary.recovery_*`` counts. With ``--reset-beyond-head`` the
    envelope also carries ``data.reset`` / ``data.recovery_reset`` lists of what
    changed and matching ``data.summary`` counts.
    """
    if reset_beyond_head and not verify_checkpoints:
        # The reset acts on what the verification pass finds, so it cannot run on
        # its own. Fail as a usage error rather than silently doing nothing.
        emit_usage_error(
            as_json=output_json,
            message="--reset-beyond-head requires --verify-checkpoints.",
        )

    if not verify_checkpoints:
        # Verification is the entry action; the reset builds on it. Without the
        # flag there is nothing to do, so print the hint and exit cleanly.
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
        collect_recovery_checkpoint_statuses,
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

    # A second class of beyond-head violation: a subscription's recovery pass
    # tracks failed positions the restore rolled off the end of the stream, which
    # it would re-read and retry forever. This is read-only. A finding is either
    # a stale entry ("stale") or a subscription whose recovery streams could not
    # be read ("unknown"), reported so it is not silently passed as clean.
    recovery_findings = collect_recovery_checkpoint_statuses(
        derived_domain, event_store_statuses
    )
    recovery_stale = [f for f in recovery_findings if f.verdict == "stale"]
    recovery_unknown = [f for f in recovery_findings if f.verdict == "unknown"]

    # Only --reset-beyond-head writes; a plain --verify-checkpoints run never
    # modifies a checkpoint or a recovery-tracking stream. Only the stale findings
    # are reset; an unknown one has nothing reconstructed to rewrite.
    resets: list[dict[str, Any]] = []
    reset_failures: list[dict[str, Any]] = []
    recovery_resets: list[dict[str, Any]] = []
    recovery_reset_failures: list[dict[str, Any]] = []
    if reset_beyond_head:
        resets, reset_failures = _perform_resets(
            derived_domain, event_store_statuses, verdicts
        )
        recovery_resets, recovery_reset_failures = _perform_recovery_resets(
            derived_domain, recovery_stale
        )

    # Exit/verdict:
    # - a reset write failure (checkpoint or recovery) is an environment error
    #   -> "error", exit 2;
    # - a plain verify run flags a beyond-head checkpoint or a stale
    #   recovery-tracking entry -> "fail", exit 1 (with --reset-beyond-head those
    #   are cleared, so they do not fail); an unknown recovery finding does not
    #   fail, matching how an unknown checkpoint is handled;
    # - otherwise the run passes -> exit 0.
    envelope_status: EnvelopeStatus
    if reset_failures or recovery_reset_failures:
        envelope_status = "error"
        exit_code = EXIT_USAGE
    elif (beyond > 0 or recovery_stale) and not reset_beyond_head:
        envelope_status = "fail"
        exit_code = EXIT_FAILURE
    else:
        envelope_status = "pass"
        exit_code = EXIT_OK

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
        summary: dict[str, Any] = {
            "checked": total,
            "consistent": consistent,
            "beyond_head": beyond,
            "unknown": unknown,
        }
        data: dict[str, Any] = {"subscriptions": subscriptions, "summary": summary}
        # Only widen the payload under --reset-beyond-head so a plain
        # --verify-checkpoints --json run keeps its exact documented shape.
        if reset_beyond_head:
            summary["reset"] = len(resets)
            summary["reset_failed"] = len(reset_failures)
            data["reset"] = resets
            data["reset_failures"] = reset_failures
        # Only widen the payload with recovery-tracking keys when there is a
        # finding, so a run with no recovery finding keeps its exact shape.
        if recovery_findings:
            data["recovery"] = [
                {
                    "name": f.name,
                    "handler_name": f.handler_name,
                    "stream_category": f.stream_category,
                    "recovery_checkpoint_stream": f.recovery_checkpoint_stream,
                    "head_position": f.head_position,
                    "verdict": f.verdict,
                    "stale_positions": f.stale_positions,
                }
                for f in recovery_findings
            ]
            summary["recovery_stale"] = len(recovery_stale)
            summary["recovery_stale_positions"] = sum(
                len(f.stale_positions) for f in recovery_stale
            )
            summary["recovery_unknown"] = len(recovery_unknown)
            if reset_beyond_head:
                summary["recovery_reset"] = sum(
                    len(r["cleared_positions"]) for r in recovery_resets
                )
                summary["recovery_reset_failed"] = len(recovery_reset_failures)
                data["recovery_reset"] = recovery_resets
                data["recovery_reset_failures"] = recovery_reset_failures
        envelope = build_envelope(
            status=envelope_status,
            data=data,
            diagnostics=[],
        )
        typer.echo(json.dumps(envelope, indent=2, sort_keys=True, default=str))
        raise typer.Exit(code=exit_code)

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
    # guards. Report the counts apart, and name both causes: the store may be
    # offline (no position recorded) or the stored position may not be numeric.
    # Unknown is not a violation, so it does not change the exit code.
    unverified = (
        f" [yellow]{unknown} could not be verified (no position recorded, "
        f"or the position is not a number).[/yellow]"
        if unknown
        else ""
    )
    # A subscription whose recovery streams could not be read is reported apart,
    # so it is never read as "no stale entry". Like an unknown checkpoint, it does
    # not change the exit code.
    recovery_unverified = (
        f"[yellow]{len(recovery_unknown)} recovery-tracking subscription(s) could "
        f"not be verified (the recovery streams could not be read).[/yellow]"
        if recovery_unknown
        else ""
    )

    if reset_beyond_head:
        if resets:
            print(
                f"\n[green]Reset {len(resets)} beyond-head checkpoint(s) to the "
                f"stream head:[/green]"
            )
            for r in resets:
                print(
                    f"  {r['handler_name']} ({r['stream_category']}): "
                    f"{r['previous_position']} -> {r['new_position']}"
                )
        elif not reset_failures and not recovery_stale:
            # Genuinely nothing beyond head in either lane. Say so only when no
            # reset was even attempted; when an attempt failed, or a recovery
            # entry was cleared, the blocks below report it, so "none to reset"
            # would contradict them.
            print("\n[green]No beyond-head checkpoints to reset.[/green]")
        if reset_failures:
            print(
                f"\n[red]{len(reset_failures)} checkpoint(s) could not be reset:[/red]"
            )
            for f in reset_failures:
                print(f"  {f['handler_name']} ({f['stream_category']}): {f['error']}")
        if recovery_resets:
            cleared_count = sum(len(r["cleared_positions"]) for r in recovery_resets)
            print(
                f"\n[green]Cleared {cleared_count} stale recovery-tracking "
                f"entry(ies) past the stream head:[/green]"
            )
            for r in recovery_resets:
                positions = ", ".join(str(p) for p in r["cleared_positions"])
                print(f"  {r['handler_name']} ({r['stream_category']}): {positions}")
        if recovery_reset_failures:
            print(
                f"\n[red]{len(recovery_reset_failures)} recovery checkpoint(s) "
                f"could not be reset:[/red]"
            )
            for f in recovery_reset_failures:
                print(f"  {f['handler_name']} ({f['stream_category']}): {f['error']}")
        if unverified:
            print(unverified.strip())
        if recovery_unverified:
            print(recovery_unverified)
        raise typer.Exit(code=exit_code)

    if beyond or recovery_stale:
        if beyond:
            print(
                f"\n[red]{beyond} of {total} checkpoint(s) point past the "
                f"restored head.[/red] Reset them before starting the engine."
            )
        if recovery_stale:
            stale_count = sum(len(f.stale_positions) for f in recovery_stale)
            print(
                f"\n[red]{stale_count} recovery-tracking entry(ies) across "
                f"{len(recovery_stale)} subscription(s) point past the restored "
                f"head.[/red] Reset them before starting the engine."
            )
            for finding in recovery_stale:
                positions = ", ".join(str(p) for p in finding.stale_positions)
                print(
                    f"  {finding.handler_name} ({finding.stream_category}): {positions}"
                )
        if unverified:
            print(unverified.strip())
        if recovery_unverified:
            print(recovery_unverified)
        raise typer.Exit(code=exit_code)

    if unknown or recovery_unknown:
        # No violation, but some subscription could not be verified. Report the
        # consistent count, then name what could not be checked (a checkpoint or a
        # recovery stream) so it is never read as clean.
        print(
            f"\n[green]{consistent} checkpoint(s) consistent with the stream "
            f"head.[/green]{unverified}"
        )
        if recovery_unverified:
            print(recovery_unverified)
        return

    print(
        f"\n[green]All {total} checkpoint(s) consistent with the stream head.[/green]"
    )
