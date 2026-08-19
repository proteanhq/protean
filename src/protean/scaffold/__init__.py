"""Protean scaffold — the change/add machinery.

Homes the shape a command like ``add`` or an upgrade uses to describe a proposed
change: a :class:`ChangePlan` of ordered operations (create a file, edit a file,
patch config), serializable to JSON, previewable without touching the
filesystem. A plan is inert; a separate applier (a later epic) executes it.

The schema is versioned as a structural contract. ``SCHEMA_VERSION``,
``SCHEMA_PATH``, and :func:`load_schema` expose the JSON Schema the serialized
plan validates against, the same way ``protean.ir`` does.

This package also holds the tooling that reasons about a generated project's
shape on disk, starting with the derived project manifest
(:mod:`protean.scaffold.manifest`). It is side-effect free on import.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from protean.scaffold.change_plan import (
    PLAN_VERSION,
    ChangePlan,
    ConfigOperation,
    CreateFileOperation,
    EditFileOperation,
    Operation,
)
from protean.scaffold.preview import render_preview

__all__ = [
    "PLAN_VERSION",
    "SCHEMA_PATH",
    "SCHEMA_VERSION",
    "ChangePlan",
    "ConfigOperation",
    "CreateFileOperation",
    "EditFileOperation",
    "Operation",
    "load_schema",
    "render_preview",
]

# The JSON Schema version tracks the serialized plan shape and stays in
# lock-step with ``PLAN_VERSION``.
SCHEMA_VERSION = PLAN_VERSION

_SCAFFOLD_DIR = Path(__file__).parent
SCHEMA_PATH = _SCAFFOLD_DIR / "schema" / f"v{SCHEMA_VERSION}" / "schema.json"


def load_schema() -> dict[str, Any]:
    """Load and return the ChangePlan JSON Schema as a Python dict."""
    # json.loads is untyped (returns Any); annotate the local to hold the
    # declared return type.
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return schema
