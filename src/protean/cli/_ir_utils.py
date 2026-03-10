"""Shared IR loading utilities for CLI commands.

Extracted from ``protean.cli.ir`` so that both the ``ir`` and ``docs``
command groups can load an IR dict from a live domain or a JSON file
without duplicating logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich import print

from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

logger = get_logger(__name__)


def load_domain_ir(domain_path: str) -> dict[str, Any]:
    """Build and return the IR from a live domain.

    Imports the domain module at *domain_path*, initialises it, and
    returns the full IR dict.  On failure the function prints a
    diagnostic and raises ``typer.Abort()``.
    """
    try:
        derived_domain = derive_domain(domain_path)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        print(f"[red]Error:[/red] {msg}")
        logger.error(msg)
        raise typer.Abort()

    assert derived_domain is not None

    try:
        derived_domain.init()
        return derived_domain.to_ir()
    except Exception as exc:
        msg = f"Error generating IR from Protean domain: {exc}"
        print(f"[red]Error:[/red] {msg}")
        logger.error(msg)
        raise typer.Abort()


def load_ir_file(path: str) -> dict[str, Any]:
    """Load an IR dict from a JSON file.

    Returns the parsed dict.  On failure (missing file or invalid JSON)
    the function prints a diagnostic and raises ``typer.Abort()``.
    """
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        print(f"[red]Error:[/red] file not found or not a regular file: {path}")
        raise typer.Abort()
    try:
        file_contents = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[red]Error:[/red] could not read {path}: {exc}")
        raise typer.Abort()
    try:
        return json.loads(file_contents)
    except json.JSONDecodeError as exc:
        print(f"[red]Error:[/red] invalid JSON in {path}: {exc}")
        raise typer.Abort()
