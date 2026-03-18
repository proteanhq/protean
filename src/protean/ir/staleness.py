"""IR staleness detection — compare live domain checksum against materialized IR.

Usage::

    from pathlib import Path
    from protean.ir.staleness import check_staleness, StalenessStatus

    result = check_staleness("my_app.domain", Path(".protean"))
    if result.status == StalenessStatus.STALE:
        print("Domain has changed; re-run `protean ir show` to update.")
    elif result.status == StalenessStatus.NO_IR:
        print("No materialized IR found in .protean/")
    else:
        print("IR is fresh.")
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from protean.ir.config import CompatConfig

__all__ = [
    "StalenessStatus",
    "StalenessResult",
    "check_staleness",
    "load_stored_ir",
]

_IR_FILENAME = "ir.json"


class StalenessStatus(str, Enum):
    """Outcome of a staleness check."""

    FRESH = "fresh"
    """The materialized IR matches the live domain."""

    STALE = "stale"
    """The materialized IR is out of date; the domain has changed."""

    NO_IR = "no_ir"
    """No materialized IR file was found in the given directory."""


@dataclass(frozen=True)
class StalenessResult:
    """Result returned by :func:`check_staleness`."""

    status: StalenessStatus
    """Overall outcome of the staleness check."""

    domain_checksum: str | None
    """Checksum computed from the live domain, or ``None`` if unavailable."""

    stored_checksum: str | None
    """Checksum read from the materialized IR file, or ``None`` if no IR."""

    ir_file: Path | None
    """Absolute path to the IR file that was checked, or ``None`` if absent."""


def load_stored_ir(protean_dir: Path | str) -> tuple[dict[str, Any], Path] | None:
    """Load the stored IR from *protean_dir*/ir.json.

    Returns ``(ir_dict, path)`` if found and valid, or ``None`` if the file
    does not exist.  Raises :exc:`ValueError` if the file exists but is not
    valid JSON.
    """
    ir_path = Path(protean_dir) / _IR_FILENAME
    if not ir_path.exists():
        return None
    try:
        content = ir_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read {ir_path}: {exc}") from exc
    try:
        return json.loads(content), ir_path
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {ir_path}: {exc}") from exc


def check_staleness(
    domain_module: str,
    protean_dir: Path | str = ".protean",
    *,
    config: CompatConfig | None = None,
) -> StalenessResult:
    """Compare the live domain's IR checksum against the materialized IR.

    Parameters
    ----------
    domain_module:
        Dotted module path (or file path) of the domain to import and
        initialise, e.g. ``"my_app.domain"`` or ``"my_app/domain.py"``.
    protean_dir:
        Path to the directory that holds the materialized ``ir.json``.
        Defaults to ``.protean`` relative to the current working directory.
    config:
        Optional :class:`~protean.ir.config.CompatConfig`.  When ``None``,
        loaded automatically from *protean_dir*/config.toml.

    Returns
    -------
    StalenessResult
        - ``status=FRESH`` — checksums match, or staleness checking is
          disabled via config.
        - ``status=STALE`` — checksums differ.
        - ``status=NO_IR`` — no ``ir.json`` found in *protean_dir*.
    """
    from protean.ir.builder import IRBuilder
    from protean.ir.config import load_config
    from protean.utils.domain_discovery import derive_domain

    if config is None:
        config = load_config(protean_dir)

    # If staleness checking is disabled, return FRESH immediately
    if not config.staleness_enabled:
        return StalenessResult(
            status=StalenessStatus.FRESH,
            domain_checksum=None,
            stored_checksum=None,
            ir_file=None,
        )

    # ------------------------------------------------------------------ #
    # 1. Load and check the stored IR                                      #
    # ------------------------------------------------------------------ #
    stored = load_stored_ir(protean_dir)
    if stored is None:
        return StalenessResult(
            status=StalenessStatus.NO_IR,
            domain_checksum=None,
            stored_checksum=None,
            ir_file=None,
        )

    stored_ir, ir_path = stored
    stored_checksum: str | None = stored_ir.get("checksum")

    # ------------------------------------------------------------------ #
    # 2. Build the live IR and compute its checksum                        #
    # ------------------------------------------------------------------ #
    domain = derive_domain(domain_module)
    domain.init(traverse=False)
    live_ir = IRBuilder(domain).build()
    domain_checksum: str = live_ir["checksum"]

    # ------------------------------------------------------------------ #
    # 3. Compare                                                           #
    # ------------------------------------------------------------------ #
    if domain_checksum == stored_checksum:
        status = StalenessStatus.FRESH
    else:
        status = StalenessStatus.STALE

    return StalenessResult(
        status=status,
        domain_checksum=domain_checksum,
        stored_checksum=stored_checksum,
        ir_file=ir_path.resolve(),
    )
