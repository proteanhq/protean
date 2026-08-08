"""CLI command for ``protean verify`` — one command for init + check + tests.

``verify`` composes the three things a developer runs by hand to confirm a
project is healthy, into a single command with one verdict and a stable exit
code:

1. **Init** — discover the domain and initialize it (``Domain.init``).
2. **Check** — run the domain health validation (``Domain.check``), the same
   engine behind ``protean check``.
3. **Tests** — run the project's own ``pytest`` suite in the project directory.

Usage::

    # Verify the project discovered from the current directory
    protean verify

    # Explicit domain and project directory
    protean verify --domain=my_app.domain --path=.

    # Machine-readable envelope (CI-friendly)
    protean verify --json

Exit codes (a stable contract, ordered by precedence):

    0 — all green: init, check, and tests all pass
    1 — verify's own error: bad arguments, or the domain was not found
    2 — the domain was found but failed to initialize
    3 — check failed (errors or warnings)
    4 — tests failed

``check`` "fails" on errors **or** warnings (``status`` ``fail``/``warn``),
matching ``protean check``'s default ``[lint].level="warn"`` floor; an
info-only domain still passes. Unlike ``check`` and the other commands,
``verify`` does not use the ``handle_cli_exceptions`` decorator — it owns its
exit-code contract, so it catches load/init failures itself and maps them to
the codes above.
"""

import json
import os
import re
import subprocess
import sys
from typing import Annotated, Any, NoReturn

import typer
from rich import print

from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain

# Exit codes — the settled contract (see module docstring).
_EXIT_OK = 0
_EXIT_USAGE = 1
_EXIT_INIT = 2
_EXIT_CHECK = 3
_EXIT_TESTS = 4

# pytest returns 5 when it collected no tests. ``verify`` treats that as a pass
# for the tests stage: a project may legitimately have no tests yet, and the
# domain was still initialized and checked. The returncode is recorded in the
# envelope so a consumer can tell "no tests" apart from "tests passed".
_PYTEST_NO_TESTS = 5

# Best-effort parse of pytest's summary line ("2 passed", "1 failed, 3 passed").
# The subprocess returncode — not these counts — is authoritative for pass/fail.
_PASSED_RE = re.compile(r"(\d+) passed")
_FAILED_RE = re.compile(r"(\d+) failed")

_STAGES = ("init", "check", "tests")


def verify(
    domain: Annotated[
        str,
        typer.Option(
            "--domain",
            "-d",
            help="Path to the domain module (e.g. 'my_app.domain')",
        ),
    ] = ".",
    path: Annotated[
        str,
        typer.Option(
            "--path",
            help="Project directory to run the tests in (where pytest is invoked)",
        ),
    ] = ".",
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit a machine-readable JSON envelope instead of a table",
        ),
    ] = False,
) -> None:
    """Initialize a domain, run check, and run its tests — one verdict."""
    # Every stage starts "skipped"; a failure before it runs leaves it that way
    # so the envelope always carries all three keys.
    stages: dict[str, dict[str, Any]] = {
        stage: {"status": "skipped"} for stage in _STAGES
    }

    # --- Init stage -------------------------------------------------------
    try:
        derived_domain = derive_domain(domain)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        stages["init"] = {"status": "fail", "error": msg}
        _emit_and_exit(json_output, stages, "", _EXIT_USAGE, error_line=msg)

    assert derived_domain is not None

    try:
        derived_domain.init(traverse=True)
    except Exception as exc:
        msg = f"Domain failed to initialize: {exc}"
        stages["init"] = {"status": "fail", "error": msg}
        _emit_and_exit(json_output, stages, "", _EXIT_INIT, error_line=msg)

    stages["init"] = {"status": "pass", "error": None}

    # --- Check stage ------------------------------------------------------
    result = derived_domain.check()
    # Fail on errors or warnings; info-only findings are a pass, matching
    # ``protean check``'s default ``[lint].level="warn"`` floor.
    check_failed = result["status"] in {"fail", "warn"}
    stages["check"] = {
        "status": "fail" if check_failed else "pass",
        "counts": result["counts"],
        "errors": result["errors"],
        "diagnostics": result["diagnostics"],
    }

    # --- Tests stage ------------------------------------------------------
    # Run tests even when check failed, so the envelope carries every stage's
    # result; exit precedence (check before tests) is applied at the end.
    tests_stage, tests_output = _run_tests(path)
    stages["tests"] = tests_stage

    _emit(json_output, stages, tests_output)

    # --- Verdict + exit ---------------------------------------------------
    if check_failed:
        raise typer.Exit(_EXIT_CHECK)
    if tests_stage["status"] == "fail":
        raise typer.Exit(_EXIT_TESTS)
    raise typer.Exit(_EXIT_OK)


def _run_tests(path: str) -> tuple[dict[str, Any], str]:
    """Run the project's pytest suite in ``path`` and summarize the outcome.

    Returns the envelope stage dict plus the raw pytest output (kept out of the
    envelope, used only for the human table).
    """
    env = dict(os.environ)
    # Env hygiene, mirroring the scaffold-test harness: drop VIRTUAL_ENV so a
    # leaked value cannot point the child at a different source tree than
    # ``sys.executable``, and drop PROTEAN_ENV/PROTEAN_DEBUG so a value exported
    # in the parent shell does not leak into the project's own test run.
    for var in ("VIRTUAL_ENV", "PROTEAN_ENV", "PROTEAN_DEBUG"):
        env.pop(var, None)
    # A src-layout project that has not been installed still needs its ``src``
    # on the path for its own tests to import the package — the common state
    # right after ``protean new``. Prepend it when present; harmless otherwise.
    src = os.path.join(path, "src")
    if os.path.isdir(src):
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = src + os.pathsep + existing if existing else src

    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=path,
        capture_output=True,
        text=True,
        env=env,
    )
    output = completed.stdout + completed.stderr
    returncode = completed.returncode

    passed = 0
    if (match := _PASSED_RE.search(output)) is not None:
        passed = int(match.group(1))
    failed = 0
    if (match := _FAILED_RE.search(output)) is not None:
        failed = int(match.group(1))

    # returncode is authoritative: 0 = passed, 5 = no tests collected (a pass),
    # anything else = failure. A missed count parse never flips this.
    status = "pass" if returncode in (_EXIT_OK, _PYTEST_NO_TESTS) else "fail"

    return (
        {
            "status": status,
            "returncode": returncode,
            "passed": passed,
            "failed": failed,
        },
        output,
    )


def _verdict(stages: dict[str, dict[str, Any]]) -> str:
    """Overall verdict — "pass" only when every stage passed."""
    return "pass" if all(stages[s]["status"] == "pass" for s in _STAGES) else "fail"


def _envelope(stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build the settled JSON envelope from the accumulated stage results."""
    return {"verdict": _verdict(stages), "stages": stages}


def _emit(
    json_output: bool, stages: dict[str, dict[str, Any]], tests_output: str
) -> None:
    """Print either the JSON envelope or the human table."""
    if json_output:
        typer.echo(json.dumps(_envelope(stages), indent=2, sort_keys=True))
    else:
        _render(stages, tests_output)


def _emit_and_exit(
    json_output: bool,
    stages: dict[str, dict[str, Any]],
    tests_output: str,
    code: int,
    error_line: str = "",
) -> NoReturn:
    """Emit the result and raise ``typer.Exit`` with ``code`` (used on early
    init failures, where check and tests never run)."""
    if not json_output and error_line:
        print(f"[red]{error_line}[/red]")
    _emit(json_output, stages, tests_output)
    raise typer.Exit(code)


def _render(stages: dict[str, dict[str, Any]], tests_output: str) -> None:
    """Print a compact per-stage table and an overall verdict line."""
    label = {
        "pass": "[bold green]PASS[/bold green]",
        "fail": "[bold red]FAIL[/bold red]",
        "skipped": "[dim]SKIPPED[/dim]",
    }
    print("\n  Protean verify")
    for stage in _STAGES:
        status = stages[stage]["status"]
        detail = _stage_detail(stage, stages[stage])
        print(f"    {stage:<7} {label.get(status, status)}{detail}")

    # Surface the check diagnostics and the tail of the pytest output so the
    # human table is actionable, not just a set of PASS/FAIL labels.
    _render_check_detail(stages["check"])
    if stages["tests"]["status"] == "fail" and tests_output.strip():
        print("\n  [bold]pytest output:[/bold]")
        for line in tests_output.strip().splitlines()[-15:]:
            print(f"    {line}")

    verdict = _verdict(stages)
    overall = label.get("pass" if verdict == "pass" else "fail")
    print(f"\n  Overall: {overall}\n")


def _stage_detail(stage: str, data: dict[str, Any]) -> str:
    """One-line summary appended to a stage's row."""
    if stage == "check" and "counts" in data:
        counts = data["counts"]
        return (
            f"  ({counts['errors']} error(s), {counts['warnings']} warning(s), "
            f"{counts['infos']} info(s))"
        )
    if stage == "tests" and "returncode" in data:
        if data["returncode"] == _PYTEST_NO_TESTS:
            return "  (no tests collected)"
        return f"  ({data['passed']} passed, {data['failed']} failed)"
    if stage == "init" and data.get("error"):
        return f"  ({data['error']})"
    return ""


def _render_check_detail(check: dict[str, Any]) -> None:
    """Print the check errors and diagnostics (the reason check gated)."""
    for err in check.get("errors", []):
        print(f"    [red]✗ {err['message']}[/red]")
    for diag in check.get("diagnostics", []):
        level = diag.get("level", "info")
        marker = "[yellow]![/yellow]" if level == "warning" else "[cyan]·[/cyan]"
        code = diag.get("code", "")
        prefix = f"[dim]{code}:[/dim] " if code else ""
        print(f"    {marker} {prefix}{diag['message']}")
