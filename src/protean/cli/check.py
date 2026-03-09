"""CLI command for ``protean check`` — domain health validation.

Usage::

    # Rich output (default)
    protean check --domain=my_app

    # JSON output (CI-friendly)
    protean check --domain=my_app --format=json

Exit codes:
    0 — clean (no errors, warnings, or diagnostics)
    1 — errors found
    2 — warnings or diagnostics only (no errors)
"""

import json

import typer
from rich import print
from rich.console import Console
from typing_extensions import Annotated

from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

logger = get_logger(__name__)

_CONSOLE = Console()


def check(
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
    """Validate a Protean domain and report errors, warnings, and diagnostics."""
    try:
        derived_domain = derive_domain(domain)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(f"[red]{msg}[/red]")
        logger.error(msg)
        raise typer.Exit(code=1)

    assert derived_domain is not None

    result = derived_domain.check()

    if format == "json":
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_rich(result)

    # Exit codes: 0=clean, 1=errors, 2=warnings/diagnostics only
    if result["counts"]["errors"] > 0:
        raise typer.Exit(code=1)
    elif result["counts"]["warnings"] > 0 or result["counts"]["diagnostics"] > 0:
        raise typer.Exit(code=2)


def _print_rich(result: dict) -> None:
    """Print a rich-formatted check report to the terminal."""
    domain_name = result["domain"]
    status = result["status"]
    counts = result["counts"]

    # Status line
    status_style = {
        "pass": "[bold green]PASS[/bold green]",
        "warn": "[bold yellow]WARN[/bold yellow]",
        "fail": "[bold red]FAIL[/bold red]",
    }
    print(f"\n  Domain: [bold]{domain_name}[/bold]  {status_style.get(status, status)}")

    # Counts summary
    parts = []
    if counts["errors"]:
        parts.append(f"[red]{counts['errors']} error(s)[/red]")
    if counts["warnings"]:
        parts.append(f"[yellow]{counts['warnings']} warning(s)[/yellow]")
    if counts["diagnostics"]:
        parts.append(f"[cyan]{counts['diagnostics']} diagnostic(s)[/cyan]")
    if parts:
        print(f"  {', '.join(parts)}")

    # Errors
    if result["errors"]:
        print(f"\n  [bold red]Errors ({counts['errors']}):[/bold red]")
        for err in result["errors"]:
            print(f"    [red]✗[/red] {err['message']}")

    # Warnings
    if result["warnings"]:
        print(f"\n  [bold yellow]Warnings ({counts['warnings']}):[/bold yellow]")
        for warn in result["warnings"]:
            code = warn.get("code", "")
            prefix = f"[dim]{code}:[/dim] " if code else ""
            print(f"    [yellow]![/yellow] {prefix}{warn['message']}")

    # Diagnostics (from IR)
    if result["diagnostics"]:
        print(f"\n  [bold cyan]Diagnostics ({counts['diagnostics']}):[/bold cyan]")
        for diag in result["diagnostics"]:
            code = diag.get("code", "")
            prefix = f"[dim]{code}:[/dim] " if code else ""
            print(f"    [cyan]·[/cyan] {prefix}{diag['message']}")

    if status == "pass":
        print("\n  [green]All checks passed.[/green]")

    print()
