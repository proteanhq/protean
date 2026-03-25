"""Pre-commit hook entry points for downstream projects.

These thin wrappers around existing CLI commands are designed to be invoked
by the `pre-commit` framework.  Each function is registered as a console
script in ``pyproject.toml`` and referenced from ``.pre-commit-hooks.yaml``.

Downstream projects should use ``repo: local`` with ``language: system``
so that the hooks run inside the project's own environment where user code
is importable.  A remote ``repo:`` installs hooks in an isolated virtualenv
that cannot import user domain modules.

Usage (downstream ``.pre-commit-config.yaml``)::

    - repo: local
      hooks:
        - id: protean-check-staleness
          name: Check IR staleness
          entry: protean-check-staleness --domain=myapp.domain
          language: system
          pass_filenames: false
          always_run: true
        - id: protean-check-compat
          name: Check IR compatibility
          entry: protean-check-compat --domain=myapp.domain
          language: system
          pass_filenames: false
          always_run: true

Multi-domain support (config-driven)::

    # .protean/config.toml
    [domains]
    identity = "identity.domain"
    catalogue = "catalogue.domain"

    # .pre-commit-config.yaml — no --domain needed
    - repo: local
      hooks:
        - id: protean-check-staleness
          name: Check IR staleness
          entry: protean-check-staleness --fix
          language: system
          pass_filenames: false
          always_run: true
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_domains(
    args: argparse.Namespace,
    config: Any,
) -> list[tuple[str, Path]]:
    """Return a list of ``(domain_module, protean_dir)`` pairs to check.

    Resolution order:
    1. Explicit ``--domain`` argument → single entry.
    2. ``[domains]`` section in config.toml → one entry per domain,
       with each domain's IR stored under ``<base_dir>/<name>/``.
    3. Neither → error.
    """
    base_dir = Path(args.dir)

    if args.domain:
        return [(args.domain, base_dir)]

    if config.domains:
        return [(module, base_dir / name) for name, module in config.domains.items()]

    print(
        "Error: No --domain argument and no [domains] section in config.toml.\n"
        "Provide --domain or add a [domains] table to .protean/config.toml.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _load_live_ir(domain_path: str) -> dict:
    """Load live IR from a domain module without depending on typer."""
    from protean.exceptions import NoDomainException
    from protean.utils.domain_discovery import derive_domain

    try:
        domain = derive_domain(domain_path)
    except NoDomainException as exc:
        print(f"Error loading domain: {exc.args[0]}", file=sys.stderr)
        raise SystemExit(1)

    try:
        domain.init()
        return domain.to_ir()
    except Exception as exc:
        print(f"Error generating IR: {exc}", file=sys.stderr)
        raise SystemExit(1)


def _regenerate_ir(domain_module: str, protean_dir: Path) -> dict:
    """Build live IR, write it to *protean_dir*/ir.json, and return the dict."""
    from protean.ir.builder import IRBuilder
    from protean.utils.domain_discovery import derive_domain

    domain = derive_domain(domain_module)
    domain.init()
    live_ir = IRBuilder(domain).build()

    protean_dir.mkdir(parents=True, exist_ok=True)
    ir_path = protean_dir / "ir.json"
    ir_path.write_text(json.dumps(live_ir, indent=2) + "\n", encoding="utf-8")
    return live_ir


def _git_add(path: Path) -> None:
    """Stage *path* with ``git add`` so it's included in the commit."""
    try:
        subprocess.run(
            ["git", "add", str(path)],
            capture_output=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(
            f"Warning: could not stage {path}: {exc}",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Staleness hook
# ---------------------------------------------------------------------------


def _build_staleness_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="protean-check-staleness",
        description="Block commit if .protean/ir.json is stale.",
    )
    parser.add_argument(
        "--domain",
        "-d",
        default=None,
        help=(
            "Path to the domain module (e.g. 'my_app.domain'). "
            "Optional when [domains] is configured in config.toml."
        ),
    )
    parser.add_argument(
        "--dir",
        default=".protean",
        help="Path to the .protean/ directory (default: .protean)",
    )
    parser.add_argument(
        "--fix",
        "-f",
        action="store_true",
        default=False,
        help="Auto-regenerate stale IR and stage the updated file.",
    )
    return parser


def _check_staleness_single(
    domain_module: str,
    protean_dir: Path,
    *,
    fix: bool,
    config: Any,
) -> bool:
    """Check staleness for a single domain.  Returns ``True`` if OK."""
    from protean.exceptions import NoDomainException
    from protean.ir.staleness import StalenessStatus, check_staleness

    try:
        result = check_staleness(domain_module, protean_dir, config=config)
    except NoDomainException as exc:
        print(f"Error ({domain_module}): {exc.args[0]}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"Error ({domain_module}): {exc}", file=sys.stderr)
        return False

    if result.status == StalenessStatus.FRESH:
        return True

    # Stale or no IR
    target_path = protean_dir / "ir.json"

    if fix:
        try:
            _regenerate_ir(domain_module, protean_dir)
        except Exception as exc:
            print(
                f"Error: failed to regenerate IR for {domain_module}: {exc}",
                file=sys.stderr,
            )
            return False
        _git_add(target_path)
        print(
            f"Fixed: regenerated {target_path} for {domain_module}",
            file=sys.stderr,
        )
        return True

    # Report without fix
    if result.status == StalenessStatus.STALE:
        print(
            f"IR is stale for {domain_module} — domain has changed since "
            "last materialization.",
            file=sys.stderr,
        )
        if result.stored_checksum:
            print(f"  stored:  {result.stored_checksum[:16]}...", file=sys.stderr)
        if result.domain_checksum:
            print(f"  current: {result.domain_checksum[:16]}...", file=sys.stderr)
    else:
        print(
            f"No materialized IR found in '{target_path}'.",
            file=sys.stderr,
        )

    print(
        f"\nRun `protean ir show --domain {domain_module} > {target_path}` "
        "to update, or use --fix to auto-regenerate.",
        file=sys.stderr,
    )
    return False


def check_staleness_hook() -> None:
    """Entry point for ``protean-check-staleness`` pre-commit hook.

    Runs ``protean ir check`` and exits with a non-zero code when
    the materialized IR is stale or missing.  Respects
    ``.protean/config.toml`` --- if ``staleness.enabled = false``, the
    hook exits 0 immediately.

    Supports ``--fix`` to auto-regenerate stale IR and stage the file.

    When ``--domain`` is omitted, reads the ``[domains]`` section from
    ``config.toml`` and checks all configured domains.

    Exit codes:
      0 --- IR is fresh (or staleness checking disabled, or --fix succeeded)
      1 --- IR is stale or missing (and --fix not used or failed)
    """
    from protean.ir.config import load_config

    parser = _build_staleness_parser()
    args = parser.parse_args()

    try:
        config = load_config(args.dir)
    except ValueError as exc:
        print(f"Error: Invalid .protean/config.toml: {exc}", file=sys.stderr)
        raise SystemExit(1)

    # If staleness checking is disabled, exit immediately
    if not config.staleness_enabled:
        raise SystemExit(0)

    domains = _resolve_domains(args, config)

    all_ok = True
    for domain_module, protean_dir in domains:
        ok = _check_staleness_single(
            domain_module, protean_dir, fix=args.fix, config=config
        )
        if not ok:
            all_ok = False

    raise SystemExit(0 if all_ok else 1)


# ---------------------------------------------------------------------------
# Compat hook
# ---------------------------------------------------------------------------


def _build_compat_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="protean-check-compat",
        description="Block commit if breaking IR changes are detected.",
    )
    parser.add_argument(
        "--domain",
        "-d",
        default=None,
        help=(
            "Path to the domain module (e.g. 'my_app.domain'). "
            "Optional when [domains] is configured in config.toml."
        ),
    )
    parser.add_argument(
        "--base",
        "-b",
        default="HEAD",
        help=(
            "Git commit/branch/tag to load the baseline .protean/ir.json from "
            "(default: HEAD)"
        ),
    )
    parser.add_argument(
        "--dir",
        default=".protean",
        help="Path to the .protean/ directory (default: .protean)",
    )
    return parser


def _check_compat_single(
    domain_module: str,
    protean_dir: Path,
    *,
    base: str,
    config: Any,
) -> bool:
    """Check compat for a single domain.  Returns ``True`` if OK (no block)."""
    from pathlib import PurePosixPath

    from protean.ir.diff import classify_changes, diff_ir
    from protean.ir.git import GitError, load_ir_from_commit

    ir_path = PurePosixPath(protean_dir, "ir.json").as_posix()
    try:
        baseline_ir = load_ir_from_commit(base, ir_path)
    except GitError as exc:
        print(
            f"Error loading baseline IR for {domain_module}: {exc}",
            file=sys.stderr,
        )
        return False

    current_ir = _load_live_ir(domain_module)

    result = diff_ir(baseline_ir, current_ir)
    report = classify_changes(result, baseline_ir, current_ir)

    if config.exclude:
        report.breaking_changes = [
            c for c in report.breaking_changes if not config.is_excluded(c.element_fqn)
        ]

    summary = result.get("summary", {})
    if not summary.get("has_changes", False):
        return True

    has_breaking = report.is_breaking or summary.get("has_breaking_changes", False)

    if has_breaking:
        if report.is_breaking:
            print(f"Breaking IR changes detected for {domain_module}:", file=sys.stderr)
            for change in report.breaking_changes:
                print(f"  ! {change.message}", file=sys.stderr)

        if config.strictness == "warn":
            print(
                "\n(strictness=warn — not blocking the commit)",
                file=sys.stderr,
            )
            return True

        return False

    return True


def check_compat_hook() -> None:
    """Entry point for ``protean-check-compat`` pre-commit hook.

    Runs ``protean ir diff --base HEAD`` and exits with a non-zero code
    when breaking changes are detected.  Respects
    ``.protean/config.toml`` --- if ``compatibility.strictness = "off"``,
    the hook exits 0.  If ``strictness = "warn"``, breaking changes are
    printed but the hook still exits 0.

    When ``--domain`` is omitted, reads the ``[domains]`` section from
    ``config.toml`` and checks all configured domains.

    Exit codes:
      0 --- no breaking changes (safe or no changes), or strictness is
          "off" / "warn"
      1 --- breaking changes found (strictness = "strict")
    """
    from protean.ir.config import load_config

    parser = _build_compat_parser()
    args = parser.parse_args()

    try:
        config = load_config(args.dir)
    except ValueError as exc:
        print(f"Error: Invalid .protean/config.toml: {exc}", file=sys.stderr)
        raise SystemExit(1)

    if config.strictness == "off":
        raise SystemExit(0)

    domains = _resolve_domains(args, config)

    all_ok = True
    for domain_module, protean_dir in domains:
        ok = _check_compat_single(
            domain_module, protean_dir, base=args.base, config=config
        )
        if not ok:
            all_ok = False

    raise SystemExit(0 if all_ok else 1)
