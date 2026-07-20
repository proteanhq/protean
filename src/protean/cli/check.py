"""CLI command for ``protean check`` — domain health validation.

Usage::

    # Rich output (default)
    protean check --domain=my_app

    # JSON output (CI-friendly)
    protean check --domain=my_app --format=json

    # SARIF 2.1.0 (GitHub Code Scanning / IDE problems panel)
    protean check --domain=my_app --format=sarif

    # GitHub Actions annotations (inline PR ::error/::warning/::notice)
    protean check --domain=my_app --format=github-annotations

    # Filter by severity level
    protean check --domain=my_app --level=warning

    # Quiet mode (counts only, for CI scripts)
    protean check --domain=my_app --quiet

Exit codes are gated by the ``[lint].level`` config key (default ``"warn"``),
which sets the severity floor that fails CI. ``--level`` only affects display.

    1 — errors found (always, regardless of ``[lint].level``)
    2 — a gating finding at-or-above the floor (no errors)
    0 — nothing at-or-above the floor

``[lint].level`` maps to the floor as:
    "error" — only errors gate (warnings and info exit 0)
    "warn"  — errors and warnings gate; info exits 0 (default, historical behavior)
    "info"  — errors, warnings, and info all gate
"""

import importlib.util
import json
import os
from typing import Annotated, Any

import typer
from rich import print
from rich.console import Console

import protean
from protean.cli._helpers import handle_cli_exceptions
from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

logger = get_logger(__name__)

_CONSOLE = Console()

# Ordered from most severe to least — used for --level threshold filtering
_LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}

# Valid values for the ``[lint].level`` config key (the exit-code severity floor)
_LINT_LEVELS = frozenset({"error", "warn", "info"})

# Maps a check ``level`` to the SARIF 2.1.0 ``result.level`` vocabulary. SARIF has
# no "warning"→"info" split; an info finding becomes ``note``. ``.get(level, "note")``
# is used at call sites so an unexpected level degrades rather than raising.
_SARIF_LEVEL = {"error": "error", "warning": "warning", "info": "note"}

# Maps a check ``level`` to the GitHub Actions workflow-command verb. ``info``
# becomes ``notice``. ``.get(level, "notice")`` is used at call sites.
_GHA_LEVEL = {"error": "error", "warning": "warning", "info": "notice"}

# Pinned SARIF 2.1.0 schema URI (top-level ``$schema``).
_SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/"
    "Schemata/sarif-schema-2.1.0.json"
)


@handle_cli_exceptions("check")
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
            help="Output format: 'rich' (default), 'json', 'sarif', or 'github-annotations'",
        ),
    ] = "rich",
    level: Annotated[
        str,
        typer.Option(
            "--level",
            "-l",
            help="Minimum severity to show: 'error', 'warning', or 'info' (default)",
        ),
    ] = "info",
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            "-q",
            help="Quiet mode: show only counts and exit code",
        ),
    ] = False,
) -> None:
    """Validate a Protean domain and report errors, warnings, and diagnostics."""
    if level not in _LEVEL_ORDER:
        print(
            f"[red]Invalid --level: {level!r}. Use 'error', 'warning', or 'info'.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        derived_domain = derive_domain(domain)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(f"[red]{msg}[/red]")
        logger.error(msg)
        raise typer.Exit(code=1) from exc

    assert derived_domain is not None

    # ``[lint].level`` is the config-driven exit-code floor (default "warn",
    # which reproduces the historical exit codes). Validate up front, mirroring
    # the ``--level`` validation, so a typo fails fast with a clear message.
    # Imported locally to keep ``protean --help`` from eagerly pulling in the
    # heavy IR builder subsystem.
    from protean.ir.builder import (  # noqa: PLC0415
        validate_lint_suppressions,
        validate_lint_table,
    )

    lint_config = derived_domain.config.get("lint", {})
    lint_table_error = validate_lint_table(lint_config)
    if lint_table_error:
        # Escape the literal ``[lint]`` so Rich does not parse it as markup.
        escaped = lint_table_error.replace("[lint]", r"\[lint]")
        print(f"[red]Invalid config: {escaped}[/red]")
        raise typer.Exit(code=1)

    lint_level = lint_config.get("level", "warn")
    if lint_level not in _LINT_LEVELS:
        # Escape the literal ``[lint]`` so Rich does not parse it as markup.
        print(
            rf"[red]Invalid \[lint].level: {lint_level!r}. "
            f"Use 'error', 'warn', or 'info'.[/red]"
        )
        raise typer.Exit(code=1)

    # ``[lint].suppressions`` is consumed by the IR builder; validate it here
    # too so a config typo produces a clean CLI error instead of the builder's
    # ``ConfigurationError`` traceback.
    suppressions_error = validate_lint_suppressions(lint_config.get("suppressions", {}))
    if suppressions_error:
        # Escape the literal ``[lint]`` so Rich does not parse it as markup.
        escaped = suppressions_error.replace("[lint]", r"\[lint]")
        print(f"[red]Invalid config: {escaped}[/red]")
        raise typer.Exit(code=1)

    result = derived_domain.check()

    # Preserve unfiltered counts for exit code — --level only affects display
    unfiltered_counts = dict(result["counts"])
    # Preserve the unfiltered diagnostics too: the SARIF/annotation formats are
    # consumed by machines (Code Scanning upload, CI annotations) where a
    # display-level filter must not silently drop findings. --level only shapes
    # the human-facing rich/json/quiet views below.
    unfiltered_diagnostics = list(result["diagnostics"])

    # Apply --level filter to displayed diagnostics
    threshold = _LEVEL_ORDER[level]
    result["diagnostics"] = [
        d
        for d in result["diagnostics"]
        if _LEVEL_ORDER.get(d.get("level"), 2) <= threshold
    ]
    # Recompute displayed counts after filtering
    result["counts"]["warnings"] = sum(
        1 for d in result["diagnostics"] if d.get("level") == "warning"
    )
    result["counts"]["infos"] = sum(
        1 for d in result["diagnostics"] if d.get("level") == "info"
    )
    # Recompute status from filtered counts for consistent display
    if result["counts"]["errors"] > 0:
        result["status"] = "fail"
    elif result["counts"]["warnings"] > 0:
        result["status"] = "warn"
    elif result["counts"]["infos"] > 0:
        result["status"] = "info"
    else:
        result["status"] = "pass"

    if quiet:
        _print_quiet(result)
    elif format == "json":
        typer.echo(json.dumps(result, indent=2, sort_keys=True))
    elif format == "sarif":
        # Machine formats ignore --level (see unfiltered_diagnostics above).
        machine_result = {**result, "diagnostics": unfiltered_diagnostics}
        typer.echo(
            json.dumps(
                _format_sarif(machine_result, derived_domain),
                indent=2,
                sort_keys=True,
            )
        )
    elif format == "github-annotations":
        machine_result = {**result, "diagnostics": unfiltered_diagnostics}
        typer.echo(_format_github_annotations(machine_result, derived_domain))
    else:
        _print_rich(result)

    # Exit codes use UNFILTERED counts — ``--level`` only affects display, not
    # the CI result. ``[lint].level`` sets the severity floor that gates:
    #   "error" → exit 1 on errors only
    #   "warn"  → exit 1 on errors, exit 2 on warnings (default; info never gates)
    #   "info"  → exit 1 on errors, exit 2 on any warning or info
    if unfiltered_counts["errors"] > 0:
        raise typer.Exit(code=1)
    if lint_level == "error":
        return
    if unfiltered_counts["warnings"] > 0:
        raise typer.Exit(code=2)
    if lint_level == "info" and unfiltered_counts["infos"] > 0:
        raise typer.Exit(code=2)


def _print_quiet(result: dict[str, Any]) -> None:
    """Print counts-only output for CI scripts."""
    counts = result["counts"]
    status = result["status"]
    domain_name = result["domain"]
    print(
        f"{domain_name}: {status} (errors={counts['errors']}, warnings={counts['warnings']}, infos={counts['infos']})"
    )


def _print_rich(result: dict[str, Any]) -> None:
    """Print a rich-formatted check report to the terminal."""
    domain_name = result["domain"]
    status = result["status"]
    counts = result["counts"]

    # Status line
    status_style = {
        "pass": "[bold green]PASS[/bold green]",
        "info": "[bold cyan]INFO[/bold cyan]",
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
    if counts["infos"]:
        parts.append(f"[cyan]{counts['infos']} info(s)[/cyan]")
    if parts:
        print(f"  {', '.join(parts)}")

    # Errors
    if result["errors"]:
        print(f"\n  [bold red]Errors ({counts['errors']}):[/bold red]")
        for err in result["errors"]:
            print(f"    [red]✗[/red] {err['message']}")

    # Diagnostics — split by level for display
    warnings = [d for d in result["diagnostics"] if d.get("level") == "warning"]
    infos = [d for d in result["diagnostics"] if d.get("level") == "info"]

    if warnings:
        print(f"\n  [bold yellow]Warnings ({len(warnings)}):[/bold yellow]")
        for diag in warnings:
            code = diag.get("code", "")
            prefix = f"[dim]{code}:[/dim] " if code else ""
            print(f"    [yellow]![/yellow] {prefix}{diag['message']}")

    if infos:
        print(f"\n  [bold cyan]Info ({len(infos)}):[/bold cyan]")
        for diag in infos:
            code = diag.get("code", "")
            prefix = f"[dim]{code}:[/dim] " if code else ""
            print(f"    [cyan]·[/cyan] {prefix}{diag['message']}")

    if status == "pass":
        print("\n  [green]All checks passed.[/green]")
    elif status == "info":
        print("\n  [cyan]All checks passed with informational findings.[/cyan]")

    print()


def _element_module_map(domain: Any) -> dict[str, str]:
    """Build an FQN → defining-module map from the domain registry.

    Rule diagnostics carry ``element`` as a fully-qualified name (``fqn(cls)``);
    the registry keys elements by that same FQN. This mirrors how the IR builder
    walks the registry, skipping ``internal`` records. Used to resolve a
    diagnostic's element to a source file for SARIF/annotation locations.
    """
    from protean.utils import fqn  # noqa: PLC0415

    module_map: dict[str, str] = {}
    for records in domain._domain_registry._elements.values():
        for record in records.values():
            if getattr(record, "internal", False):
                continue
            module_map[fqn(record.cls)] = record.cls.__module__
    return module_map


def _workspace_relative_uri(origin: str) -> str:
    """Return a workspace-root-relative POSIX path for a resolved module origin.

    GitHub Code Scanning resolves SARIF ``artifactLocation.uri`` — and GitHub
    Actions resolves an annotation's ``file=`` — against the workspace root
    (``GITHUB_WORKSPACE``). An absolute filesystem path matches no file in the
    checked-out PR, so the finding is dropped. Emit a path relative to
    ``GITHUB_WORKSPACE`` when it is set (so a workflow step that ``cd``s into a
    subdirectory before running ``protean check`` still maps to the repo root),
    falling back to the current working directory otherwise. Uses ``/``
    separators per the SARIF spec, and returns the absolute path only when a
    relative path is impossible (e.g. a different drive on Windows).
    """
    base = os.environ.get("GITHUB_WORKSPACE") or None
    try:
        rel = os.path.relpath(origin, start=base)
    except ValueError:
        return origin
    return rel.replace(os.sep, "/")


def _resolve_sarif_location(
    element_fqn: str, module_map: dict[str, str]
) -> dict[str, Any] | None:
    """Resolve an element FQN to a SARIF ``location`` dict, or ``None``.

    Returns ``None`` (a location-less, run-level result — valid SARIF) whenever
    the FQN is not a registered public element (validator errors and
    domain-scoped diagnostics), or its module cannot be resolved to a file. Never
    raises: any failure to resolve degrades to ``None``. The resolved path is
    workspace-relative so it maps to the PR diff on GitHub.
    """
    module = module_map.get(element_fqn)
    if not module:
        return None
    try:
        spec = importlib.util.find_spec(module)
        origin = spec.origin if spec else None
    # Broad by design, matching ``SourceProvider``: ``find_spec`` may import a
    # not-yet-loaded parent package and re-execute its ``__init__``, which can
    # raise anything. A report should lose a location, not fail to render.
    except Exception:
        return None
    if not origin:
        return None
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": _workspace_relative_uri(origin)}
        }
    }


def _format_sarif(result: dict[str, Any], domain: Any) -> dict[str, Any]:
    """Render a check result as a SARIF 2.1.0 document.

    ``errors`` and ``diagnostics`` are mutually exclusive per run and carry
    different shapes, so each list is handled separately: validator ``errors``
    become location-less ``error`` results with no rule metadata; rule
    ``diagnostics`` carry the #774 metadata and attempt FQN-based location
    resolution. ``reportingDescriptor`` objects are deduplicated by code across
    both lists (first occurrence wins).
    """
    module_map = _element_module_map(domain)
    rules: dict[str, dict[str, Any]] = {}
    sarif_results: list[dict[str, Any]] = []

    def _descriptor(
        code: str,
        message: str,
        rule: dict[str, Any] | None,
        suggestion: str | None,
    ) -> None:
        if code in rules:
            return
        fix = (rule or {}).get("fix", "")
        help_text = fix
        if suggestion and suggestion != fix:
            help_text = f"{fix}\n{suggestion}".strip()
        rules[code] = {
            "id": code,
            "shortDescription": {"text": message or code},
            "fullDescription": {"text": (rule or {}).get("rationale", "")},
            "help": {"text": help_text},
            "helpUri": (
                "https://docs.proteanhq.com/reference/fitness-functions#"
                f"{code.lower().replace('_', '-')}"
            ),
        }

    # Validator errors: no FQN, no rule metadata, always error, no location.
    for err in result.get("errors", []):
        code = err["code"]
        _descriptor(code, err.get("message", code), None, None)
        sarif_results.append(
            {
                "ruleId": code,
                "level": "error",
                "message": {"text": err["message"]},
                "locations": [],
            }
        )

    # Rule diagnostics: #774 schema, FQN-resolvable location.
    for diag in result.get("diagnostics", []):
        code = diag["code"]
        _descriptor(
            code, diag.get("message", code), diag.get("rule"), diag.get("suggestion")
        )
        loc = _resolve_sarif_location(diag.get("element", ""), module_map)
        sarif_results.append(
            {
                "ruleId": code,
                "level": _SARIF_LEVEL.get(diag.get("level"), "note"),
                "message": {"text": diag["message"]},
                "locations": [loc] if loc else [],
            }
        )

    return {
        "version": "2.1.0",
        "$schema": _SARIF_SCHEMA,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "protean",
                        "version": protean.__version__,
                        "informationUri": "https://docs.proteanhq.com/reference/cli/check",
                        "rules": list(rules.values()),
                    }
                },
                "results": sarif_results,
            }
        ],
    }


def _escape_annotation(text: str) -> str:
    """Escape a GitHub Actions annotation message body.

    ``%`` is replaced first so the ``%`` introduced by the ``\\r``/``\\n``
    replacements is not itself re-escaped (double-escaping).
    """
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    """Escape a GitHub Actions annotation *property* value (e.g. ``file=``).

    Properties are delimited by ``,`` and the ``::`` message boundary, so a
    property value carries two more escapes than a message body — ``:`` and
    ``,`` — matching GitHub's own ``@actions/core`` toolkit. Without this a path
    containing a comma (``src/orders,v2/model.py``) or a Windows drive colon
    (``C:\\proj\\model.py``) mis-parses and corrupts the annotation.
    """
    return _escape_annotation(value).replace(":", "%3A").replace(",", "%2C")


def _format_github_annotations(result: dict[str, Any], domain: Any) -> str:
    """Render a check result as GitHub Actions workflow-command annotations.

    One ``::error``/``::warning``/``::notice`` command per finding. Validator
    ``errors`` emit ``::error`` with no ``file=`` (no resolvable FQN); rule
    ``diagnostics`` include ``file=<path>`` when the element resolves to a file.
    """
    module_map = _element_module_map(domain)
    lines: list[str] = []

    for err in result.get("errors", []):
        msg = _escape_annotation(f"RULE [{err['code']}] {err['message']}")
        lines.append(f"::error::{msg}")

    for diag in result.get("diagnostics", []):
        gha = _GHA_LEVEL.get(diag.get("level"), "notice")
        loc = _resolve_sarif_location(diag.get("element", ""), module_map)
        file_param = ""
        if loc:
            path = loc["physicalLocation"]["artifactLocation"]["uri"]
            file_param = f" file={_escape_property(path)}"
        msg = _escape_annotation(f"RULE [{diag['code']}] {diag['message']}")
        lines.append(f"::{gha}{file_param}::{msg}")

    return "\n".join(lines)
