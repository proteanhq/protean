"""The shared CLI result envelope, its versioned schema, and the exit-code convention.

Every Protean command that emits machine-readable output under ``--json`` (or
``--format json``) wraps its result in one stable envelope::

    {
      "version": "0.1.0",
      "status": "pass" | "fail" | "error",
      "data": { ... command-specific detail ... },
      "diagnostics": [ ... typed Diagnostic records ... ]
    }

so an agent can consume any command's output uniformly. ``status`` is the
coarse verdict that maps to the exit-code class: ``"pass"`` (exit ``0``),
``"fail"`` (a failure the command is designed to detect), ``"error"`` (a usage
or environment error it could not run past). The fine-grained detail — a
command's own status, counts, or stage tree — lives under ``data``;
``diagnostics`` carries the typed ``Diagnostic`` list from the registry
(:mod:`protean.ir.diagnostics`).

The envelope is a guarded contract, not just a shape: it ships a pinned,
versioned JSON Schema at :data:`SCHEMA_PATH`, mirroring the IR precedent at
``src/protean/ir/schema/v0.1.0/schema.json``. A conformance test asserts every
command's ``--json`` output validates against it.

The exit-code convention every command follows (with command-specific classes
documented per command):

    0 — success.
    1 — the command ran and reports a failure it is designed to detect (the
        severity/stage detail is in the envelope, not the code).
    2 — a usage or environment error it could not run past (a bad option, no or
        unloadable domain, malformed config, IO). This is Click's own default
        for a bad command line, so untouched commands inherit it for free.
    >=3 — command-specific failure classes, documented per command (``verify``
        pins ``3`` init, ``4`` check, ``5`` tests).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

ENVELOPE_VERSION = "0.1.0"

_CLI_DIR = Path(__file__).parent
SCHEMA_PATH = _CLI_DIR / "schema" / f"v{ENVELOPE_VERSION}" / "envelope.schema.json"

# The CLI-wide exit-code convention (see the module docstring). The
# command-specific classes (``verify``'s 3/4/5) are named in that command.
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_USAGE = 2

# The envelope's coarse verdict — the exit-code class, not the fine-grained
# severity (which lives under ``data``).
EnvelopeStatus = Literal["pass", "fail", "error"]


def load_envelope_schema() -> dict[str, Any]:
    """Load and return the CLI result-envelope JSON Schema as a Python dict."""
    # json.loads is untyped (returns Any); annotate the local to hold the
    # declared return type.
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return schema


def build_envelope(
    *,
    status: EnvelopeStatus,
    data: dict[str, Any],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one result envelope from a command's status, detail, and diagnostics.

    ``status`` is the coarse verdict (``"pass"``/``"fail"``/``"error"``);
    ``data`` is the command's own detail; ``diagnostics`` is the typed
    ``Diagnostic`` list (empty when the command has none). The returned dict
    carries exactly the four contract keys and validates against
    :data:`SCHEMA_PATH`. ``diagnostics`` is copied so a later mutation of the
    caller's list does not reach into the envelope.
    """
    return {
        "version": ENVELOPE_VERSION,
        "status": status,
        "data": data,
        "diagnostics": list(diagnostics),
    }
