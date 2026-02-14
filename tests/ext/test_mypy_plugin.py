"""Tests for the Protean mypy plugin.

Runs mypy programmatically on fixture files and verifies that field
factory return types are correctly resolved by the plugin.
"""

from __future__ import annotations

import re
from pathlib import Path

from mypy import api as mypy_api

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Common mypy flags used for all tests
_MYPY_FLAGS = [
    "--no-incremental",
    "--show-error-codes",
    "--no-error-summary",
    "--hide-error-context",
]


def _run_mypy(fixture: str) -> tuple[list[str], list[str]]:
    """Run mypy on a fixture file and return (notes, errors).

    ``notes`` contains ``reveal_type`` output lines.
    ``errors`` contains actual error lines.
    """
    filepath = str(FIXTURES_DIR / fixture)
    result = mypy_api.run([*_MYPY_FLAGS, filepath])
    stdout = result[0].strip()
    lines = stdout.splitlines() if stdout else []

    notes = [line for line in lines if ": note:" in line]
    errors = [line for line in lines if ": error:" in line]
    return notes, errors


def _extract_revealed_types(notes: list[str]) -> list[str]:
    """Extract the revealed type strings from mypy note output.

    Each note looks like:
        /path/to/file.py:6: note: Revealed type is "builtins.str"
    Returns: ["builtins.str", ...]
    """
    types = []
    for note in notes:
        match = re.search(r'Revealed type is "([^"]+)"', note)
        if match:
            types.append(match.group(1))
    return types


class TestSimpleFields:
    """Field factories for simple types resolve to the correct Python types."""

    def test_required_fields_are_not_optional(self) -> None:
        notes, errors = _run_mypy("simple_fields.py")
        types = _extract_revealed_types(notes)
        assert types == [
            "builtins.str",  # String(required=True)
            "builtins.str",  # Text(required=True)
            "builtins.int",  # Integer(required=True)
            "builtins.float",  # Float(required=True)
            "builtins.bool",  # Boolean(required=True)
            "datetime.date",  # Date(required=True)
            "datetime.datetime",  # DateTime(required=True)
        ]
        # No errors expected (no class instantiation in this fixture)
        assert not errors

    def test_optional_fields(self) -> None:
        notes, errors = _run_mypy("optional_fields.py")
        types = _extract_revealed_types(notes)
        assert types == [
            "builtins.str | None",  # String()
            "builtins.int | None",  # Integer()
            "builtins.float | None",  # Float()
            "builtins.bool | None",  # Boolean()
            "datetime.date | None",  # Date()
            "datetime.datetime | None",  # DateTime()
        ]
        assert not errors

    def test_fields_with_defaults_are_not_optional(self) -> None:
        notes, errors = _run_mypy("default_fields.py")
        types = _extract_revealed_types(notes)
        assert types == [
            "builtins.str",  # String(default="hello")
            "builtins.int",  # Integer(default=0)
            "builtins.float",  # Float(default=0.0)
            "builtins.bool",  # Boolean(default=True)
        ]
        assert not errors


class TestContainerFields:
    """List and Dict fields resolve to list/dict and are never Optional."""

    def test_container_fields_have_correct_types(self) -> None:
        notes, errors = _run_mypy("container_fields.py")
        types = _extract_revealed_types(notes)
        assert types == [
            "builtins.list",  # List()
            "builtins.list",  # List(content_type=int)
            "builtins.dict",  # Dict()
            "builtins.list",  # List(required=True)
            "builtins.dict",  # Dict(required=True)
        ]
        assert not errors


class TestIdentifierFields:
    """Identifier and Auto fields resolve correctly."""

    def test_identifier_fields(self) -> None:
        notes, errors = _run_mypy("identifier_fields.py")
        types = _extract_revealed_types(notes)
        assert types == [
            "builtins.str",  # Identifier(identifier=True) - not Optional
            "builtins.str",  # Auto(identifier=True) - not Optional
            "builtins.str | None",  # Identifier() - Optional
        ]
        assert not errors


class TestClassFields:
    """Fields declared in domain element classes resolve correctly."""

    def test_aggregate_field_types(self) -> None:
        notes, errors = _run_mypy("class_fields.py")
        types = _extract_revealed_types(notes)
        assert types == [
            "builtins.str",  # customer_name: required
            "builtins.int | None",  # quantity: optional
            "builtins.float | None",  # price: optional
            "builtins.bool",  # is_active: has default
        ]
        # call-arg errors from Order() are expected (no __init__ synthesis)
        # but there should be no type errors
        type_errors = [e for e in errors if "[call-arg]" not in e]
        assert not type_errors
