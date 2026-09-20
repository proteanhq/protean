"""Typed query dispatch resolves the declared result type.

Runs the ``typed_query_dispatch`` fixture through both static checkers:

- **mypy** in strict mode, with the Protean plugin, via ``mypy.api``.
- **pyright** in its default (standard) mode, via ``subprocess`` + ``--outputjson``.

For each checker it asserts that a ``BaseQuery[OrderSummary]`` query dispatches
to ``OrderSummary``, a ``BaseQuery[Any]`` query dispatches to ``Any``, and
neither checker reports an error. pyright is a dev dependency and is not wired
into CI; the test skips (with a clear message) only when the executable is
genuinely absent.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from mypy import api as mypy_api

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES_DIR / "typed_query_dispatch.py"
_MYPY_CONFIG = Path(__file__).parent / "typed_dispatch_mypy_config.ini"

_MYPY_FLAGS = [
    "--config-file",
    str(_MYPY_CONFIG),
    "--no-incremental",
    "--show-error-codes",
    "--no-error-summary",
    "--hide-error-context",
]


def _run_mypy() -> tuple[list[str], list[str]]:
    """Run mypy strict on the fixture; return (revealed_types, errors)."""
    result = mypy_api.run([*_MYPY_FLAGS, str(FIXTURE)])
    stdout = result[0].strip()
    lines = stdout.splitlines() if stdout else []

    revealed: list[str] = []
    errors: list[str] = []
    for line in lines:
        match = re.search(r'Revealed type is "([^"]+)"', line)
        if match:
            # mypy renders a local class module-qualified; keep just the tail.
            revealed.append(match.group(1).rsplit(".", 1)[-1])
        elif ": error:" in line:
            errors.append(line)
    return revealed, errors


def _run_pyright() -> tuple[list[str], list[str]]:
    """Run pyright standard on the fixture; return (revealed_types, errors)."""
    pyright = shutil.which("pyright")
    if pyright is None:
        pytest.skip("pyright executable not found on PATH")

    proc = subprocess.run(
        [pyright, "--outputjson", str(FIXTURE)],
        capture_output=True,
        text=True,
    )
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover — defensive
        raise AssertionError(
            f"pyright did not emit JSON:\nstdout={proc.stdout}\nstderr={proc.stderr}"
        ) from exc

    revealed: list[str] = []
    errors: list[str] = []
    for diag in report["generalDiagnostics"]:
        message = diag["message"]
        match = re.search(r'Type of ".*" is "([^"]+)"', message)
        if match:
            revealed.append(match.group(1))
        elif diag["severity"] == "error":
            errors.append(message)
    return revealed, errors


class TestTypedDispatchMypy:
    def test_typed_query_resolves_result_type(self) -> None:
        revealed, errors = _run_mypy()
        assert not errors, f"mypy reported errors: {errors}"
        # Fixture reveals the typed dispatch first, the untyped one second.
        assert revealed == ["OrderSummary", "Any"], revealed


class TestTypedDispatchPyright:
    def test_typed_query_resolves_result_type(self) -> None:
        revealed, errors = _run_pyright()
        assert not errors, f"pyright reported errors: {errors}"
        assert revealed == ["OrderSummary", "Any"], revealed
