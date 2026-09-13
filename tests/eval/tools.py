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

import inspect
import json
import os
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

    ``ok`` is the pass/fail discriminator and equals ``verdict == "pass"``.
    ``codes`` are the check-stage diagnostic codes, sorted. ``error`` is present
    only when verify's output could not be parsed as the JSON envelope or the
    run timed out.
    """

    ok: bool
    verdict: Literal["pass", "fail"]
    counts: dict[str, int]
    codes: list[str]
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

    Returns ``ok`` (the verdict is a pass), the ``verdict``, the check-stage
    ``counts``, the sorted diagnostic ``codes``, and the process ``exit_code``.
    The domain is discovered the way a developer's project is laid out: a root
    ``domain.py`` uses the default discovery; a single ``src/<pkg>/domain.py`` is
    addressed by its path, which ``protean verify`` resolves to the domain the
    module defines. Output that will not parse as the JSON envelope, or a run
    that exceeds the timeout, is reported as a failed verdict.
    """
    root_path = Path(root)
    env = {
        key: value for key, value in os.environ.items() if key not in _STRIPPED_ENV_VARS
    }
    args = [sys.executable, "-m", "protean", "verify", "--json", "--path", "."]
    domain_arg = _discover_domain_arg(root_path)
    if domain_arg is not None:
        args += ["-d", domain_arg]

    try:
        completed = subprocess.run(
            args,
            cwd=root_path,
            capture_output=True,
            text=True,
            errors="replace",
            env=env,
            timeout=_VERIFY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "verdict": "fail",
            "counts": dict(_EMPTY_COUNTS),
            "codes": [],
            "exit_code": -1,
            "error": f"verify timed out after {_VERIFY_TIMEOUT_SECONDS}s",
        }
    return _summarize_verify(completed.stdout, completed.returncode, completed.stderr)


def _summarize_verify(stdout: str, exit_code: int, stderr: str = "") -> VerifyResult:
    def _unparseable() -> VerifyResult:
        # verify crashed or emitted something other than the JSON envelope. Keep
        # a stderr tail in the error so the failure is diagnosable without
        # re-running by hand.
        detail = stderr.strip().splitlines()[-5:]
        suffix = f": {' / '.join(detail)}" if detail else ""
        return {
            "ok": False,
            "verdict": "fail",
            "counts": dict(_EMPTY_COUNTS),
            "codes": [],
            "exit_code": exit_code,
            "error": f"verify did not emit a parseable JSON envelope{suffix}",
        }

    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return _unparseable()
    # json.loads accepts a list, string, or null; the envelope must be an object.
    if not isinstance(envelope, dict):
        return _unparseable()

    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}
    check = stages.get("check") if isinstance(stages.get("check"), dict) else {}
    diagnostics = check.get("diagnostics")
    diagnostics = diagnostics if isinstance(diagnostics, list) else []
    counts = (
        check.get("counts")
        if isinstance(check.get("counts"), dict)
        else dict(_EMPTY_COUNTS)
    )
    verdict = data.get("verdict", "fail")
    codes = sorted(
        diag.get("code", "")
        for diag in diagnostics
        if isinstance(diag, dict) and diag.get("code")
    )
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "counts": counts,
        "codes": codes,
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
