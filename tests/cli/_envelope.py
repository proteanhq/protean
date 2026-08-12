"""Shared assertion for CLI result-envelope conformance tests.

The per-command test modules (events, subscriptions, projection) use this to
check that a command's ``--json`` output is exactly one envelope object on
stdout that validates against the pinned schema. The leading underscore keeps
pytest from collecting this module as a test file.
"""

from __future__ import annotations

import json
from typing import Any

from jsonschema import validate

from protean.cli.result import load_envelope_schema

_SCHEMA = load_envelope_schema()


def assert_envelope(stdout: str) -> dict[str, Any]:
    """Decode ``stdout`` as exactly one envelope object and validate it.

    Guards the "exactly one JSON object on stdout and nothing else" contract: a
    leaked log line before the object, or a second object after it, fails here.
    Returns the decoded envelope for the caller's further assertions.
    """
    decoder = json.JSONDecoder()
    obj, end = decoder.raw_decode(stdout.lstrip())
    assert stdout.lstrip()[end:].strip() == "", (
        f"stdout carried more than one JSON object:\n{stdout!r}"
    )
    assert isinstance(obj, dict), f"stdout was not a JSON object: {stdout!r}"
    validate(obj, _SCHEMA)
    return obj
