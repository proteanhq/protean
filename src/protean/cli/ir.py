"""CLI commands for the domain IR (Intermediate Representation).

Usage::

    # Show full IR as JSON
    protean ir show --domain=my_domain

    # Show IR summary with element counts
    protean ir show --domain=my_domain --format=summary

    # Diff two IR snapshots
    protean ir diff --left=baseline.json --right=current.json

    # Diff live domain against a saved baseline
    protean ir diff --domain=my_app --right=baseline.json

    # Auto-baseline: diff live domain against .protean/ir.json
    protean ir diff --domain=my_app

    # Diff live domain against IR from a git commit
    protean ir diff --domain=my_app --base=HEAD
    protean ir diff --domain=my_app --base=main

    # Check whether the materialized IR is fresh or stale
    protean ir check --domain=my_domain
    protean ir check --domain=my_domain --dir=.protean --format=json
"""

import json
from typing import Any

import typer
from rich import print
from rich.console import Console
from rich.table import Table
from typing_extensions import Annotated

from protean.cli._ir_utils import load_domain_ir, load_ir_file

app = typer.Typer(no_args_is_help=True)


@app.callback()
def callback():
    """Inspect the domain's Intermediate Representation (IR)."""


@app.command()
def show(
    domain: Annotated[
        str,
        typer.Option(
            "--domain",
            "-d",
            help="Path to the domain module (e.g. 'my_app.domain')",
        ),
    ],
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: 'json' (default) or 'summary'",
        ),
    ] = "json",
) -> None:
    """Show the domain's IR."""
    ir = load_domain_ir(domain)

    if format == "summary":
        _print_summary(ir)
    else:
        typer.echo(json.dumps(ir, indent=2, sort_keys=True))


@app.command()
def diff(
    left: Annotated[
        str,
        typer.Option(
            "--left",
            "-l",
            help="Path to the left (baseline) IR JSON file",
        ),
    ] = "",
    right: Annotated[
        str,
        typer.Option(
            "--right",
            "-r",
            help="Path to the right (current) IR JSON file",
        ),
    ] = "",
    domain: Annotated[
        str,
        typer.Option(
            "--domain",
            "-d",
            help=(
                "Domain module path. With --base or alone: live domain is the "
                "'current' (right) side. With --right: live domain is the "
                "'baseline' (left) side."
            ),
        ),
    ] = "",
    base: Annotated[
        str,
        typer.Option(
            "--base",
            "-b",
            help=(
                "Git commit/branch/tag to load the baseline .protean/ir.json from "
                "(e.g. HEAD, main, v0.15.0). Requires --domain."
            ),
        ),
    ] = "",
    dir: Annotated[
        str,
        typer.Option(
            "--dir",
            help="Path to the .protean/ directory (default: .protean)",
        ),
    ] = ".protean",
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: 'text' (default) or 'json'",
        ),
    ] = "text",
) -> None:
    """Compare two IR snapshots and show differences.

    Modes of operation:

    \b
    1. Explicit files:  --left baseline.json --right current.json
    2. Domain vs file:  --domain my_app --right current.json
    3. Auto-baseline:   --domain my_app  (loads .protean/ir.json as baseline)
    4. Git baseline:    --domain my_app --base HEAD

    Exit codes (CI-friendly):
      0 — no changes detected
      1 — breaking changes found
      2 — non-breaking changes only
    """
    from protean.ir.config import load_config
    from protean.ir.diff import classify_changes, diff_ir

    # ------------------------------------------------------------------ #
    # Load config                                                          #
    # ------------------------------------------------------------------ #
    config = load_config(dir)

    # If compatibility checking is disabled, skip entirely
    if config.strictness == "off":
        print("[dim]Compatibility checking is disabled (strictness=off).[/dim]")
        raise typer.Exit(code=0)

    # ------------------------------------------------------------------ #
    # Validate argument combinations                                      #
    # ------------------------------------------------------------------ #
    if base and not domain:
        print("[red]Error:[/red] --base requires --domain")
        raise typer.Abort()

    if base and (left or right):
        print("[red]Error:[/red] --base cannot be combined with --left/--right")
        raise typer.Abort()

    if left and domain:
        print("[red]Error:[/red] --left and --domain are mutually exclusive")
        raise typer.Abort()

    if left and not right:
        print("[red]Error:[/red] --right is required when using --left")
        raise typer.Abort()

    if not left and not domain:
        print("[red]Error:[/red] provide either --left or --domain")
        raise typer.Abort()

    # ------------------------------------------------------------------ #
    # Load IRs based on mode                                              #
    # ------------------------------------------------------------------ #
    if base:
        # Mode 4: git baseline — load IR from a commit
        baseline_ir = _load_ir_from_git(base, dir)
        current_ir = load_domain_ir(domain)
    elif domain and not right:
        # Mode 3: auto-baseline — load .protean/ir.json as baseline
        baseline_ir = _load_auto_baseline(dir)
        current_ir = load_domain_ir(domain)
    elif domain and right:
        # Mode 2: domain (left) vs file (right)
        baseline_ir = load_domain_ir(domain)
        current_ir = load_ir_file(right)
    else:
        # Mode 1: explicit files
        baseline_ir = load_ir_file(left)
        current_ir = load_ir_file(right)

    # ------------------------------------------------------------------ #
    # Compute diff and classify                                           #
    # ------------------------------------------------------------------ #
    result = diff_ir(baseline_ir, current_ir)
    report = classify_changes(result, baseline_ir, current_ir)

    # Filter out excluded elements from the report
    if config.exclude:
        report.breaking_changes = [
            c
            for c in report.breaking_changes
            if not config.is_excluded(c.element_fqn)
        ]
        report.safe_changes = [
            c for c in report.safe_changes if not config.is_excluded(c.element_fqn)
        ]

    if format == "json":
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_diff_text(result)

    # ------------------------------------------------------------------ #
    # CI exit codes                                                       #
    # ------------------------------------------------------------------ #
    summary = result.get("summary", {})
    if not summary.get("has_changes", False):
        raise typer.Exit(code=0)
    elif report.is_breaking:
        if config.strictness == "warn":
            print(
                "[yellow]Warning:[/yellow] Breaking changes detected "
                "(strictness=warn, not blocking)."
            )
            raise typer.Exit(code=0)
        raise typer.Exit(code=1)
    elif summary.get("has_breaking_changes", False):
        # Contract-level breaking changes from diff (not in report)
        if config.strictness == "warn":
            raise typer.Exit(code=0)
        raise typer.Exit(code=1)
    else:
        raise typer.Exit(code=2)


def _load_ir_from_git(commit: str, protean_dir: str) -> dict[str, Any]:
    """Load .protean/ir.json from a git commit, or abort on error."""
    from pathlib import PurePosixPath

    from protean.ir.git import GitError, load_ir_from_commit

    ir_path = PurePosixPath(protean_dir, "ir.json").as_posix()
    try:
        return load_ir_from_commit(commit, ir_path)
    except GitError as exc:
        print(f"[red]Error:[/red] {exc}")
        raise typer.Abort()


def _load_auto_baseline(protean_dir: str) -> dict[str, Any]:
    """Load .protean/ir.json from disk, or abort if not found."""
    from pathlib import Path

    from protean.ir.staleness import load_stored_ir

    try:
        stored = load_stored_ir(Path(protean_dir))
    except ValueError as exc:
        print(f"[red]Error:[/red] {exc}")
        raise typer.Abort()

    if stored is None:
        print(
            f"[red]Error:[/red] No materialized IR found in '{protean_dir}/ir.json'.\n"
            "  Run [bold]protean ir show --domain <module> > "
            f"{protean_dir}/ir.json[/bold] to generate one,\n"
            "  or use --left/--right to specify files explicitly."
        )
        raise typer.Abort()
    ir_dict, _ = stored
    return ir_dict


# ------------------------------------------------------------------
# Text formatting for diff output
# ------------------------------------------------------------------

_CONSOLE = Console()


def _print_diff_text(result: dict[str, Any]) -> None:
    """Print a rich-formatted text diff to the terminal."""
    summary = result.get("summary", {})

    if not summary.get("has_changes", False):
        print("[green]No changes detected.[/green]")
        return

    # Header
    print(
        f"\n[bold]IR Diff[/bold]  "
        f"left={summary.get('left_checksum', '?')[:16]}  "
        f"right={summary.get('right_checksum', '?')[:16]}"
    )

    counts = summary.get("counts", {})
    print(
        f"  [green]+{counts.get('added', 0)} added[/green]  "
        f"[red]-{counts.get('removed', 0)} removed[/red]  "
        f"[yellow]~{counts.get('changed', 0)} changed[/yellow]"
    )

    # Breaking changes (prominent)
    breaking = result.get("contracts", {}).get("breaking_changes", [])
    if breaking:
        print(f"\n[bold red]Breaking Changes ({len(breaking)}):[/bold red]")
        for bc in breaking:
            print(f"  [red]! {bc['message']}[/red]")

    # Clusters
    clusters = result.get("clusters", {})
    if clusters:
        print("\n[bold]Clusters[/bold]")
        _print_section_changes(clusters)

    # Projections
    projections = result.get("projections", {})
    if projections:
        print("\n[bold]Projections[/bold]")
        _print_section_changes(projections)

    # Flows
    flows = result.get("flows", {})
    if flows:
        print("\n[bold]Flows[/bold]")
        for sub_name in ("domain_services", "process_managers", "subscribers"):
            sub = flows.get(sub_name, {})
            if sub:
                label = sub_name.replace("_", " ").title()
                print(f"  [dim]{label}[/dim]")
                _print_section_changes(sub, indent=4)

    # Contracts (non-breaking additions)
    contracts = result.get("contracts", {})
    contract_added = contracts.get("added", [])
    contract_removed = contracts.get("removed", [])
    if contract_added or contract_removed:
        print("\n[bold]Contracts[/bold]")
        for evt in contract_added:
            print(
                f"  [green]+ published event: {evt.get('type', evt.get('fqn'))}[/green]"
            )
        for evt in contract_removed:
            print(f"  [red]- published event: {evt.get('type', evt.get('fqn'))}[/red]")

    # Diagnostics
    diagnostics = result.get("diagnostics", {})
    if diagnostics:
        print("\n[bold]Diagnostics[/bold]")
        for diag in diagnostics.get("added", []):
            print(f"  [yellow]+ {diag['code']}: {diag['message']}[/yellow]")
        for diag in diagnostics.get("resolved", []):
            print(f"  [green]- resolved: {diag['code']}: {diag['message']}[/green]")

    # Domain config
    domain_diff = result.get("domain", {})
    domain_changed = domain_diff.get("changed", {})
    if domain_changed:
        print("\n[bold]Domain Config[/bold]")
        for key, vals in sorted(domain_changed.items()):
            print(f"  [yellow]~ {key}: {vals['left']} → {vals['right']}[/yellow]")

    print()


def _print_section_changes(
    section: dict[str, Any],
    indent: int = 2,
) -> None:
    """Print added/removed/changed for a keyed section."""
    pad = " " * indent

    for fqn, info in sorted(section.get("added", {}).items()):
        name = info.get("name", fqn.rsplit(".", 1)[-1])
        etype = info.get("element_type", "")
        label = f"{name} ({etype})" if etype else name
        print(f"{pad}[green]+ {label}[/green]")

    for fqn, info in sorted(section.get("removed", {}).items()):
        name = info.get("name", fqn.rsplit(".", 1)[-1])
        etype = info.get("element_type", "")
        label = f"{name} ({etype})" if etype else name
        print(f"{pad}[red]- {label}[/red]")

    for fqn, changes in sorted(section.get("changed", {}).items()):
        name = fqn.rsplit(".", 1)[-1]
        print(f"{pad}[yellow]~ {name}[/yellow]")
        _print_element_changes(changes, indent + 4)


def _print_element_changes(
    changes: dict[str, Any],
    indent: int,
) -> None:
    """Print field-level and attribute-level changes for an element."""
    pad = " " * indent

    # Aggregate-level changes within a cluster
    if "aggregate" in changes:
        print(f"{pad}[dim]aggregate:[/dim]")
        _print_element_changes(changes["aggregate"], indent + 2)

    # Fields
    fields = changes.get("fields", {})
    if fields:
        for name, field_info in sorted(fields.get("added", {}).items()):
            kind = field_info.get("type", field_info.get("kind", ""))
            req = ", required" if field_info.get("required") else ""
            print(f"{pad}[green]+ field: {name} ({kind}{req})[/green]")

        for name, field_info in sorted(fields.get("removed", {}).items()):
            kind = field_info.get("type", field_info.get("kind", ""))
            print(f"{pad}[red]- field: {name} ({kind})[/red]")

        for name, attrs in sorted(fields.get("changed", {}).items()):
            for attr, vals in sorted(attrs.items()):
                print(
                    f"{pad}[yellow]~ field {name}.{attr}: "
                    f"{vals['left']} → {vals['right']}[/yellow]"
                )

    # Options
    options = changes.get("options", {})
    for key, vals in sorted(options.get("changed", {}).items()):
        print(f"{pad}[yellow]~ option {key}: {vals['left']} → {vals['right']}[/yellow]")

    # Handlers
    handlers = changes.get("handlers", {})
    if handlers:
        for type_key in sorted(handlers.get("added", {})):
            print(f"{pad}[green]+ handles: {type_key}[/green]")
        for type_key in sorted(handlers.get("removed", {})):
            print(f"{pad}[red]- handles: {type_key}[/red]")

    # Invariants
    invariants = changes.get("invariants", {})
    for category in ("pre", "post"):
        cat_changes = invariants.get(category, {})
        for name in cat_changes.get("added", []):
            print(f"{pad}[green]+ invariant ({category}): {name}[/green]")
        for name in cat_changes.get("removed", []):
            print(f"{pad}[red]- invariant ({category}): {name}[/red]")

    # Sub-sections (entities, commands, events, etc. within a cluster)
    for sub in (
        "entities",
        "value_objects",
        "commands",
        "events",
        "command_handlers",
        "event_handlers",
        "repositories",
        "database_models",
        "application_services",
        "projectors",
        "queries",
        "query_handlers",
    ):
        sub_changes = changes.get(sub, {})
        if sub_changes:
            label = sub.replace("_", " ")
            print(f"{pad}[dim]{label}:[/dim]")
            _print_section_changes(sub_changes, indent + 2)


@app.command()
def check(
    domain: Annotated[
        str,
        typer.Option(
            "--domain",
            "-d",
            help="Path to the domain module (e.g. 'my_app.domain')",
        ),
    ],
    dir: Annotated[
        str,
        typer.Option(
            "--dir",
            help="Path to the .protean/ directory (default: auto-detect from CWD)",
        ),
    ] = ".protean",
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: 'text' (default) or 'json'",
        ),
    ] = "text",
) -> None:
    """Check whether the materialized IR is fresh or stale.

    Exit codes:
      0 — IR is fresh (matches live domain)
      1 — IR is stale (domain has changed)
      2 — No materialized IR found in the given directory
    """
    from pathlib import Path

    from protean.exceptions import NoDomainException
    from protean.ir.config import load_config
    from protean.ir.staleness import StalenessStatus, check_staleness

    config = load_config(dir)

    try:
        result = check_staleness(domain, Path(dir), config=config)
    except NoDomainException as exc:
        print(f"[red]Error:[/red] {exc.args[0]}")
        raise typer.Exit(code=2)
    except Exception as exc:
        print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=2)

    if format == "json":
        import json as _json

        payload = {
            "status": result.status.value,
            "domain_checksum": result.domain_checksum,
            "stored_checksum": result.stored_checksum,
            "ir_file": str(result.ir_file) if result.ir_file else None,
        }
        typer.echo(_json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_check_text(result, dir)

    # Map status → exit code
    _exit_codes = {
        StalenessStatus.FRESH: 0,
        StalenessStatus.STALE: 1,
        StalenessStatus.NO_IR: 2,
    }
    raise typer.Exit(code=_exit_codes[result.status])


def _print_check_text(result: Any, protean_dir: str = ".protean") -> None:
    """Print a human-readable staleness check result."""
    from protean.ir.staleness import StalenessStatus

    if result.status == StalenessStatus.FRESH:
        print("[green]IR is fresh.[/green]")
        if result.domain_checksum:
            print(f"  checksum: {result.domain_checksum[:16]}…")
    elif result.status == StalenessStatus.STALE:
        print(
            "[yellow]IR is stale — domain has changed since last materialization.[/yellow]"
        )
        if result.stored_checksum:
            print(f"  stored:  {result.stored_checksum[:16]}…")
        if result.domain_checksum:
            print(f"  current: {result.domain_checksum[:16]}…")
        if result.ir_file:
            print(f"  file:    {result.ir_file}")
        print(
            "\n  Run [bold]protean ir show --domain <module> > .protean/ir.json[/bold]"
            " to update."
        )
    else:  # NO_IR
        location = str(result.ir_file) if result.ir_file else protean_dir
        print(f"[red]No materialized IR found in '{location}'.[/red]")
        print(
            "\n  Run [bold]protean ir show --domain <module> > .protean/ir.json[/bold]"
            " to generate one."
        )


def _print_summary(ir: dict) -> None:
    """Print a human-readable summary of the IR."""
    print(f"\n[bold]Domain:[/bold] {ir['domain']['name']}")
    print(f"[bold]IR Version:[/bold] {ir['ir_version']}")
    print(f"[bold]Checksum:[/bold] {ir['checksum']}")
    print()

    # Element counts
    table = Table(title="Element Counts")
    table.add_column("Element Type", style="cyan")
    table.add_column("Count", justify="right", style="green")

    for etype, fqn_list in sorted(ir.get("elements", {}).items()):
        table.add_row(etype, str(len(fqn_list)))

    print(table)

    # Cluster summary
    clusters = ir.get("clusters", {})
    if clusters:
        print(f"\n[bold]Clusters:[/bold] {len(clusters)}")
        for cluster_fqn, cluster in sorted(clusters.items()):
            agg_name = cluster["aggregate"]["name"]
            entity_count = len(cluster.get("entities", {}))
            vo_count = len(cluster.get("value_objects", {}))
            cmd_count = len(cluster.get("commands", {}))
            evt_count = len(cluster.get("events", {}))
            print(
                f"  {agg_name}: "
                f"{entity_count} entities, {vo_count} VOs, "
                f"{cmd_count} commands, {evt_count} events"
            )

    # Diagnostics
    diagnostics = ir.get("diagnostics", [])
    if diagnostics:
        print(f"\n[bold yellow]Diagnostics:[/bold yellow] {len(diagnostics)}")
        for diag in diagnostics:
            print(f"  [{diag['level']}] {diag['code']}: {diag['message']}")
