"""Typed query dispatch resolves the declared result type.

Runs the ``typed_query_dispatch`` fixture through both static checkers:

- **mypy** in strict mode, via ``mypy.api``, twice: once with the Protean
  plugin and once without it. Typed dispatch is plain typing, so the
  plugin-free leg is the one that holds ADR-0043 to its claim that the feature
  does not depend on the plugin; the plugin leg proves the generic query base
  composes with the plugin.
- **pyright** in its default (standard) mode, via ``subprocess`` + ``--outputjson``.

For each checker it asserts that a ``BaseQuery[OrderSummary]`` query dispatches
to ``OrderSummary``, that a ``BaseQuery[Any]`` query and a decorator-only query
both dispatch to ``Any``, and that no checker reports an error. pyright is a
dev dependency and is not wired into CI; the test skips (with a clear message)
only when the executable is genuinely absent.
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
_MYPY_PLUGIN_CONFIG = Path(__file__).parent / "typed_dispatch_mypy_config.ini"
_MYPY_NO_PLUGIN_CONFIG = (
    Path(__file__).parent / "typed_dispatch_mypy_no_plugin_config.ini"
)

# Fixture order: typed query, bare query, decorator-only query.
_EXPECTED_REVEALS = ["OrderSummary", "Any", "Any"]


def _run_mypy(config: Path) -> tuple[list[str], list[str]]:
    """Run mypy strict on the fixture; return (revealed_types, errors)."""
    result = mypy_api.run(
        [
            "--config-file",
            str(config),
            "--no-incremental",
            "--show-error-codes",
            "--no-error-summary",
            "--hide-error-context",
            str(FIXTURE),
        ]
    )
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


def _parse_pyright_report(stdout: str) -> dict | None:
    """Pull pyright's ``--outputjson`` payload out of a stdout stream.

    The stream is not always JSON from its first byte. The `pyright` PyPI
    package launches the real checker through a node shim, and on a cold cache
    that shim prints its platform probe to stdout first, as a Python repr:
    ``{'x86': False, 'risc': False, 'lts': False}``. Handing the whole stream to
    ``json.loads`` then fails on a run where pyright itself answered correctly,
    and the whole matrix has to be run again to clear it.

    So decode from the first brace that begins a real report object and ignore
    whatever surrounds it. Returns None when the stream carries no report.
    """
    decoder = json.JSONDecoder()
    for index, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and "generalDiagnostics" in candidate:
            return candidate
    return None


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
    report = _parse_pyright_report(proc.stdout)
    if report is None:
        raise AssertionError(
            f"pyright did not emit JSON:\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )

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
    @pytest.mark.parametrize(
        "config",
        [_MYPY_NO_PLUGIN_CONFIG, _MYPY_PLUGIN_CONFIG],
        ids=["no-plugin", "with-plugin"],
    )
    def test_typed_query_resolves_result_type(self, config: Path) -> None:
        revealed, errors = _run_mypy(config)
        assert not errors, f"mypy reported errors: {errors}"
        assert revealed == _EXPECTED_REVEALS, revealed


class TestTypedDispatchPyright:
    def test_typed_query_resolves_result_type(self) -> None:
        revealed, errors = _run_pyright()
        assert not errors, f"pyright reported errors: {errors}"
        assert revealed == _EXPECTED_REVEALS, revealed


class TestPyrightReportParsing:
    """The report is read out of the stream, whatever the launcher printed first."""

    def test_plain_json_stream(self) -> None:
        report = _parse_pyright_report('{"generalDiagnostics": [], "version": "1.1"}')
        assert report is not None
        assert report["version"] == "1.1"

    def test_node_probe_line_ahead_of_the_report(self) -> None:
        # What the node shim prints on a cold cache: a Python repr, not JSON.
        stdout = (
            "{'x86': False, 'risc': False, 'lts': False}\n{\"generalDiagnostics\": []}"
        )
        report = _parse_pyright_report(stdout)
        assert report == {"generalDiagnostics": []}

    def test_json_object_without_diagnostics_is_not_the_report(self) -> None:
        stdout = '{"version": "1.1"}\n{"generalDiagnostics": [{"severity": "error"}]}'
        report = _parse_pyright_report(stdout)
        assert report is not None
        assert report["generalDiagnostics"] == [{"severity": "error"}]

    def test_stream_with_no_report_returns_none(self) -> None:
        assert _parse_pyright_report("pyright: command failed\n") is None
