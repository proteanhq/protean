"""Shared IR loading utilities for CLI commands.

Extracted from ``protean.cli.ir`` so that both the ``ir`` and ``docs``
command groups can load an IR dict from a live domain or a JSON file
without duplicating logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, cast

import typer
from rich import print

from protean.cli.result import emit_usage_error
from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain
from protean.utils.logging import get_logger

if TYPE_CHECKING:
    from protean.domain import Domain

logger = get_logger(__name__)


def _abort_load(
    message: str, *, as_json: bool, exc: BaseException | None = None
) -> NoReturn:
    """Report an IR-load failure and exit.

    Under ``as_json`` the failure is the shared ``status="error"`` envelope on
    stdout (exit ``2``), so a command emitting the result envelope keeps stdout
    to one JSON object; otherwise a red line goes to stdout and ``typer.Abort``
    exits ``1``, the historical behaviour. The exit class is format-dependent by
    design: the machine path follows the envelope convention (``2`` for a
    usage/environment error) while the human path stays backward-compatible.
    """
    logger.error(message)
    if as_json:
        emit_usage_error(as_json=True, message=message)
    print(f"[red]Error:[/red] {message}")
    raise typer.Abort() from exc


def load_domain(domain_path: str, *, as_json: bool = False) -> Domain:
    """Import and initialise a live domain, returning the Domain object.

    Imports the domain module at *domain_path* and initialises it. Callers can
    introspect the returned domain's registered element classes (e.g. their
    index declarations). On failure the function reports a diagnostic and
    raises ``typer.Abort()`` (or exits with the error envelope under
    ``as_json``).
    """
    try:
        derived_domain = derive_domain(domain_path)
    except NoDomainException as exc:
        _abort_load(
            f"Error loading Protean domain: {exc.args[0]}", as_json=as_json, exc=exc
        )

    assert derived_domain is not None

    try:
        derived_domain.init()
    except Exception as exc:
        _abort_load(
            f"Error initialising Protean domain: {exc}", as_json=as_json, exc=exc
        )

    return derived_domain


def load_domain_ir(domain_path: str, *, as_json: bool = False) -> dict[str, Any]:
    """Build and return the IR from a live domain.

    Loads and initialises the domain (via :func:`load_domain`), then returns
    the full IR dict. On failure it reports a diagnostic and raises
    ``typer.Abort()`` (or exits with the error envelope under ``as_json``).
    """
    derived_domain = load_domain(domain_path, as_json=as_json)

    try:
        return derived_domain.to_ir()
    except Exception as exc:
        _abort_load(
            f"Error generating IR from Protean domain: {exc}", as_json=as_json, exc=exc
        )


def load_ir_file(path: str, *, as_json: bool = False) -> dict[str, Any]:
    """Load an IR dict from a JSON file.

    Returns the parsed dict. On failure (missing file or invalid JSON) it
    reports a diagnostic and raises ``typer.Abort()`` (or exits with the error
    envelope under ``as_json``).
    """
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        _abort_load(f"file not found or not a regular file: {path}", as_json=as_json)
    try:
        file_contents = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        _abort_load(f"could not read {path}: {exc}", as_json=as_json, exc=exc)
    try:
        data = json.loads(file_contents)
    except json.JSONDecodeError as exc:
        _abort_load(f"invalid JSON in {path}: {exc}", as_json=as_json, exc=exc)
    # An IR is a JSON object. A file that parses to a list or scalar would blow
    # up later in the catalog builder, so reject it here where the message can
    # still name the file.
    if not isinstance(data, dict):
        _abort_load(f"IR file is not a JSON object: {path}", as_json=as_json)
    # json.loads is typed to return Any; the check above pins it to a dict.
    return cast("dict[str, Any]", data)
