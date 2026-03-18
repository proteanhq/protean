"""Protean Intermediate Representation (IR) schema and utilities.

The IR captures the topology of a Protean domain model -- what elements exist,
their shape, and how they connect -- in a portable JSON format.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "SCHEMA_VERSION",
    "SCHEMA_PATH",
    "EXAMPLES_DIR",
    "IRBuilder",
    "CompatibilityChange",
    "CompatibilityReport",
    "StalenessResult",
    "StalenessStatus",
    "classify_changes",
    "check_staleness",
    "diff_ir",
    "load_schema",
]

SCHEMA_VERSION = "0.1.0"

_IR_DIR = Path(__file__).parent
SCHEMA_PATH = _IR_DIR / "schema" / f"v{SCHEMA_VERSION}" / "schema.json"
EXAMPLES_DIR = _IR_DIR / "examples"


def load_schema() -> dict[str, Any]:
    """Load and return the IR JSON Schema as a Python dict."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# Deferred imports to avoid circular dependencies
def __getattr__(name: str) -> Any:
    if name == "IRBuilder":
        from protean.ir.builder import IRBuilder

        return IRBuilder
    if name == "diff_ir":
        from protean.ir.diff import diff_ir

        return diff_ir
    if name == "classify_changes":
        from protean.ir.diff import classify_changes

        return classify_changes
    if name == "CompatibilityChange":
        from protean.ir.diff import CompatibilityChange

        return CompatibilityChange
    if name == "CompatibilityReport":
        from protean.ir.diff import CompatibilityReport

        return CompatibilityReport
    if name == "StalenessResult":
        from protean.ir.staleness import StalenessResult

        return StalenessResult
    if name == "StalenessStatus":
        from protean.ir.staleness import StalenessStatus

        return StalenessStatus
    if name == "check_staleness":
        from protean.ir.staleness import check_staleness

        return check_staleness
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
