"""Protean Intermediate Representation (IR) schema and utilities.

The IR captures the topology of a Protean domain model -- what elements exist,
their shape, and how they connect -- in a portable JSON format.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["SCHEMA_VERSION", "SCHEMA_PATH", "EXAMPLES_DIR", "load_schema"]

SCHEMA_VERSION = "0.1.0"

_IR_DIR = Path(__file__).parent
SCHEMA_PATH = _IR_DIR / "schema" / f"v{SCHEMA_VERSION}" / "schema.json"
EXAMPLES_DIR = _IR_DIR / "examples"


def load_schema() -> dict[str, Any]:
    """Load and return the IR JSON Schema as a Python dict."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
