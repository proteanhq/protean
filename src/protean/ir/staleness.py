"""IR staleness detection — compare live domain checksum against materialized IR.

Usage::

    from pathlib import Path
    from protean.ir.staleness import check_staleness, StalenessStatus

    result = check_staleness("my_app.domain", Path(".protean"))
    if result.status == StalenessStatus.STALE:
        print("Domain has changed; re-run `protean ir show --canonical` to update.")
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

from protean.exceptions import NoDomainException
from protean.ir import SCHEMA_VERSION
from protean.ir.builder import IRBuilder
from protean.ir.config import load_config
from protean.utils.domain_discovery import derive_domain

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

    VERSION_MISMATCH = "version_mismatch"
    """The materialized IR was produced against a different schema version.

    A baseline whose ``ir_version`` differs from the current
    :data:`~protean.ir.SCHEMA_VERSION` cannot be compared by checksum — the
    checksum spaces are not comparable across schema versions. Regenerate the
    baseline against the current schema.
    """


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

    stored_version: str | None = None
    """``ir_version`` from the materialized IR, populated only on a
    VERSION_MISMATCH outcome; ``None`` on every other outcome (FRESH/STALE/NO_IR)
    even when the stored file carries an ``ir_version``."""

    current_version: str | None = None
    """Current schema version the live domain builds against, or ``None`` if
    the version was not compared (e.g. FRESH/STALE/NO_IR outcomes)."""


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
        - ``status=VERSION_MISMATCH`` — the stored ``ir_version`` differs from
          the current :data:`~protean.ir.SCHEMA_VERSION`; the baseline was
          materialized against a different schema version and must be
          regenerated.
    """
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
    # 1a. Schema version discipline                                        #
    # ------------------------------------------------------------------ #
    # A baseline carrying an ``ir_version`` that differs from the current
    # schema version was materialized against an older (or newer) schema; its
    # checksum is not comparable to a live checksum computed under the current
    # schema. Report VERSION_MISMATCH and short-circuit — building the live IR
    # would only yield a misleading STALE. A baseline with no ``ir_version``
    # (legacy/bare) falls through to the checksum path unchanged. A non-string
    # ``ir_version`` (corrupt baseline) is coerced to ``str`` so the result
    # field honours its ``str | None`` contract for JSON consumers.
    raw_version = stored_ir.get("ir_version")
    stored_version: str | None = str(raw_version) if raw_version is not None else None
    if stored_version is not None and stored_version != SCHEMA_VERSION:
        return StalenessResult(
            status=StalenessStatus.VERSION_MISMATCH,
            domain_checksum=None,
            stored_checksum=stored_checksum,
            ir_file=ir_path.resolve(),
            stored_version=stored_version,
            current_version=SCHEMA_VERSION,
        )

    # ------------------------------------------------------------------ #
    # 2. Build the live IR and compute its checksum                        #
    # ------------------------------------------------------------------ #
    domain = derive_domain(domain_module)
    if domain is None:
        raise NoDomainException(
            f"Could not derive a Protean domain from {domain_module!r}"
        )
    domain.init()
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
