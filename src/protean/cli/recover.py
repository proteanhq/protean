"""CLI command for recovering after an event-store restore.

Usage::

    # Flag beyond-head checkpoints and stale recovery-tracking entries
    protean recover --verify-checkpoints --domain=my_domain

    # Machine-readable JSON
    protean recover --verify-checkpoints --domain=my_domain --json

    # Reset each beyond-head checkpoint and clear each stale recovery entry
    protean recover --verify-checkpoints --reset-beyond-head --domain=my_domain

Restoring an event store from a backup can leave a subscription's checkpoint
ahead of the stream it consumes: the checkpoint stream was backed up after the
category stream, so it names a position the restored store no longer holds. Such
a subscription would skip every event between the head and the stale checkpoint.
The same restore can leave an event-store subscription's recovery pass tracking
failed positions whose message the restored store no longer holds, which it would
re-read and retry forever. ``--verify-checkpoints`` reports both so an operator
can reset them before starting the engine. ``--reset-beyond-head`` snaps each
beyond-head checkpoint back to the stream head and clears each stale
recovery-tracking entry. Without it, no run modifies any checkpoint or
recovery-tracking stream.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
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
    """Clear the stale recovery-tracking entries from each finding.

    Each finding here is a ``"stale"`` one, so its ``stale_positions`` are the
    ones whose message the restored store no longer holds. Returns two lists: the
    resets that succeeded (each naming the subscription and the positions cleared)
    and the resets that failed (each naming the subscription and the error). A
    write that fails is recorded and the loop
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
            help=(
                "Flag checkpoints past the restored head and recovery-tracking "
                "entries whose message the restore removed"
            ),
        ),
    ] = False,
    reset_beyond_head: Annotated[
        bool,
        typer.Option(
            "--reset-beyond-head",
            help=(
                "Snap each beyond-head checkpoint back to the head and clear each "
                "stale recovery-tracking entry (requires --verify-checkpoints)"
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

    With ``--verify-checkpoints``, report each event-store subscription whose
    checkpoint points past the head of the stream it consumes, and each
    recovery-tracking entry whose message the restored store no longer holds. A
    subscription whose recovery streams cannot be read is reported as
    ``unknown``. Broker and stream subscriptions are not examined. The run exits
    ``1`` when a checkpoint is beyond head or a recovery-tracking entry is stale,
    and ``0`` otherwise. Without ``--verify-checkpoints`` the command prints a
    hint and exits ``0``.

    Add ``--reset-beyond-head`` to move each beyond-head checkpoint back to the
    stream head and clear each stale recovery-tracking entry. The reset run
    reports what it changed and exits ``0``, or ``2`` if a write fails.
    ``--reset-beyond-head`` requires ``--verify-checkpoints``. Without it, no run
    changes any checkpoint or recovery-tracking stream.

    ``--json`` prints the shared CLI result envelope. The ``protean recover``
    reference page lists its fields.
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
            "past the restored head and stale recovery-tracking entries."
        )
        return

    if output_json:
        # Route logs to stderr before the domain import so a stray import-time
        # log cannot corrupt the machine payload on stdout.
        route_logs_to_stderr(
            log_already_configured=bool((ctx.obj or {}).get(CTX_LOG_CONFIGURED))
        )

    derived_domain = load_domain(domain, as_json=output_json)
    run = _verify(derived_domain, reset_beyond_head)
    envelope_status, exit_code = _outcome(run)

    if output_json:
        envelope = build_envelope(
            status=envelope_status,
            data=_json_data(run),
            diagnostics=[],
        )
        typer.echo(json.dumps(envelope, indent=2, sort_keys=True, default=str))
        raise typer.Exit(code=exit_code)

    if not run.statuses:
        print("No event-store subscriptions found in domain.")
        return

    _print_table(derived_domain.name, run)
    _print_text_report(run, exit_code)


@dataclass
class _Run:
    """What one ``recover --verify-checkpoints`` run found and changed.

    ``statuses`` holds only the event-store subscriptions, with ``verdicts`` in
    the same order. The four reset lists stay empty unless ``reset_beyond_head``
    is set.
    """

    reset_beyond_head: bool
    statuses: list[SubscriptionStatus]
    verdicts: list[str]
    recovery_findings: list[RecoveryCheckpointStatus]
    recovery_stale: list[RecoveryCheckpointStatus]
    recovery_unknown: list[RecoveryCheckpointStatus]
    resets: list[dict[str, Any]] = field(default_factory=list)
    reset_failures: list[dict[str, Any]] = field(default_factory=list)
    recovery_resets: list[dict[str, Any]] = field(default_factory=list)
    recovery_reset_failures: list[dict[str, Any]] = field(default_factory=list)


def _verify(derived_domain: Domain, reset_beyond_head: bool) -> _Run:
    """Collect the checkpoint and recovery-tracking findings, resetting them on request."""
    from protean.server.subscription_status import (  # noqa: PLC0415
        collect_recovery_checkpoint_statuses,
        collect_subscription_statuses,
    )

    with derived_domain.domain_context():
        statuses = collect_subscription_statuses(derived_domain)

    # Only event-store subscriptions track checkpoints; broker and stream
    # subscriptions do not, so "beyond the restored head" does not apply.
    event_store_statuses = [s for s in statuses if s.subscription_type == "event_store"]
    verdicts = [_verdict(s) for s in event_store_statuses]

    # A second class of restore damage: a subscription's recovery pass tracks
    # failed positions whose message the restore removed (a rolled-back category,
    # or a removed specific aggregate stream that can sit below the category
    # head), which it would re-read and retry forever. This is read-only. A
    # finding is either a stale entry ("stale") or a subscription whose recovery
    # streams could not be read ("unknown"), reported so it is not silently passed
    # as clean.
    recovery_findings = collect_recovery_checkpoint_statuses(
        derived_domain, event_store_statuses
    )
    run = _Run(
        reset_beyond_head=reset_beyond_head,
        statuses=event_store_statuses,
        verdicts=verdicts,
        recovery_findings=recovery_findings,
        recovery_stale=[f for f in recovery_findings if f.verdict == "stale"],
        recovery_unknown=[f for f in recovery_findings if f.verdict == "unknown"],
    )

    # Only --reset-beyond-head writes; a plain --verify-checkpoints run never
    # modifies a checkpoint or a recovery-tracking stream. Only the stale findings
    # are reset; an unknown one has nothing reconstructed to rewrite.
    if reset_beyond_head:
        run.resets, run.reset_failures = _perform_resets(
            derived_domain, event_store_statuses, verdicts
        )
        run.recovery_resets, run.recovery_reset_failures = _perform_recovery_resets(
            derived_domain, run.recovery_stale
        )
    return run


def _outcome(run: _Run) -> tuple[EnvelopeStatus, int]:
    """Return the envelope status and exit code for a finished run.

    - a reset write failure (checkpoint or recovery) is an environment error
      -> "error", exit 2;
    - a plain verify run flags a beyond-head checkpoint or a stale
      recovery-tracking entry -> "fail", exit 1 (with --reset-beyond-head those
      are cleared, so they do not fail); an unknown recovery finding does not
      fail, matching how an unknown checkpoint is handled;
    - otherwise the run passes -> exit 0.
    """
    if run.reset_failures or run.recovery_reset_failures:
        return "error", EXIT_USAGE
    beyond = run.verdicts.count("beyond_head")
    if (beyond > 0 or run.recovery_stale) and not run.reset_beyond_head:
        return "fail", EXIT_FAILURE
    return "pass", EXIT_OK


def _json_data(run: _Run) -> dict[str, Any]:
    """Build the ``data`` payload of the ``--json`` envelope."""
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
        for s, v in zip(run.statuses, run.verdicts, strict=True)
    ]
    summary: dict[str, Any] = {
        "checked": len(run.statuses),
        "consistent": run.verdicts.count("consistent"),
        "beyond_head": run.verdicts.count("beyond_head"),
        "unknown": run.verdicts.count("unknown"),
    }
    data: dict[str, Any] = {"subscriptions": subscriptions, "summary": summary}
    # Only widen the payload under --reset-beyond-head so a plain
    # --verify-checkpoints --json run keeps its exact documented shape.
    if run.reset_beyond_head:
        summary["reset"] = len(run.resets)
        summary["reset_failed"] = len(run.reset_failures)
        data["reset"] = run.resets
        data["reset_failures"] = run.reset_failures
    # Only widen the payload with recovery-tracking keys when there is a
    # finding, so a run with no recovery finding keeps its exact shape.
    if run.recovery_findings:
        _add_recovery_json(run, data, summary)
    return data


def _add_recovery_json(
    run: _Run, data: dict[str, Any], summary: dict[str, Any]
) -> None:
    """Add the recovery-tracking keys to the ``--json`` payload and its summary."""
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
        for f in run.recovery_findings
    ]
    summary["recovery_stale"] = len(run.recovery_stale)
    summary["recovery_stale_positions"] = sum(
        len(f.stale_positions) for f in run.recovery_stale
    )
    summary["recovery_unknown"] = len(run.recovery_unknown)
    if run.reset_beyond_head:
        summary["recovery_reset"] = sum(
            len(r["cleared_positions"]) for r in run.recovery_resets
        )
        summary["recovery_reset_failed"] = len(run.recovery_reset_failures)
        data["recovery_reset"] = run.recovery_resets
        data["recovery_reset_failures"] = run.recovery_reset_failures


_VERDICT_CELL = {
    "beyond_head": "[red]beyond head[/red]",
    "unknown": "[yellow]unknown[/yellow]",
    "consistent": "[green]consistent[/green]",
}


def _print_table(domain_name: str, run: _Run) -> None:
    """Print one row per event-store subscription with its verdict."""
    table = Table(title=f"Checkpoint verification: {domain_name}")
    table.add_column("Handler", style="bold")
    table.add_column("Stream")
    table.add_column("Checkpoint", justify="right")
    table.add_column("Head", justify="right")
    table.add_column("Verdict")

    for s, v in zip(run.statuses, run.verdicts, strict=True):
        table.add_row(
            s.handler_name,
            s.stream_category,
            s.current_position if s.current_position is not None else "-",
            s.head_position if s.head_position is not None else "-",
            _VERDICT_CELL[v],
        )

    print(table)


def _unverified_text(unknown: int) -> str:
    """Return the note on checkpoints that could not be verified, or ``""``."""
    # An unknown row was never actually verified, so a summary that folds it into
    # "consistent" would state a falsehood in the exact scenario this command
    # guards. Report the counts apart, and name both causes: the store may be
    # offline (no position recorded) or the stored position may not be numeric.
    # Unknown is not a violation, so it does not change the exit code.
    if not unknown:
        return ""
    return (
        f" [yellow]{unknown} could not be verified (no position recorded, "
        f"or the position is not a number).[/yellow]"
    )


def _recovery_unverified_text(recovery_unknown: list[RecoveryCheckpointStatus]) -> str:
    """Return the note naming each unreadable recovery-tracking subscription, or ``""``."""
    # A subscription whose recovery tracking could not be read is reported apart,
    # so it is never read as "no stale entry". Like an unknown checkpoint, it does
    # not change the exit code. Name each one, so with more than one an operator
    # can tell which handler and category to look at.
    if not recovery_unknown:
        return ""
    lines = [
        (
            f"[yellow]{len(recovery_unknown)} recovery-tracking subscription(s) "
            "could not be verified (the recovery streams, or a tracked message, "
            "could not be read):[/yellow]"
        )
    ]
    lines += [f"  {f.handler_name} ({f.stream_category})" for f in recovery_unknown]
    return "\n".join(lines)


def _print_text_report(run: _Run, exit_code: int) -> None:
    """Print the text summary under the table.

    Raises ``typer.Exit`` with ``exit_code`` after a reset run or a run that
    found a violation; returns for a run that found none.
    """
    beyond = run.verdicts.count("beyond_head")
    unknown = run.verdicts.count("unknown")
    unverified = _unverified_text(unknown)
    recovery_unverified = _recovery_unverified_text(run.recovery_unknown)

    if run.reset_beyond_head:
        _print_checkpoint_resets(run)
        _print_recovery_resets(run)
        _print_unverified(unverified, recovery_unverified)
        raise typer.Exit(code=exit_code)

    if beyond or run.recovery_stale:
        _print_violations(run, beyond)
        _print_unverified(unverified, recovery_unverified)
        raise typer.Exit(code=exit_code)

    if unknown or run.recovery_unknown:
        # No violation, but some subscription could not be verified. Report the
        # consistent count, then name what could not be checked (a checkpoint or a
        # recovery stream) so it is never read as clean.
        print(
            f"\n[green]{run.verdicts.count('consistent')} checkpoint(s) consistent "
            f"with the stream head.[/green]{unverified}"
        )
        if recovery_unverified:
            print(recovery_unverified)
        return

    print(
        f"\n[green]All {len(run.statuses)} checkpoint(s) consistent with the "
        f"stream head.[/green]"
    )


def _print_unverified(unverified: str, recovery_unverified: str) -> None:
    """Print the notes on what could not be verified, skipping empty ones."""
    if unverified:
        print(unverified.strip())
    if recovery_unverified:
        print(recovery_unverified)


def _print_checkpoint_resets(run: _Run) -> None:
    """Print the beyond-head checkpoints a reset run moved, and the ones it could not."""
    if run.resets:
        print(
            f"\n[green]Reset {len(run.resets)} beyond-head checkpoint(s) to the "
            f"stream head:[/green]"
        )
        for r in run.resets:
            print(
                f"  {r['handler_name']} ({r['stream_category']}): "
                f"{r['previous_position']} -> {r['new_position']}"
            )
    elif not run.reset_failures and not run.recovery_stale:
        # Genuinely nothing beyond head in either lane. Say so only when no
        # reset was even attempted; when an attempt failed, or a recovery
        # entry was cleared, the blocks below report it, so "none to reset"
        # would contradict them.
        print("\n[green]No beyond-head checkpoints to reset.[/green]")
    if run.reset_failures:
        print(
            f"\n[red]{len(run.reset_failures)} checkpoint(s) could not be reset:[/red]"
        )
        for f in run.reset_failures:
            print(f"  {f['handler_name']} ({f['stream_category']}): {f['error']}")


def _print_recovery_resets(run: _Run) -> None:
    """Print the recovery-tracking entries a reset run cleared, and the ones it could not."""
    if run.recovery_resets:
        cleared_count = sum(len(r["cleared_positions"]) for r in run.recovery_resets)
        print(
            f"\n[green]Cleared {cleared_count} stale recovery-tracking "
            f"entry(ies) whose message the restore removed:[/green]"
        )
        for r in run.recovery_resets:
            positions = ", ".join(str(p) for p in r["cleared_positions"])
            print(f"  {r['handler_name']} ({r['stream_category']}): {positions}")
    if run.recovery_reset_failures:
        print(
            f"\n[red]{len(run.recovery_reset_failures)} recovery checkpoint(s) "
            f"could not be reset:[/red]"
        )
        for f in run.recovery_reset_failures:
            print(f"  {f['handler_name']} ({f['stream_category']}): {f['error']}")


def _print_violations(run: _Run, beyond: int) -> None:
    """Print the beyond-head checkpoints and stale recovery-tracking entries found."""
    if beyond:
        print(
            f"\n[red]{beyond} of {len(run.statuses)} checkpoint(s) point past the "
            f"restored head.[/red] Reset them before starting the engine."
        )
    if run.recovery_stale:
        stale_count = sum(len(f.stale_positions) for f in run.recovery_stale)
        print(
            f"\n[red]{stale_count} recovery-tracking entry(ies) across "
            f"{len(run.recovery_stale)} subscription(s) name a message the "
            f"restored store no longer holds.[/red] Reset them before "
            f"starting the engine."
        )
        for finding in run.recovery_stale:
            positions = ", ".join(str(p) for p in finding.stale_positions)
            print(f"  {finding.handler_name} ({finding.stream_category}): {positions}")
