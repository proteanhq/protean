"""CLI commands for event-store integrity and maintenance.

Usage::

    # Check the event store's internal consistency
    protean eventstore verify --domain=my_domain

    # Machine-readable result (the shared CLI envelope)
    protean eventstore verify --domain=my_domain --json
"""

import json
from typing import Annotated

import typer
from rich import print
from rich.table import Table

from protean.cli._helpers import CTX_LOG_CONFIGURED, handle_cli_exceptions, load_domain
from protean.cli.result import EXIT_FAILURE, build_envelope, route_logs_to_stderr

app = typer.Typer(no_args_is_help=True)


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
