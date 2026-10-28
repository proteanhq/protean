"""CLI commands for the transactional outbox.

Usage::

    # Create outbox rows for events durable in the event store that are missing
    # their outbox row (recovers the ADR-0015 crash window).
    protean outbox reconcile --domain=my_domain

    # List the partition keys an abandoned row halts, and the rows waiting
    # behind each.
    protean outbox halted --domain=my_domain
    protean outbox halted --domain=my_domain --json

    # Release a halted key: publish the abandoned row again, or skip it.
    protean outbox retry <id> --domain=my_domain
    protean outbox discard <id> --reason "payload rejected by the broker" --domain=my_domain
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any, NoReturn, cast

import typer
from rich import print
from rich.markup import escape

from protean.cli._helpers import CTX_LOG_CONFIGURED, handle_cli_exceptions, load_domain
from protean.cli.result import build_envelope, emit_usage_error, route_logs_to_stderr
from protean.utils.outbox import HaltedKey, Outbox, OutboxRepository, reconcile_outbox

if TYPE_CHECKING:
    from protean.domain import Domain

app = typer.Typer(no_args_is_help=True)


def _require_outbox(derived_domain: Domain, *, as_json: bool = False) -> None:
    if derived_domain.has_outbox:
        return
    message = (
        "Outbox is not enabled for this domain. Enable it with "
        'default_subscription_type = "stream" under [server]. The older '
        "enable_outbox = true switch also needs that setting."
    )
    if as_json:
        emit_usage_error(as_json=True, message=message)
    print(escape(message))
    raise typer.Abort()


def _load_row(repo: OutboxRepository, row_id: str) -> Outbox:
    row = cast(Outbox | None, repo.get_or_none(row_id))
    if row is None:
        print(f"No outbox row with id {escape(row_id)}.")
        raise typer.Abort()
    return row


def _refuse(row_id: str, row: Outbox) -> NoReturn:
    print(
        f"Outbox row {escape(row_id)} is {row.status}. Only a failed or "
        "abandoned row can be retried or discarded."
    )
    raise typer.Abort()


@app.callback()
def callback() -> None:
    """Manage the transactional outbox."""


@app.command()
@handle_cli_exceptions("outbox reconcile")
def reconcile(
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    provider: Annotated[
        str, typer.Option(help="Provider whose outbox to reconcile")
    ] = "default",
    limit: Annotated[
        int, typer.Option(help="Most recent event-store messages to scan for gaps")
    ] = 1000,
) -> None:
    """Create outbox rows for events in the event store that are missing them.

    Recovers the ADR-0015 crash window: an event appended to the event store
    (the durable anchor) whose relational outbox commit did not land, so the
    event is durable but would never be published.
    """
    derived_domain = load_domain(domain)
    with derived_domain.domain_context():
        _require_outbox(derived_domain)

        created = reconcile_outbox(derived_domain, provider_name=provider, limit=limit)
        if created:
            print(f"Reconciled {created} outbox row(s) from the event store.")
        else:
            print(
                "Nothing to reconcile: no event in the scanned window is missing "
                "its outbox row."
            )


def _halted_entry(key: HaltedKey) -> dict[str, Any]:
    return {
        "target_broker": key.target_broker,
        "stream_category": key.stream_category,
        "partition_key": key.partition_key,
        "lane": key.lane,
        "head_id": str(key.head.id),
        "status": key.head.status,
        "last_error": key.head.last_error,
        "waiting": key.waiting,
    }


@app.command()
@handle_cli_exceptions("outbox halted")
def halted(
    ctx: typer.Context,
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    provider: Annotated[
        str, typer.Option(help="Provider whose outbox to inspect")
    ] = "default",
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output the result envelope as JSON"),
    ] = False,
) -> None:
    """List the partition keys that an abandoned outbox row halts.

    Each entry names the abandoned row at the head of the key and how many
    later rows of the key wait behind it. Release a key with ``protean outbox
    retry`` or ``protean outbox discard``. Under ``--json`` the result is the
    shared CLI result envelope, with the list under ``data.halted``.
    """
    if output_json:
        # Route logs to stderr before the domain import so a stray import-time
        # log cannot corrupt the machine payload on stdout.
        route_logs_to_stderr(
            log_already_configured=bool((ctx.obj or {}).get(CTX_LOG_CONFIGURED))
        )

    derived_domain = load_domain(domain, as_json=output_json)
    with derived_domain.domain_context():
        _require_outbox(derived_domain, as_json=output_json)
        keys = derived_domain._get_outbox_repo(provider).find_halted()

    if output_json:
        envelope = build_envelope(
            status="pass",
            data={"halted": [_halted_entry(key) for key in keys]},
            diagnostics=[],
        )
        typer.echo(json.dumps(envelope, indent=2, sort_keys=True, default=str))
        return

    if not keys:
        print("No partition key is halted.")
        return

    print(f"{len(keys)} halted partition key(s):")
    for key in keys:
        error = (key.head.last_error or {}).get("message", "no error recorded")
        print(
            f"- {escape(key.target_broker)} {escape(key.stream_category)} "
            f"key={escape(key.partition_key)} lane={key.lane}: "
            f"head row {escape(str(key.head.id))} is {key.head.status} "
            f"({escape(str(error))}), {key.waiting} row(s) waiting"
        )


@app.command()
@handle_cli_exceptions("outbox retry")
def retry(
    row_id: Annotated[str, typer.Argument(help="Id of the outbox row")],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    provider: Annotated[
        str, typer.Option(help="Provider whose outbox holds the row")
    ] = "default",
) -> None:
    """Publish a failed or abandoned outbox row again.

    The row goes back to pending with its retry count at zero, and the
    outbox processor claims it on its next poll. Later rows of its
    partition key publish after it.
    """
    derived_domain = load_domain(domain)
    with derived_domain.domain_context():
        _require_outbox(derived_domain)
        repo = derived_domain._get_outbox_repo(provider)
        row = _load_row(repo, row_id)
        if not row.reset_for_retry():
            _refuse(row_id, row)
        repo.add(row)

    print(f"Outbox row {escape(row_id)} is {row.status} and will be published again.")


@app.command()
@handle_cli_exceptions("outbox discard")
def discard(
    row_id: Annotated[str, typer.Argument(help="Id of the outbox row")],
    reason: Annotated[
        str, typer.Option(help="Why the row is skipped, kept on the row")
    ],
    domain: Annotated[str, typer.Option(help="Domain module path")] = ".",
    provider: Annotated[
        str, typer.Option(help="Provider whose outbox holds the row")
    ] = "default",
) -> None:
    """Skip a failed or abandoned outbox row for good.

    The row is never published. It stays in the outbox as discarded, with
    the reason in its ``last_error``, and the later rows of its partition key
    publish without it.
    """
    derived_domain = load_domain(domain)
    with derived_domain.domain_context():
        _require_outbox(derived_domain)
        repo = derived_domain._get_outbox_repo(provider)
        row = _load_row(repo, row_id)
        if not row.discard(reason):
            _refuse(row_id, row)
        repo.add(row)

    print(f"Outbox row {escape(row_id)} is {row.status} and will not be published.")
