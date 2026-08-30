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
    2 — warnings found (review recommended before upgrading)
"""

import json
import re
from typing import Annotated

import typer
from rich import print

from protean import __version__
from protean.cli._helpers import handle_cli_exceptions
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
    """Report changes that need attention when upgrading to a newer Protean."""
    if format not in ("rich", "json"):
        print(f"[red]Invalid --format: {format!r}. Use 'rich' or 'json'.[/red]")
        raise typer.Exit(code=1)

    if pinned_version is not None and not _PINNED_VERSION_RE.match(pinned_version):
        print(
            f"[red]Invalid --pinned-version: {pinned_version!r}. "
            "Use a version like '0.16' or '0.16.3'.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        derived_domain = derive_domain(domain)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(f"[red]{msg}[/red]")
        logger.error(msg)
        raise typer.Exit(code=1) from exc

    if derived_domain is None:  # pragma: no cover - derive_domain raises on failure
        print("[red]Error loading Protean domain: no domain found.[/red]")
        raise typer.Exit(code=1)

    if opportunities:
        # No init here. The opportunity detectors only read the domain's source
        # off disk through SourceProvider, so initializing adapters would make
        # the mode fail or hang whenever the databases and brokers aren't up.
        pinned = pinned_version or __version__
        findings = run_opportunity_checks(derived_domain, pinned)
    else:
        # Full init so live-schema checks (e.g. the outbox table diff) can
        # introspect the configured databases. Element/config checks do not
        # require it, but the schema check does.
        with derived_domain.domain_context():
            derived_domain.init(traverse=True)
            findings = run_upgrade_checks(derived_domain)

    if format == "json":
        typer.echo(json.dumps([f.as_dict() for f in findings], indent=2))
    else:
        _print_rich(derived_domain.name, findings)

    if any(f.level == "warning" for f in findings):
        raise typer.Exit(code=2)


def _print_rich(domain_name: str, findings: list[UpgradeFinding]) -> None:
    warnings = sum(1 for f in findings if f.level == "warning")
    infos = sum(1 for f in findings if f.level == "info")

    if not findings:
        print(f"\n  Domain: [bold]{domain_name}[/bold]  [bold green]READY[/bold green]")
        print("  No upgrade actions detected.\n")
        return

    print(f"\n  Domain: [bold]{domain_name}[/bold]  [bold yellow]REVIEW[/bold yellow]")
    parts = []
    if warnings:
        parts.append(f"[yellow]{warnings} warning(s)[/yellow]")
    if infos:
        parts.append(f"[cyan]{infos} info(s)[/cyan]")
    print(f"  {', '.join(parts)}\n")

    for f in findings:
        marker = "[yellow]![/yellow]" if f.level == "warning" else "[cyan]i[/cyan]"
        loc = f" [dim]({f.element})[/dim]" if f.element else ""
        print(f"  {marker} [bold]{f.title}[/bold]{loc}")
        print(f"    [dim]{f.code}[/dim]  {f.detail}")
        print(f"    [green]Remediation:[/green] {f.remediation}")
        if f.sql:
            print("    [green]Generated SQL:[/green]")
            for line in f.sql.splitlines():
                print(f"      [dim]{line}[/dim]")
        print()
