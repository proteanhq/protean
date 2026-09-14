"""The tools an eval run drives the agent over.

The agent gets generic file operations plus a verify signal, and nothing else.
Deliberately no ``protean add``: handing the agent the scaffold command would
collapse the context-driven path into the deterministic ``add`` path and void
the comparison the eval exists to make.

- ``write_file(path, content)``: write a text file into the workspace.
- ``read_file(path)``: read a file back.
- ``list_dir(path=".")``: list a directory.
- ``run_verify()``: run ``protean verify`` on the produced project and return
  its verdict, so the agent gets the same feedback a developer would.

Every tool returns a plain dict carrying ``ok`` plus its result or an ``error``
string. :func:`execute_tool_call` is the single entry point the runner and
replay share; it turns an unknown tool, a bad-argument call, and a workspace
error into ``{"ok": False, "error": ...}`` feedback, so one bad call becomes
something the agent can react to. An unexpected exception from inside a tool is
a real bug and propagates.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import os
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

from tests.eval.transcript import ToolCall
from tests.eval.workspace import Workspace, WorkspaceError

__all__ = ["TOOLS", "TOOL_SPECS", "VerifyResult", "execute_tool_call", "run_verify"]


class VerifyResult(TypedDict):
    """The structured result of a ``run_verify`` call.

    ``ok`` is the pass/fail discriminator and equals every stage passing with a
    clean exit. ``codes`` are the sorted check-stage diagnostic and error codes;
    ``errors`` are stage failure messages (an init import error, a check config
    or fatal error, a failing test suite), so the agent has something to act on.
    ``error`` is present only when verify's output could not be parsed as the
    JSON envelope or the run timed out.
    """

    ok: bool
    verdict: Literal["pass", "fail"]
    counts: dict[str, int]
    codes: list[str]
    errors: list[str]
    exit_code: int
    error: NotRequired[str]


# Env vars dropped before the verify subprocess, mirroring the scaffold-test
# harness: VIRTUAL_ENV so a leaked value cannot point the child at a different
# source tree than sys.executable, and PROTEAN_ENV/PROTEAN_DEBUG so a value
# exported in the parent shell does not leak into the verify run. PROTEAN_DOMAIN
# and DOMAIN_ROOT_PATH too: verify honours the former over the `-d` argument and
# the latter as a Domain root, so either leaked value would steer verification
# away from the workspace and make the result depend on the outer environment.
_STRIPPED_ENV_VARS = (
    "VIRTUAL_ENV",
    "PROTEAN_ENV",
    "PROTEAN_DEBUG",
    "PROTEAN_DOMAIN",
    "DOMAIN_ROOT_PATH",
)

# A ceiling on the verify subprocess. The live lane runs model-generated code
# through pytest, whose import or a test could hang; the cap keeps a hung run
# from stalling the whole recording.
_VERIFY_TIMEOUT_SECONDS = 300

_EMPTY_COUNTS = {"errors": 0, "warnings": 0, "infos": 0}


def _tool_write_file(
    workspace: Workspace, *, path: str, content: str
) -> dict[str, Any]:
    return {"ok": True, "path": workspace.write(path, content)}


def _tool_read_file(workspace: Workspace, *, path: str) -> dict[str, Any]:
    return {"ok": True, "content": workspace.read(path)}


def _tool_list_dir(workspace: Workspace, *, path: str = ".") -> dict[str, Any]:
    return {"ok": True, "entries": workspace.list_dir(path)}


def _tool_run_verify(workspace: Workspace) -> VerifyResult:
    return run_verify(workspace.root)


# The tool registry: the names the agent may call, mapped to their
# implementations. execute_tool_call dispatches through this.
TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "write_file": _tool_write_file,
    "read_file": _tool_read_file,
    "list_dir": _tool_list_dir,
    "run_verify": _tool_run_verify,
}

# Provider-neutral descriptions a live driver hands to a model as its tool
# schema. The runner and replay lane do not read these; only a live driver does.
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "write_file",
        "description": "Write a text file into the project, creating parent directories. Overwrites an existing file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project-relative path."},
                "content": {"type": "string", "description": "The file's full text."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file from the project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project-relative path."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_dir",
        "description": "List a directory in the project. Directory entries end with '/'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Project-relative path; defaults to the project root.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "run_verify",
        "description": "Run `protean verify` on the project and return its verdict, counts, and diagnostic codes.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def execute_tool_call(workspace: Workspace, call: ToolCall) -> dict[str, Any]:
    """Dispatch *call* to its tool and return the tool's result dict.

    An unknown tool name, an argument mismatch (a missing or unexpected key),
    and a workspace error (a bad path, an I/O failure) all come back as
    ``{"ok": False, "error": ...}`` so the run loop treats a malformed call as
    agent-visible feedback. Argument binding is checked before the tool runs, so
    only a genuine binding failure is reported as "bad arguments"; an unexpected
    exception from inside a tool is a real bug and propagates.
    """
    # A non-string (unhashable) name would raise on the dict lookup; treat it as
    # a malformed call, like an unknown tool.
    if not isinstance(call.name, str):
        return {"ok": False, "error": f"tool name must be a string: {call.name!r}"}
    tool = TOOLS.get(call.name)
    if tool is None:
        return {"ok": False, "error": f"unknown tool: {call.name!r}"}
    try:
        inspect.signature(tool).bind(workspace, **call.input)
    except TypeError as exc:
        return {"ok": False, "error": f"bad arguments for {call.name!r}: {exc}"}
    try:
        return tool(workspace, **call.input)
    except (WorkspaceError, OSError) as exc:
        return {"ok": False, "error": str(exc)}


def run_verify(root: Path | str) -> VerifyResult:
    """Run ``protean verify --json`` on the project at *root* and summarize it.

    Returns ``ok`` (a pass verdict AND a clean exit), the ``verdict``, the
    check-stage ``counts``, the sorted diagnostic and error ``codes``, the
    check-stage error ``errors``, and the process ``exit_code``. The domain is
    discovered the way a developer's project is laid out: a root ``domain.py``
    uses the default discovery; a single ``src/<pkg>/domain.py`` is addressed by
    its path, which ``protean verify`` resolves to the domain the module
    defines. Output with no JSON envelope, or a run that exceeds the timeout, is
    reported as a failed verdict.

    ``verify`` executes the generated project (it imports the domain and runs
    pytest), so generated code can print to stdout. The envelope is decoded from
    the output rather than requiring stdout to be pure JSON, and a pass verdict
    is only honoured when the process also exited 0. Defending against a
    deliberately hostile generated project (one that fabricates an envelope and
    exits 0) needs a sandbox and is out of scope for this harness.
    """
    root_path = Path(root)
    env = {
        key: value for key, value in os.environ.items() if key not in _STRIPPED_ENV_VARS
    }
    # `-P` keeps the agent's workspace off this interpreter's module search, so a
    # generated `protean.py` at the root cannot shadow the framework CLI on
    # `-m protean`. It is a flag on the outer interpreter, not an inherited env
    # var, so verify's nested `python -m pytest` still sees the workspace on its
    # path and a root-layout project's own tests still import their modules.
    args = [sys.executable, "-P", "-m", "protean", "verify", "--json", "--path", "."]
    domain_arg = _discover_domain_arg(root_path)
    if domain_arg is not None:
        args += ["-d", domain_arg]

    # Run in its own session (a new process group) so a timeout can kill the
    # whole tree. verify launches pytest as a child; killing only the parent
    # would leave a hung generated test running and holding the workspace.
    process = subprocess.Popen(
        args,
        cwd=root_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        env=env,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=_VERIFY_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _terminate_tree(process)
        return {
            "ok": False,
            "verdict": "fail",
            "counts": dict(_EMPTY_COUNTS),
            "codes": [],
            "errors": [],
            "exit_code": -1,
            "error": f"verify timed out after {_VERIFY_TIMEOUT_SECONDS}s",
        }
    return _summarize_verify(stdout, process.returncode, stderr)


def _terminate_tree(process: subprocess.Popen) -> None:
    """Kill the timed-out verify process and its children, then reap it.

    ``start_new_session`` made the process a group leader, so on POSIX one
    ``killpg`` takes down verify and its nested pytest together. Platforms
    without process groups fall back to killing the direct process only, so a
    nested pytest could outlive the timeout there; this harness is maintainer-
    side and runs on POSIX, so that fallback is a known, accepted limitation."""
    try:
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:  # pragma: no cover - exercised only on non-POSIX platforms
            process.kill()
    except (ProcessLookupError, PermissionError, OSError):  # pragma: no cover
        process.kill()
    finally:
        with contextlib.suppress(subprocess.TimeoutExpired, ValueError, OSError):
            process.communicate(timeout=5)


def _decode_envelope(stdout: str) -> dict[str, Any] | None:
    """Decode verify's JSON envelope from stdout, tolerating stray output around
    it (a generated domain may print during import).

    ``verify`` prints its envelope last, so this returns the **last** top-level
    JSON object in the output: a stray print earlier, even one that looks like a
    JSON object, does not win over the real trailing envelope. Returns ``None``
    when there is no JSON object at all.
    """
    decoder = json.JSONDecoder()
    last: dict[str, Any] | None = None
    index = stdout.find("{")
    while index != -1:
        try:
            # Scanning only from "{", so a successful decode is always an object.
            candidate, end = decoder.raw_decode(stdout, index)
        except json.JSONDecodeError:
            index = stdout.find("{", index + 1)
            continue
        last = candidate
        index = stdout.find("{", max(end, index + 1))
    return last


def _summarize_verify(stdout: str, exit_code: int, stderr: str = "") -> VerifyResult:
    envelope = _decode_envelope(stdout)
    if envelope is None:
        # verify crashed or emitted no JSON envelope. Keep a stderr tail in the
        # error so the failure is diagnosable without re-running by hand.
        detail = stderr.strip().splitlines()[-5:]
        suffix = f": {' / '.join(detail)}" if detail else ""
        return {
            "ok": False,
            "verdict": "fail",
            "counts": dict(_EMPTY_COUNTS),
            "codes": [],
            "errors": [],
            "exit_code": exit_code,
            "error": f"verify did not emit a parseable JSON envelope{suffix}",
        }

    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}

    def _stage(name: str) -> dict[str, Any]:
        stage = stages.get(name)
        return stage if isinstance(stage, dict) else {}

    init, check, tests = _stage("init"), _stage("check"), _stage("tests")

    diagnostics = check.get("diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, list) else []
    check_errors = check.get("errors")
    check_errors = check_errors if isinstance(check_errors, list) else []
    counts = (
        check.get("counts")
        if isinstance(check.get("counts"), dict)
        else dict(_EMPTY_COUNTS)
    )
    codes = {
        diag["code"]
        for diag in diagnostics
        if isinstance(diag, dict) and diag.get("code")
    } | {
        err["code"] for err in check_errors if isinstance(err, dict) and err.get("code")
    }

    # Surface every stage's failure detail, not just check's: an init import
    # error (exit 3) or a failing test suite (exit 5) is the actionable feedback
    # run_verify exists to give the agent.
    errors: list[str] = []
    if init.get("status") == "fail" and init.get("error"):
        errors.append(str(init["error"]))
    errors.extend(
        str(err["message"])
        for err in check_errors
        if isinstance(err, dict) and err.get("message")
    )
    if tests.get("status") == "fail":
        errors.append(
            f"tests failed (returncode {tests.get('returncode')}, "
            f"{tests.get('failed')} failed)"
        )

    # A pass is derived from the stage tree, not the top-level verdict field:
    # every stage must report pass and the process must have exited 0. A
    # truncated envelope missing a stage, or one claiming pass alongside a
    # non-zero exit, is a fail.
    passed = exit_code == 0 and all(
        stage.get("status") == "pass" for stage in (init, check, tests)
    )
    return {
        "ok": passed,
        "verdict": "pass" if passed else "fail",
        "counts": counts,
        "codes": sorted(codes),
        "errors": errors,
        "exit_code": exit_code,
    }


def _discover_domain_arg(root: Path) -> str | None:
    """Return the ``-d`` value ``protean verify`` needs, or ``None`` to use the
    default discovery.

    A root ``domain.py`` is what the default discovery already finds, so it
    needs no ``-d``. Otherwise a single ``src/<pkg>/domain.py`` is addressed by
    its path; ``protean verify`` resolves the domain the module defines (or
    reports the file's own error if it will not import). A layout that matches
    neither returns ``None`` and lets verify report the missing domain itself.
    """
    if (root / "domain.py").is_file():
        return None
    candidates = (
        sorted((root / "src").glob("*/domain.py")) if (root / "src").is_dir() else []
    )
    if len(candidates) != 1:
        return None
    package = candidates[0].parent.name
    return f"src/{package}/domain.py"
