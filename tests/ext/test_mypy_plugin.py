"""Tests for the Protean mypy plugin.

Runs mypy programmatically on fixture files and verifies that field
factory return types are correctly resolved by the plugin.

All fixtures are checked in a single mypy invocation (cached via
``@lru_cache``) so the expensive cold-start cost is paid only once.
"""

import re
from functools import lru_cache
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

# All fixture files to check in one mypy run
_FIXTURE_FILES = [
    "simple_fields.py",
    "optional_fields.py",
    "default_fields.py",
    "container_fields.py",
    "identifier_fields.py",
    "class_fields.py",
]


@lru_cache(maxsize=1)
def _run_mypy_all() -> dict[str, tuple[list[str], list[str]]]:
    """Run mypy once on all fixture files and return results keyed by filename.

    Returns a dict mapping fixture filename to (notes, errors).
    """
    filepaths = [str(FIXTURES_DIR / f) for f in _FIXTURE_FILES]
    result = mypy_api.run([*_MYPY_FLAGS, *filepaths])
    stdout = result[0].strip()
    lines = stdout.splitlines() if stdout else []

    # Bucket lines by fixture filename
    results: dict[str, tuple[list[str], list[str]]] = {
        f: ([], []) for f in _FIXTURE_FILES
    }
    for line in lines:
        for fixture in _FIXTURE_FILES:
            if fixture in line:
                notes, errors = results[fixture]
                if ": note:" in line:
                    notes.append(line)
                elif ": error:" in line:
                    errors.append(line)
                break

    return results


def _get_mypy_results(fixture: str) -> tuple[list[str], list[str]]:
    """Get mypy results for a specific fixture file."""
    return _run_mypy_all()[fixture]


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
        notes, errors = _get_mypy_results("simple_fields.py")
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
        notes, errors = _get_mypy_results("optional_fields.py")
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
        notes, errors = _get_mypy_results("default_fields.py")
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
        notes, errors = _get_mypy_results("container_fields.py")
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
        notes, errors = _get_mypy_results("identifier_fields.py")
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
        notes, errors = _get_mypy_results("class_fields.py")
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
