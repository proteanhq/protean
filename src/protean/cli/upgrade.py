"""CLI command for ``protean upgrade-check`` — 0.16 upgrade-readiness diagnostics.

Inspects a loaded domain (and, where reachable, its live database schema) and
reports changes that may need operator attention when upgrading to 0.16, with
concrete remediation. Schema changes are *generated* as SQL to review and run;
nothing is applied automatically.

Usage::

    protean upgrade-check --domain=my_app
    protean upgrade-check --domain=my_app --format=json

Exit codes:
    0 — clean or advisory (info) only
    2 — warnings found (review recommended before upgrading)
"""

import json

import typer
from rich import print
from typing_extensions import Annotated

from protean.cli._helpers import handle_cli_exceptions
from protean.exceptions import NoDomainException
from protean.upgrade import UpgradeFinding, run_upgrade_checks
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

logger = get_logger(__name__)

_LEVEL_STYLE = {"warning": "[yellow]warning[/yellow]", "info": "[cyan]info[/cyan]"}


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
) -> None:
    """Report changes that need attention when upgrading a domain to 0.16."""
    if format not in ("rich", "json"):
        print(f"[red]Invalid --format: {format!r}. Use 'rich' or 'json'.[/red]")
        raise typer.Exit(code=1)

    try:
        derived_domain = derive_domain(domain)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(f"[red]{msg}[/red]")
        logger.error(msg)
        raise typer.Exit(code=1)

    if derived_domain is None:  # pragma: no cover - derive_domain raises on failure
        print("[red]Error loading Protean domain: no domain found.[/red]")
        raise typer.Exit(code=1)

    # Full init so live-schema checks (e.g. the outbox table diff) can introspect
    # the configured databases. Element/config checks do not require it, but the
    # schema check does.
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
        print("  No upgrade actions detected for 0.16.\n")
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
