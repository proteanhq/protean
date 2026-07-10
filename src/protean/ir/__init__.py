"""Protean Intermediate Representation (IR) schema and utilities.

The IR captures the topology of a Protean domain model -- what elements exist,
their shape, and how they connect -- in a portable JSON format.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "EXAMPLES_DIR",
    "SCHEMA_PATH",
    "SCHEMA_VERSION",
    "CompatConfig",
    "CompatibilityChange",
    "CompatibilityReport",
    "GitError",
    "IRBuilder",
    "StalenessResult",
    "StalenessStatus",
    "check_staleness",
    "classify_changes",
    "diff_ir",
    "load_config",
    "load_ir_from_commit",
    "load_schema",
]

SCHEMA_VERSION = "0.1.0"

_IR_DIR = Path(__file__).parent
SCHEMA_PATH = _IR_DIR / "schema" / f"v{SCHEMA_VERSION}" / "schema.json"
EXAMPLES_DIR = _IR_DIR / "examples"


def load_schema() -> dict[str, Any]:
    """Load and return the IR JSON Schema as a Python dict."""
    # json.loads is untyped (returns Any); annotate the local to hold the
    # declared return type.
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return schema


# Deferred imports to avoid circular dependencies
def __getattr__(name: str) -> Any:
    if name == "IRBuilder":
        from protean.ir.builder import IRBuilder  # noqa: PLC0415

        return IRBuilder
    if name == "diff_ir":
        from protean.ir.diff import diff_ir  # noqa: PLC0415

        return diff_ir
    if name == "classify_changes":
        from protean.ir.diff import classify_changes  # noqa: PLC0415

        return classify_changes
    if name == "CompatibilityChange":
        from protean.ir.diff import CompatibilityChange  # noqa: PLC0415

        return CompatibilityChange
    if name == "CompatibilityReport":
        from protean.ir.diff import CompatibilityReport  # noqa: PLC0415

        return CompatibilityReport
    if name == "StalenessResult":
        from protean.ir.staleness import StalenessResult  # noqa: PLC0415

        return StalenessResult
    if name == "StalenessStatus":
        from protean.ir.staleness import StalenessStatus  # noqa: PLC0415

        return StalenessStatus
    if name == "check_staleness":
        from protean.ir.staleness import check_staleness  # noqa: PLC0415

        return check_staleness
    if name == "GitError":
        from protean.ir.git import GitError  # noqa: PLC0415

        return GitError
    if name == "load_ir_from_commit":
        from protean.ir.git import load_ir_from_commit  # noqa: PLC0415

        return load_ir_from_commit
    if name == "CompatConfig":
        from protean.ir.config import CompatConfig  # noqa: PLC0415

        return CompatConfig
    if name == "load_config":
        from protean.ir.config import load_config  # noqa: PLC0415

        return load_config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
