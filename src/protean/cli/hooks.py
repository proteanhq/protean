"""Pre-commit hook entry points for downstream projects.

These thin wrappers around existing CLI commands are designed to be invoked
by the `pre-commit` framework.  Each function is registered as a console
script in ``pyproject.toml`` and referenced from ``.pre-commit-hooks.yaml``.

Usage (downstream ``.pre-commit-config.yaml``)::

    - repo: https://github.com/proteanhq/protean
      hooks:
        - id: protean-check-staleness
          args: [--domain=myapp.domain]
        - id: protean-check-compat
          args: [--domain=myapp.domain]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _build_staleness_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="protean-check-staleness",
        description="Block commit if .protean/ir.json is stale.",
    )
    parser.add_argument(
        "--domain",
        "-d",
        required=True,
        help="Path to the domain module (e.g. 'my_app.domain')",
    )
    parser.add_argument(
        "--dir",
        default=".protean",
        help="Path to the .protean/ directory (default: .protean)",
    )
    return parser


def check_staleness_hook() -> None:
    """Entry point for ``protean-check-staleness`` pre-commit hook.

    Runs ``protean ir check`` and exits with a non-zero code when
    the materialized IR is stale or missing.

    Exit codes:
      0 — IR is fresh
      1 — IR is stale or missing
    """
    from protean.exceptions import NoDomainException
    from protean.ir.staleness import StalenessStatus, check_staleness

    parser = _build_staleness_parser()
    args = parser.parse_args()

    try:
        result = check_staleness(args.domain, Path(args.dir))
    except NoDomainException as exc:
        print(f"Error: {exc.args[0]}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    if result.status == StalenessStatus.FRESH:
        raise SystemExit(0)

    # Stale or no IR — block the commit
    if result.status == StalenessStatus.STALE:
        print(
            "IR is stale — domain has changed since last materialization.",
            file=sys.stderr,
        )
        if result.stored_checksum:
            print(f"  stored:  {result.stored_checksum[:16]}…", file=sys.stderr)
        if result.domain_checksum:
            print(f"  current: {result.domain_checksum[:16]}…", file=sys.stderr)
    else:
        print(
            f"No materialized IR found in '{args.dir}/ir.json'.",
            file=sys.stderr,
        )

    print(
        "\nRun `protean ir show --domain <module> > .protean/ir.json` to update.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _build_compat_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="protean-check-compat",
        description="Block commit if breaking IR changes are detected.",
    )
    parser.add_argument(
        "--domain",
        "-d",
        required=True,
        help="Path to the domain module (e.g. 'my_app.domain')",
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


def check_compat_hook() -> None:
    """Entry point for ``protean-check-compat`` pre-commit hook.

    Runs ``protean ir diff --base HEAD`` and exits with a non-zero code
    when breaking changes are detected.

    Exit codes:
      0 — no breaking changes (safe or no changes)
      1 — breaking changes found
    """
    from pathlib import PurePosixPath

    from protean.ir.diff import classify_changes, diff_ir
    from protean.ir.git import GitError, load_ir_from_commit

    parser = _build_compat_parser()
    args = parser.parse_args()

    # Load baseline IR from the git commit
    ir_path = PurePosixPath(args.dir, "ir.json").as_posix()
    try:
        baseline_ir = load_ir_from_commit(args.base, ir_path)
    except GitError as exc:
        print(f"Error loading baseline IR: {exc}", file=sys.stderr)
        raise SystemExit(1)

    # Load live domain IR
    current_ir = _load_live_ir(args.domain)

    # Compute diff and classify
    result = diff_ir(baseline_ir, current_ir)
    report = classify_changes(result, baseline_ir, current_ir)

    summary = result.get("summary", {})
    if not summary.get("has_changes", False):
        raise SystemExit(0)

    if report.is_breaking:
        print("Breaking IR changes detected:", file=sys.stderr)
        for change in report.breaking_changes:
            print(f"  ! {change.message}", file=sys.stderr)
        raise SystemExit(1)

    # Non-breaking changes only — allow the commit
    raise SystemExit(0)
