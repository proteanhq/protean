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

    # Run all three stages under the ``memory`` environment
    protean verify --env memory

All three stages run under one environment, named by ``--env`` (default
``test``). ``verify`` sets ``PROTEAN_ENV`` to it before the domain is imported,
so init and check load that config overlay, and passes the same value to the
pytest child. A ``PROTEAN_ENV`` exported in the shell does not change the
config any stage loads, and the caller's value is restored when ``run_verify``
returns. The shell's value still picks the default log level and format,
because ``verify`` sets up logging before the stages run.

Under ``--json`` the result is the shared CLI envelope (see
:mod:`protean.cli.result`): the verdict and per-stage tree under ``data``, the
check-stage diagnostics at the top level, and a coarse ``status``.

Exit codes follow the CLI-wide convention (see :mod:`protean.cli.result`), with
the stage classes pinned. Ordered by precedence:

    0 — all green: init, check, and tests all pass
    2 — a usage error: the domain was not found, ``--path`` is not a
        directory, or ``--env`` is blank (Click also exits ``2`` for a
        malformed command line)
    3 — the domain was found but failed to initialize
    4 — check failed (a malformed ``[lint]`` config, or findings at or above
        the ``[lint].level`` floor)
    5 — tests failed

A malformed command line (an unknown flag, a missing option value) is rejected
by the argument parser *before* ``verify`` runs and also exits ``2`` — Click's
convention, which the usage class here matches. The contract above applies once
``verify`` itself starts running.

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

The compute is split from the emit. :func:`run_verify` runs the three stages and
returns a :class:`VerifyResult` (the stage tree, verdict, and mapped exit code)
without printing or raising ``typer.Exit``. The ``verify`` command is the thin
wrapper that emits the result (human table or JSON envelope) and exits. A caller
that composes verify into a larger flow (``protean new --from-model``) calls
``run_verify`` and maps ``result.exit_code`` itself.
"""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Annotated, Any

import typer
from rich import print
from rich.console import Console
from rich.markup import escape

from protean.cli.result import EnvelopeStatus, build_envelope, route_logs_to_stderr
from protean.exceptions import NoDomainException
from protean.utils.domain_discovery import derive_domain

# Exit codes — the settled contract (see module docstring). Usage is 2 (the
# CLI-wide convention and Click's own default); the stage classes shift up by
# one so 2 is reserved for usage.
_EXIT_OK = 0
_EXIT_USAGE = 2
_EXIT_INIT = 3
_EXIT_CHECK = 4
_EXIT_TESTS = 5

# Error lines write to stderr so ``--json`` keeps stdout to the envelope alone.
_ERR_CONSOLE = Console(stderr=True)

# pytest returns 5 when it collected no tests. ``verify`` treats that as a pass
# for the tests stage: a project may legitimately have no tests yet, and the
# domain was still initialized and checked. The returncode is recorded in the
# envelope so a consumer can tell "no tests" apart from "tests passed".
_PYTEST_NO_TESTS = 5

# Best-effort parse of pytest's summary line ("2 passed", "1 failed, 3 passed").
# The subprocess returncode — not these counts — is authoritative for pass/fail.
# The counts are read from the final summary line only: earlier output (a
# failure message such as "port 15432 failed", a ``-ra`` skip reason) can carry
# the same "<N> passed" / "<N> failed" text. The line may sit inside a ``=====``
# banner and end with an "(h:mm:ss)" or "(1 day, h:mm:ss)" suffix on long runs.
# The body must follow pytest's stats grammar ("<N> <word>, ..." or "no tests
# ran"), so a later line such as "Finished in 3s" printed by a plugin is not
# taken for the summary.
_SUMMARY_RE = re.compile(
    r"^=*\s*(?P<body>\d+ [a-z]+(?:, \d+ [a-z]+)*|no tests ran)"
    r" in \d+(?:\.\d+)?s(?:\s*\([^)]*\))?\s*=*$"
)
_PASSED_RE = re.compile(r"\b(\d+) passed")
_FAILED_RE = re.compile(r"\b(\d+) failed")
# A project that forces ``--color=yes`` wraps the summary in ANSI escapes.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_STAGES = ("init", "check", "tests")

# Valid values for the ``[lint].level`` config key (the check-stage severity
# floor). Mirrors ``check.py``'s ``_LINT_LEVELS``.
_LINT_LEVELS = frozenset({"error", "warn", "info"})


@dataclass
class VerifyResult:
    """The outcome of a verify run, computed but not yet emitted.

    :func:`run_verify` returns this; the ``verify`` command turns it into console
    output and an exit code. Nothing here has printed or exited, so
    ``protean new --from-model`` can run verify in-process and map
    ``result.exit_code`` instead of catching a ``typer.Exit``.

    - ``stages`` is the per-stage tree (init/check/tests), the same dict the
      envelope and the human table read.
    - ``exit_code`` is the settled code the command exits with (0/2/3/4/5).
    - ``status`` is the coarse envelope status: ``"pass"`` all green, ``"fail"`` a
      detected failure, ``"error"`` a usage error caught before any stage ran.
    - ``tests_output`` is the raw pytest output, kept for the human table only.
    - ``error_line`` is the red line the command prints to stderr, empty when
      there is none.
    - ``envelope_error`` is the ``data.error`` slot: the usage-error message when
      no stage carries it, empty otherwise.
    """

    stages: dict[str, dict[str, Any]]
    exit_code: int
    status: EnvelopeStatus
    tests_output: str = ""
    error_line: str = ""
    envelope_error: str = ""


def run_verify(domain: str, path: str, env: str = "test") -> VerifyResult:
    """Run init + check + tests and return the result, without printing or exiting.

    This is the compute-only core behind ``protean verify``: it discovers and
    initializes the domain, runs ``Domain.check``, runs the project's pytest suite
    in ``path``, and maps the outcome to the settled exit code. The early
    usage/init failures (a bad ``--path``, a blank ``env``, a domain that is not
    found or fails to load) become early returns that carry the stage tree, an
    error line, a status class and an exit code. The ``verify`` command emits
    the result and exits; ``protean new --from-model`` maps ``result.exit_code``.

    Init and check run in the calling process, so this is meant for one call per
    process (the CLI's use). A second call in the same process for a different
    project that shares a package name returns the first project's result:
    ``__import__`` caches the module under its dotted name, so the second call
    re-inits the first domain. Verifying several projects from one process needs
    a fresh interpreter per call, or a reset of the module cache between calls.

    All three stages run under the environment ``env``. ``PROTEAN_ENV`` is set to
    it for the whole call, and the pytest child gets the same value. The caller's
    ``PROTEAN_ENV`` (or its absence) is restored on every return path. Init and
    check load the ``env`` config overlay only when this call is the first to
    import the domain module: a module already in ``sys.modules`` (imported by
    the caller, or by an earlier call with a different ``env``) keeps the config
    it loaded then, while the tests stage still runs under ``env``.
    """
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
        return _early_result(stages, _EXIT_USAGE, msg)

    # A blank name selects no config overlay, yet on the command line it looks
    # like a choice was made. Surrounding spaces would match no overlay name,
    # so they are dropped.
    env = env.strip()
    if not env:
        return _early_result(stages, _EXIT_USAGE, "--env must not be blank")

    # ``Domain.__init__`` reads ``PROTEAN_ENV`` when it loads config, and
    # ``derive_domain`` constructs the domain by importing its module, so the
    # variable must be set before init starts.
    previous_env = os.environ.get("PROTEAN_ENV")
    os.environ["PROTEAN_ENV"] = env
    try:
        return _run_stages(stages, domain, path, env)
    finally:
        if previous_env is None:
            os.environ.pop("PROTEAN_ENV", None)
        else:
            os.environ["PROTEAN_ENV"] = previous_env


def _run_stages(
    stages: dict[str, dict[str, Any]], domain: str, path: str, env: str
) -> VerifyResult:
    """Run init, check and tests in order and map the outcome to a result."""
    # --- Init stage -------------------------------------------------------
    try:
        derived_domain = derive_domain(domain)
    except NoDomainException as exc:
        msg = f"Error loading Protean domain: {exc.args[0]}"
        stages["init"] = {"status": "fail", "error": msg}
        # ``locate_domain`` (domain_discovery.py) raises ``NoDomainException``
        # both when the module can't be found at all, and when it *is* found
        # but an ``ImportError`` happens while importing it — it wraps the
        # latter with a "While importing ..." prefix. Only the former is a
        # usage error (bad ``--domain``); the latter means the domain was
        # found but failed to load, so it gets the init-failure code instead.
        exit_code = (
            _EXIT_INIT
            if str(exc.args[0]).startswith("While importing ")
            else _EXIT_USAGE
        )
        return _early_result(stages, exit_code, msg)
    except Exception as exc:  # noqa: BLE001 - CLI boundary: importing user code can raise anything
        # ``derive_domain`` wraps the domain-not-found and most import-error
        # cases in ``NoDomainException`` (caught above), but a domain module
        # that raises during import — a ``SyntaxError``, or any exception its
        # own top-level code throws — comes through as that exception, not
        # ``NoDomainException``. Treat it as an init failure (3), the same
        # code a domain that imports fine but blows up in ``.init()`` gets,
        # rather than letting it crash out as an unhandled traceback.
        msg = f"Domain failed to initialize: {exc}"
        stages["init"] = {"status": "fail", "error": msg}
        return _early_result(stages, _EXIT_INIT, msg)

    # ``derive_domain`` returns ``None`` (rather than raising) when the path is
    # empty and ``PROTEAN_DOMAIN`` is unset — e.g. ``-d ""`` or ``-d "$PROTEAN_DOMAIN"``
    # with the var unset. Treat it as domain-not-found, not an ``AssertionError``.
    if derived_domain is None:
        msg = "No domain found. Provide --domain or set PROTEAN_DOMAIN."
        stages["init"] = {"status": "fail", "error": msg}
        return _early_result(stages, _EXIT_USAGE, msg)

    try:
        derived_domain.init(traverse=True)
    except Exception as exc:  # noqa: BLE001 - CLI boundary: user domain code can raise anything
        msg = f"Domain failed to initialize: {exc}"
        stages["init"] = {"status": "fail", "error": msg}
        return _early_result(stages, _EXIT_INIT, msg)

    stages["init"] = {"status": "pass", "error": None}

    # --- Check stage ------------------------------------------------------
    check_failed, stages["check"] = _run_check(derived_domain)

    # --- Tests stage ------------------------------------------------------
    # Run tests even when check failed, so the envelope carries every stage's
    # result; exit precedence (check before tests) is applied below.
    tests_stage, tests_output = _run_tests(path, env)
    stages["tests"] = tests_stage

    status: EnvelopeStatus = "pass" if _verdict(stages) == "pass" else "fail"

    # --- Verdict + exit code ----------------------------------------------
    # Precedence: check (4) before tests (5), 0 when both pass.
    if check_failed:
        exit_code = _EXIT_CHECK
    elif tests_stage["status"] == "fail":
        exit_code = _EXIT_TESTS
    else:
        exit_code = _EXIT_OK

    return VerifyResult(
        stages=stages,
        exit_code=exit_code,
        status=status,
        tests_output=tests_output,
    )


def _early_result(
    stages: dict[str, dict[str, Any]], code: int, error_line: str
) -> VerifyResult:
    """Build the result for an early exit: a usage or init failure caught before
    check and tests run. Mirrors what ``verify`` did inline before the core split:
    the envelope status follows the exit-code class (usage → ``"error"``, a
    detected failure → ``"fail"``), and the error line lands at ``data.error`` only
    when no stage already carries it (the up-front ``--path`` check), so it is not
    duplicated with ``data.stages.init.error``."""
    status: EnvelopeStatus = "error" if code == _EXIT_USAGE else "fail"
    envelope_error = error_line if stages["init"]["status"] == "skipped" else ""
    return VerifyResult(
        stages=stages,
        exit_code=code,
        status=status,
        error_line=error_line,
        envelope_error=envelope_error,
    )


def verify(
    ctx: typer.Context,
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
    env: Annotated[
        str,
        typer.Option(
            "--env",
            help="Environment (PROTEAN_ENV) that init, check and tests all run under",
        ),
    ] = "test",
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit a machine-readable JSON envelope instead of a table",
        ),
    ] = False,
) -> None:
    """Initialize a domain, run check, and run its tests — one verdict."""
    # Route logs to stderr before ``derive_domain`` imports the domain module, so
    # a stray import-time log cannot corrupt the JSON envelope on stdout. Skip if
    # the CLI's --log-config/--log-level/--log-format callback already configured
    # logging, so that configuration is not silently discarded.
    from protean.cli._helpers import CTX_LOG_CONFIGURED  # noqa: PLC0415

    parent_obj = ctx.obj or {}
    route_logs_to_stderr(
        log_already_configured=bool(parent_obj.get(CTX_LOG_CONFIGURED))
    )

    result = run_verify(domain, path, env)

    # The red error line goes to stderr so ``--json`` stdout stays a single
    # parseable object.
    if not json_output and result.error_line:
        _ERR_CONSOLE.print(f"[red]{escape(result.error_line)}[/red]")
    _emit(
        json_output,
        result.stages,
        result.tests_output,
        result.status,
        error=result.envelope_error,
    )
    raise typer.Exit(result.exit_code)


def _validate_lint_level(lint_config: dict[str, Any]) -> str | None:
    """Return an error message if ``[lint].level`` is not a valid floor, else ``None``."""
    level = lint_config.get("level", "warn")
    if not isinstance(level, str) or level not in _LINT_LEVELS:
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

    ``Domain.check()`` does not validate ``[lint].level``, and it reports a
    malformed ``[lint]`` value only by raising ``ConfigurationError``. Run the
    same validation ``protean check`` runs, up front, so every
    bad ``[lint]`` value (a non-table ``[lint]``, an invalid ``level``, a bad
    ``suppressions`` count) surfaces as an ``INVALID_LINT_CONFIG`` check-stage
    error (exit 4).
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
    except Exception as exc:  # noqa: BLE001 - CLI boundary: a crash must exit 4, not dump a traceback
        # Defensive: ``check()`` re-runs ``_prepare(traverse=True, validate=False)``
        # and builds the IR, neither wrapped here. init already succeeded above,
        # so no concrete trigger is known — but a crash must surface as the
        # contracted exit 4, not a traceback.
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


def _parse_counts(stdout: str) -> tuple[int, int]:
    """Return the ``(passed, failed)`` counts from pytest's final summary line.

    A count missing from the summary is 0, and output with no summary line at
    all gives ``(0, 0)``.
    """
    for line in reversed(stdout.splitlines()):
        match = _SUMMARY_RE.match(_ANSI_RE.sub("", line).strip())
        if match is None:
            continue
        body = match.group("body")
        passed_match = _PASSED_RE.search(body)
        failed_match = _FAILED_RE.search(body)
        return (
            int(passed_match.group(1)) if passed_match else 0,
            int(failed_match.group(1)) if failed_match else 0,
        )
    return 0, 0


def _run_tests(path: str, env: str) -> tuple[dict[str, Any], str]:
    """Run the project's pytest suite in ``path`` under ``env`` and summarize the
    outcome.

    Returns the envelope stage dict plus the raw pytest output (kept out of the
    envelope, used only for the human table).
    """
    child_env = dict(os.environ)
    # Env hygiene, mirroring the scaffold-test harness: drop VIRTUAL_ENV so a
    # leaked value cannot point the child at a different source tree than
    # ``sys.executable``, and drop PROTEAN_DEBUG so a value exported in the
    # parent shell does not leak into the project's own test run. The child
    # gets the environment verify chose for all stages; the Protean pytest
    # plugin only ``setdefault``s PROTEAN_ENV, so this value wins over its
    # ``--protean-env`` option.
    for var in ("VIRTUAL_ENV", "PROTEAN_DEBUG"):
        child_env.pop(var, None)
    child_env["PROTEAN_ENV"] = env
    # A src-layout project that has not been installed still needs its ``src``
    # on the path for its own tests to import the package — the common state
    # right after ``protean new``. Prepend it when present; harmless otherwise.
    src = os.path.join(path, "src")
    if os.path.isdir(src):
        existing = child_env.get("PYTHONPATH", "")
        child_env["PYTHONPATH"] = src + os.pathsep + existing if existing else src

    # ``--verbosity`` sets the level outright, where ``-q`` only lowers it: a
    # project with ``addopts = -q`` plus a forced ``-q`` runs at -2, and pytest
    # prints no summary line at that level.
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--verbosity=-1"],
        cwd=path,
        capture_output=True,
        text=True,
        # Decode leniently: under a non-UTF-8 locale, pytest output with
        # non-decodable bytes would otherwise raise ``UnicodeDecodeError`` here.
        errors="replace",
        env=child_env,
        check=False,
    )
    output = completed.stdout + completed.stderr
    returncode = completed.returncode

    # pytest writes its summary to stdout; stderr is appended after it in
    # ``output``, so parsing only stdout keeps a trailing stderr line from
    # being mistaken for the summary.
    passed, failed = _parse_counts(completed.stdout)

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


def _envelope(
    stages: dict[str, dict[str, Any]], status: EnvelopeStatus, error: str = ""
) -> dict[str, Any]:
    """Build the shared CLI envelope from the accumulated stage results.

    The verdict and per-stage tree go under ``data``; the check-stage
    diagnostics surface at the top level (empty when check never ran).
    ``status`` is the coarse verdict: ``"pass"`` all green, ``"fail"`` a stage
    the command detected as failing, ``"error"`` a usage error it could not run
    past. ``error`` — set only for a usage error caught before any stage
    ran — lands at ``data.error`` (mirrors ``check``'s usage-error shape), so
    the message survives in ``--json`` output even though no stage carries it.
    """
    diagnostics = stages["check"].get("diagnostics", [])
    data: dict[str, Any] = {"verdict": _verdict(stages), "stages": stages}
    if error:
        data["error"] = error
    return build_envelope(status=status, data=data, diagnostics=diagnostics)


def _emit(
    json_output: bool,
    stages: dict[str, dict[str, Any]],
    tests_output: str,
    status: EnvelopeStatus,
    error: str = "",
) -> None:
    """Print either the JSON envelope or the human table."""
    if json_output:
        envelope = _envelope(stages, status, error=error)
        typer.echo(json.dumps(envelope, indent=2, sort_keys=True))
    else:
        _render(stages, tests_output)


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
    if stages["tests"]["status"] == "fail":
        _render_pytest_tail(tests_output)

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
        first_line = data["error"].strip().splitlines()[0]
        return f"  ({escape(first_line)})"
    return ""


def _render_pytest_tail(tests_output: str) -> None:
    """Print the last lines of the pytest output, the reason the tests stage failed.

    Shared by ``verify``'s human table and ``protean new --from-model``, so a
    failed build shows the pytest tail in both. Empty output prints nothing.
    """
    if not tests_output.strip():
        return
    print("\n  [bold]pytest output:[/bold]")
    for line in tests_output.strip().splitlines()[-15:]:
        print(f"    {line}")


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
