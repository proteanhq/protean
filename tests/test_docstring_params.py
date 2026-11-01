"""Every docstring in ``src/protean`` documents only parameters its signature has.

Griffe parses each Google-style docstring the way mkdocstrings does for the API
pages, and warns when an ``Args:`` entry names a parameter the signature lacks.
The docs build fails on that warning through ``hooks/docstring_params.py``, but
the docs build runs only on deploy. This test runs the same check on every PR,
over all of ``src/protean`` instead of only the objects the API pages render.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

griffe = pytest.importorskip("griffe")

pytestmark = pytest.mark.no_test_domain

SRC = Path(__file__).resolve().parents[1] / "src"
MARKER = "does not appear in the function signature"


def _parse_all(obj: griffe.Object) -> None:
    if obj.docstring is not None:
        obj.docstring.parse("google")
    for member in obj.members.values():
        # An alias is an import; its target is parsed where it is defined.
        if not member.is_alias:
            _parse_all(member)


def test_docstrings_document_only_parameters_in_the_signature(
    caplog: pytest.LogCaptureFixture,
) -> None:
    package = griffe.load("protean", search_paths=[SRC], resolve_aliases=False)

    with caplog.at_level(logging.WARNING):
        _parse_all(package)

    stale = [r.getMessage() for r in caplog.records if MARKER in r.getMessage()]
    assert not stale, "Docstrings document parameters their signatures lack:\n" + (
        "\n".join(stale)
    )
