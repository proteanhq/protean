"""Plugin fixtures checked under ``mypy --strict``.

Each fixture states its expectations inline. A line ending in ``# R: <type>``
must produce that revealed type, and a line ending in ``# E: <code>`` must
produce an error with that code. Any other error, or any reveal without a
marker, fails the fixture. ``strict_sample.py`` is a small domain in the
canonical typed-annotation style that must type-check with no errors at all.

All fixtures go through one mypy run, cached for the module.
"""

import re
from functools import lru_cache
from pathlib import Path

import pytest
from mypy import api as mypy_api

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_STRICT_CONFIG = Path(__file__).parent / "mypy_plugin_strict_config.ini"

_STRICT_FIXTURES = [
    "strict_typed_annotation.py",
    "strict_annotation_only.py",
    "strict_mismatch.py",
    "strict_dict_annotation.py",
    "strict_base_class_params.py",
    "strict_element_types.py",
    "strict_upcaster.py",
    "strict_handle_any.py",
    "strict_queryset_self.py",
    "strict_sample.py",
]

_OUTPUT_LINE = re.compile(
    r"^(?P<file>[^:]+\.py):(?P<line>\d+): (?P<kind>error|note): (?P<message>.*)$"
)
_REVEAL = re.compile(r'Revealed type is "(?P<type>.*)"$')
_ERROR_CODE = re.compile(r"\[(?P<code>[a-z-]+)\]$")
_EXPECT_REVEAL = re.compile(r"# R: (?P<type>.+)$")
_EXPECT_ERROR = re.compile(r"# E: (?P<code>[a-z-]+)$")
# mypy qualifies class names with their module; the expectations use the bare
# class name so they read the way the fixture is written.
_MODULE_PREFIX = re.compile(r"\b(?:[a-z_][a-z0-9_]*\.)+(?=[A-Za-z_])")


def _normalize(revealed: str) -> str:
    return _MODULE_PREFIX.sub("", revealed)


Findings = dict[int, list[str]]


@lru_cache(maxsize=1)
def _run_mypy() -> dict[str, tuple[Findings, Findings]]:
    """Run mypy strict over every fixture; return (reveals, errors) per fixture."""
    result = mypy_api.run(
        [
            "--config-file",
            str(_STRICT_CONFIG),
            "--no-incremental",
            "--show-error-codes",
            "--no-error-summary",
            "--hide-error-context",
            *(str(FIXTURES_DIR / name) for name in _STRICT_FIXTURES),
        ]
    )
    findings: dict[str, tuple[Findings, Findings]] = {
        name: ({}, {}) for name in _STRICT_FIXTURES
    }
    for raw in result[0].splitlines():
        match = _OUTPUT_LINE.match(raw)
        if match is None:
            continue
        name = Path(match["file"]).name
        assert name in findings, f"mypy reported on an unexpected file: {raw}"
        reveals, errors = findings[name]
        line = int(match["line"])
        message = match["message"]
        if match["kind"] == "note":
            reveal = _REVEAL.search(message)
            if reveal is not None:
                reveals.setdefault(line, []).append(_normalize(reveal["type"]))
            continue
        code = _ERROR_CODE.search(message)
        errors.setdefault(line, []).append(code["code"] if code else message)
    return findings


def _expectations(name: str) -> tuple[Findings, Findings]:
    reveals: Findings = {}
    errors: Findings = {}
    lines = (FIXTURES_DIR / name).read_text(encoding="utf-8").splitlines()
    for number, text in enumerate(lines, start=1):
        if (reveal := _EXPECT_REVEAL.search(text)) is not None:
            reveals[number] = [reveal["type"].strip()]
        if (error := _EXPECT_ERROR.search(text)) is not None:
            errors[number] = [error["code"]]
    return reveals, errors


@pytest.mark.parametrize(
    "fixture", _STRICT_FIXTURES, ids=[name[:-3] for name in _STRICT_FIXTURES]
)
def test_fixture_matches_its_expectations(fixture: str) -> None:
    expected_reveals, expected_errors = _expectations(fixture)
    actual_reveals, actual_errors = _run_mypy()[fixture]

    assert actual_reveals == expected_reveals
    assert actual_errors == expected_errors


def test_sample_domain_declares_no_expected_errors() -> None:
    """The sample must stay clean, so it may not mark any line as an error."""
    _, expected_errors = _expectations("strict_sample.py")
    assert expected_errors == {}


def test_expectation_markers_are_found() -> None:
    """Guard against a marker typo silently turning a fixture into a no-op."""
    reveals, errors = _expectations("strict_typed_annotation.py")
    assert len(reveals) > 0
    assert len(errors) > 0
