"""CLI command for ``protean upgrade-check`` — upgrade-readiness diagnostics.

Inspects a loaded domain (and, where reachable, its live database schema) and
reports changes that may need operator attention when upgrading to a newer
Protean, with concrete remediation.

The checks accumulate across releases rather than targeting one. Each finding
names the release its change came from.

Nothing is applied automatically. Schema changes are *generated* as SQL for you
to review and run.

Usage::

    protean upgrade-check --domain=my_app
    protean upgrade-check --domain=my_app --format=json

Exit codes:
    0 — clean or advisory (info) only
    1 — warnings found (review recommended before upgrading), including a
        check that could not complete (``CHECK_FAILED``)
    2 — a usage or environment error: a bad option, a domain that does not
        load, or an error while initializing the domain or outside a single
        check. The message goes to stderr and stdout stays empty.
"""

import json
import re
from typing import Annotated, Any

import structlog
import typer
from rich import print
from rich.markup import escape

from protean import __version__
from protean.cli._helpers import (
    CTX_LOG_CONFIGURED,
    apply_domain_logging,
    handle_cli_exceptions,
)
from protean.cli.result import EXIT_FAILURE, emit_usage_error, route_logs_to_stderr
from protean.domain import Domain
from protean.exceptions import NoDomainException
from protean.upgrade import UpgradeFinding, run_upgrade_checks
from protean.upgrade_opportunities import run_opportunity_checks
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

logger = get_logger(__name__)

_LEVEL_STYLE = {"warning": "[yellow]warning[/yellow]", "info": "[cyan]info[/cyan]"}

# A pinned version is MAJOR.MINOR with an optional patch and an optional
# release tag: 0.16, 0.16.3, 0.15.0rc1, 0.17.0.dev1. Only the PEP 440 tags
# (a/b/rc/dev/post) with a numeric suffix are accepted, so a typo like
# "0.16latest" fails fast rather than parsing to a surprising tuple.
_PINNED_VERSION_RE = re.compile(
    r"^\d+\.\d+(\.\d+)?((a|b|rc)\d+|\.?(dev|post)\d+)?$",
)


@handle_cli_exceptions("upgrade-check")
def upgrade_check(
    ctx: typer.Context,
    domain: Annotated[
        str,
        typer.Option(
            "--domain",
            "-d",
            help="Path to the domain module (e.g. 'my_app.domain')",
        ),
    ] = ".",
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: 'rich' (default) or 'json'",
        ),
    ] = "rich",
    opportunities: Annotated[
        bool,
        typer.Option(
            "--opportunities",
            help=(
                "Report shipped capability the domain still hand-rolls, instead "
                "of upgrade-readiness changes"
            ),
        ),
    ] = False,
    pinned_version: Annotated[
        str | None,
        typer.Option(
            "--pinned-version",
            help=(
                "Version the domain is pinned to, for --opportunities "
                "(default: the installed Protean)"
            ),
        ),
    ] = None,
) -> None:
    """Report upgrade-readiness changes, or with --opportunities, shipped
    capability the domain still hand-rolls.

    \b
    Exit codes:
      0: clean, or info findings only
      1: warning findings, including a check that could not complete
         (CHECK_FAILED)
      2: usage or environment error (message on stderr, stdout empty)
    """
    # Route logs to stderr before ``derive_domain`` imports the domain module:
    # unconfigured structlog prints to stdout, and an error run must leave
    # stdout empty. Skip if the CLI's logging flags already configured it.
    parent_obj = ctx.obj or {}
    route_logs_to_stderr(
        log_already_configured=bool(parent_obj.get(CTX_LOG_CONFIGURED))
    )
    # A logger first used while the domain imports would cache the current
    # processor chain and keep it after apply_domain_logging adds the
    # [logging].redact processor. configure_logging turns the cache back on.
    structlog.configure(cache_logger_on_first_use=False)

    _validate_options(format, opportunities, pinned_version)
    derived_domain = _load_domain(domain)
    findings = _collect_findings(
        derived_domain, opportunities, pinned_version, parent_obj
    )

    if format == "json":
        typer.echo(json.dumps([f.as_dict() for f in findings], indent=2))
    else:
        _print_rich(derived_domain.name, findings)

    if any(f.level == "warning" for f in findings):
        raise typer.Exit(code=EXIT_FAILURE)


def _validate_options(
    format: str, opportunities: bool, pinned_version: str | None
) -> None:
    """Exit ``2`` on stderr when the options do not form a valid command."""
    if format not in ("rich", "json"):
        emit_usage_error(
            as_json=False,
            message=f"Invalid --format: {format!r}. Use 'rich' or 'json'.",
        )

    if pinned_version is not None and not opportunities:
        emit_usage_error(
            as_json=False,
            message="--pinned-version applies only with --opportunities.",
        )

    if pinned_version is not None and not _PINNED_VERSION_RE.match(pinned_version):
        emit_usage_error(
            as_json=False,
            message=(
                f"Invalid --pinned-version: {pinned_version!r}. "
                "Use a version like '0.16', '0.16.3', or '0.16.0rc1'."
            ),
        )


def _load_domain(domain_path: str) -> Domain:
    """Import the domain at ``domain_path``, or exit ``2`` on stderr."""
    try:
        derived_domain = derive_domain(domain_path)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        logger.error(msg)
        emit_usage_error(as_json=False, message=msg)
    except (Exception, SystemExit) as exc:
        # CLI boundary: importing user code can raise anything. Discovery
        # converts only ImportError to NoDomainException; a module that raises
        # anything else at import (a SyntaxError, a RuntimeError, a sys.exit
        # call) is still a domain that did not load. The traceback stays on
        # stderr at debug level.
        logger.debug("domain import failed", exc_info=True)
        msg = f"Error loading Protean domain: {_describe(exc)}"
        logger.error(msg)
        emit_usage_error(as_json=False, message=msg)

    # Discovery returns None when no path is given and nothing is found.
    if derived_domain is None:
        emit_usage_error(
            as_json=False, message="Error loading Protean domain: no domain found."
        )
    return derived_domain


def _collect_findings(
    derived_domain: Domain,
    opportunities: bool,
    pinned_version: str | None,
    parent_obj: dict[str, Any],
) -> list[UpgradeFinding]:
    """Apply the domain's logging settings, run the checks for the selected
    mode and return their findings.

    An error in the domain's ``[logging]`` settings, an error while
    initializing the domain, or one that a single check does not catch and
    report as ``CHECK_FAILED``, exits ``2`` on stderr before anything is
    printed to stdout.
    """
    try:
        # The stderr bootstrap put a root handler in place, so Domain.init
        # skips its own logging setup; apply [logging] (redact, level,
        # log_dir) here. The CLI's logging flags still take precedence.
        apply_domain_logging(derived_domain, parent_obj)
        if opportunities:
            # No init here. The opportunity detectors only read the domain's
            # source off disk through SourceProvider, so initializing adapters
            # would make the mode fail or hang whenever the databases and
            # brokers aren't up.
            return run_opportunity_checks(derived_domain, pinned_version or __version__)
        # Full init so live-schema checks (e.g. the outbox table diff) can
        # introspect the configured databases. Element/config checks do not
        # require it, but the schema check does.
        with derived_domain.domain_context():
            derived_domain.init(traverse=True)
            return run_upgrade_checks(derived_domain)
    except (Exception, SystemExit) as exc:
        # CLI boundary: user domain code can raise anything, including a
        # typer.Exit or typer.Abort (both RuntimeError), whose own code would
        # read as clean or as warnings. This also catches a bug in Protean's
        # own check framing, so keep the traceback on stderr at debug level.
        logger.debug("upgrade-check failed", exc_info=True)
        emit_usage_error(as_json=False, message=f"Error: {_describe(exc)}")


def _describe(exc: BaseException) -> str:
    """Name the exception type, so an empty message still says what failed."""
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


def _print_rich(domain_name: str, findings: list[UpgradeFinding]) -> None:
    warnings = sum(1 for f in findings if f.level == "warning")
    infos = sum(1 for f in findings if f.level == "info")

    if not findings:
        print(
            f"\n  Domain: [bold]{escape(domain_name)}[/bold]  [bold green]READY[/bold green]"
        )
        print("  No upgrade actions detected.\n")
        return

    print(
        f"\n  Domain: [bold]{escape(domain_name)}[/bold]  [bold yellow]REVIEW[/bold yellow]"
    )
    parts = []
    if warnings:
        parts.append(f"[yellow]{warnings} warning(s)[/yellow]")
    if infos:
        parts.append(f"[cyan]{infos} info(s)[/cyan]")
    print(f"  {', '.join(parts)}\n")

    for f in findings:
        marker = "[yellow]![/yellow]" if f.level == "warning" else "[cyan]i[/cyan]"
        loc = f" [dim]({escape(f.element)})[/dim]" if f.element else ""
        print(f"  {marker} [bold]{escape(f.title)}[/bold]{loc}")
        print(f"    [dim]{escape(f.code)}[/dim]  {escape(f.detail)}")
        print(f"    [green]Remediation:[/green] {escape(f.remediation)}")
        if f.sql:
            print("    [green]Generated SQL:[/green]")
            for line in f.sql.splitlines():
                print(f"      [dim]{escape(line)}[/dim]")
        print()
