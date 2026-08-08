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
    1 — verify's own error: the domain was not found, or ``--path`` is not a
        directory
    2 — the domain was found but failed to initialize
    3 — check failed (a malformed ``[lint]`` config, or findings at or above
        the ``[lint].level`` floor)
    4 — tests failed

A malformed command line (an unknown flag, a missing option value) is rejected
by the argument parser *before* ``verify`` runs and exits ``2`` — Click's
convention, which happens to overlap the init-failure code. The contract above
applies once ``verify`` itself starts running.

The check stage honours ``[lint].level`` (default ``"warn"``), the same
severity floor ``protean check`` uses: ``"error"`` gates on errors only,
``"warn"`` also gates on warnings, ``"info"`` gates on any finding. It also
validates the ``[lint]`` config the way ``protean check`` does — ``verify``
calls ``Domain.check`` directly, whose IR build swallows the ``ConfigurationError``
a bad ``[lint]`` block raises, so without this validation a malformed config
would read as a false green. Unlike ``check`` and the other commands, ``verify``
does not use the ``handle_cli_exceptions`` decorator — it owns its exit-code
contract, so it catches load/init failures itself and maps them to the codes
above.
"""

import json
import os
import re
import subprocess
import sys
from typing import Annotated, Any, NoReturn

import typer
from rich import print
from rich.markup import escape

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

# Valid values for the ``[lint].level`` config key (the check-stage severity
# floor). Mirrors ``check.py``'s ``_LINT_LEVELS``.
_LINT_LEVELS = frozenset({"error", "warn", "info"})


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

    # ``--path`` is handed to ``subprocess.run(cwd=...)`` for the tests stage;
    # a missing directory (or a file) would otherwise crash there with an
    # uncaught ``FileNotFoundError``/``NotADirectoryError`` — and in ``--json``
    # mode corrupt the envelope with a traceback. Reject it up front as a usage
    # error, before doing any init work.
    if not os.path.isdir(path):
        msg = f"--path is not a directory: {path}"
        _emit_and_exit(json_output, stages, "", _EXIT_USAGE, error_line=msg)

    # --- Init stage -------------------------------------------------------
    try:
        derived_domain = derive_domain(domain)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        stages["init"] = {"status": "fail", "error": msg}
        _emit_and_exit(json_output, stages, "", _EXIT_USAGE, error_line=msg)
    except Exception as exc:
        # ``derive_domain`` wraps the domain-not-found and most import-error
        # cases in ``NoDomainException`` (caught above), but a domain module
        # that raises during import — a ``SyntaxError``, or any exception its
        # own top-level code throws — comes through as that exception, not
        # ``NoDomainException``. Treat it as an init failure (2), the same
        # code a domain that imports fine but blows up in ``.init()`` gets,
        # rather than letting it crash out as an unhandled traceback.
        msg = f"Domain failed to initialize: {exc}"
        stages["init"] = {"status": "fail", "error": msg}
        _emit_and_exit(json_output, stages, "", _EXIT_INIT, error_line=msg)

    # ``derive_domain`` returns ``None`` (rather than raising) when the path is
    # empty and ``PROTEAN_DOMAIN`` is unset — e.g. ``-d ""`` or ``-d "$PROTEAN_DOMAIN"``
    # with the var unset. Treat it as domain-not-found, not an ``AssertionError``.
    if derived_domain is None:
        msg = "No domain found. Provide --domain or set PROTEAN_DOMAIN."
        stages["init"] = {"status": "fail", "error": msg}
        _emit_and_exit(json_output, stages, "", _EXIT_USAGE, error_line=msg)

    try:
        derived_domain.init(traverse=True)
    except Exception as exc:
        msg = f"Domain failed to initialize: {exc}"
        stages["init"] = {"status": "fail", "error": msg}
        _emit_and_exit(json_output, stages, "", _EXIT_INIT, error_line=msg)

    stages["init"] = {"status": "pass", "error": None}

    # --- Check stage ------------------------------------------------------
    check_failed, stages["check"] = _run_check(derived_domain)

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


def _validate_lint_level(lint_config: dict[str, Any]) -> str | None:
    """Return an error message if ``[lint].level`` is not a valid floor, else ``None``."""
    level = lint_config.get("level", "warn")
    if level not in _LINT_LEVELS:
        return f"[lint].level: {level!r} is invalid. Use 'error', 'warn', or 'info'."
    return None


def _check_gates(counts: dict[str, Any], lint_level: str) -> bool:
    """Whether a check result gates, honouring ``[lint].level`` — same rule as
    ``protean check``: errors always gate; ``"warn"`` also gates warnings;
    ``"info"`` gates any finding; ``"error"`` gates on errors alone."""
    if counts["errors"] > 0:
        return True
    if lint_level == "error":
        return False
    if counts["warnings"] > 0:
        return True
    return bool(lint_level == "info" and counts["infos"] > 0)


def _config_error_stage(message: str, code: str) -> dict[str, Any]:
    """A check-stage dict that carries a single fatal error (bad config or a
    ``check()`` crash), shaped like a real check result so the envelope keys and
    the human renderer are unchanged."""
    return {
        "status": "fail",
        "counts": {"errors": 1, "warnings": 0, "infos": 0},
        "errors": [{"code": code, "message": message}],
        "diagnostics": [],
    }


def _run_check(domain: Any) -> tuple[bool, dict[str, Any]]:
    """Validate the ``[lint]`` config, run ``Domain.check``, and decide whether
    check gates. Returns ``(check_failed, stage_dict)``.

    ``verify`` calls ``Domain.check()`` directly, which — unlike ``protean check``
    — skips the ``[lint]`` config validation and wraps its IR build in a bare
    ``except Exception: pass``. So a malformed ``[lint]`` block (a bad
    ``suppressions`` count, a non-table ``[lint]``, an invalid ``level``) is
    swallowed and reads as a false green. Run the same validation ``check`` runs,
    up front, and surface any failure as a check-stage error (exit 3).
    """
    # Imported locally to keep ``protean --help`` from eagerly pulling in the
    # heavy IR builder subsystem (mirrors ``check.py``).
    from protean.ir.builder import (  # noqa: PLC0415
        validate_lint_suppressions,
        validate_lint_table,
    )

    lint_config = domain.config.get("lint", {})
    # Order matters: the table check must run first — if ``[lint]`` is not a
    # table, reading ``level``/``suppressions`` off it would raise. ``or``
    # short-circuits, so the later reads never touch a non-dict.
    config_error = validate_lint_table(lint_config) or _validate_lint_level(lint_config)
    if config_error is None:
        config_error = validate_lint_suppressions(lint_config.get("suppressions", {}))
    if config_error is not None:
        return True, _config_error_stage(config_error, "INVALID_LINT_CONFIG")

    try:
        result = domain.check()
    except Exception as exc:
        # Defensive: ``check()`` re-runs ``_prepare(traverse=True, validate=False)``
        # and builds the IR, neither wrapped here. init already succeeded above,
        # so no concrete trigger is known — but a crash must surface as the
        # contracted exit 3, not a traceback.
        return True, _config_error_stage(f"Domain check failed: {exc}", "CHECK_FAILED")

    lint_level = lint_config.get("level", "warn")
    check_failed = _check_gates(result["counts"], lint_level)
    stage = {
        "status": "fail" if check_failed else "pass",
        "counts": result["counts"],
        "errors": result["errors"],
        "diagnostics": result["diagnostics"],
    }
    return check_failed, stage


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
        # Decode leniently: under a non-UTF-8 locale, pytest output with
        # non-decodable bytes would otherwise raise ``UnicodeDecodeError`` here.
        errors="replace",
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
        print(f"[red]{escape(error_line)}[/red]")
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
        return f"  ({escape(data['error'])})"
    return ""


def _render_check_detail(check: dict[str, Any]) -> None:
    """Print the check errors and diagnostics (the reason check gated).

    Messages are arbitrary text (a config error naming ``[lint].suppressions``,
    a rule message with a class name in brackets), so escape them before the
    ``rich`` print — otherwise a bracketed token like ``[lint]`` is parsed as
    markup and silently dropped from the output.
    """
    for err in check.get("errors", []):
        print(f"    [red]✗ {escape(err['message'])}[/red]")
    for diag in check.get("diagnostics", []):
        level = diag.get("level", "info")
        marker = "[yellow]![/yellow]" if level == "warning" else "[cyan]·[/cyan]"
        code = diag.get("code", "")
        prefix = f"[dim]{escape(code)}:[/dim] " if code else ""
        print(f"    {marker} {prefix}{escape(diag['message'])}")
