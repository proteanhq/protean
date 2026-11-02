"""Git utilities for loading IR files from specific commits.

Usage::

    from protean.ir.git import load_ir_from_commit

    ir_dict = load_ir_from_commit("HEAD", ".protean/ir.json")
    ir_dict = load_ir_from_commit("main", ".protean/ir.json")
    ir_dict = load_ir_from_commit("v0.15.0", ".protean/ir.json")
"""

from __future__ import annotations

import json
import subprocess
from pathlib import PurePosixPath
from typing import Any, cast

__all__ = ["GitError", "load_ir_from_commit"]


class GitError(Exception):
    """Raised when a git operation fails."""


def load_ir_from_commit(
    commit: str,
    path: str = ".protean/ir.json",
) -> dict[str, Any]:
    """Load an IR JSON file from a specific git commit.

    Reads the file with ``git show <commit>:<path>``, without checking out the
    commit.

    Args:
        commit: A git commit reference: branch name, tag, SHA, ``HEAD``,
            ``HEAD~1``, and so on.
        path: Path to the IR file relative to the repository root.

    Returns:
        The parsed IR dict.

    Raises:
        GitError: If git is not on ``PATH``, the git command fails (unknown
            commit, file missing at that commit, not a git repository), or
            the file is not UTF-8 text, not valid JSON, or not a JSON object.
    """
    # Normalize to forward slashes — git show always expects POSIX paths.
    posix_path = PurePosixPath(path).as_posix()
    ref = f"{commit}:{posix_path}"
    try:
        result = subprocess.run(
            ["git", "show", ref],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
    except FileNotFoundError as exc:
        raise GitError("git is not installed or not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        raise GitError(
            f"Failed to load '{posix_path}' from commit '{commit}': {stderr}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise GitError(
            f"'{posix_path}' at commit '{commit}' is not UTF-8 text: {exc}"
        ) from exc

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GitError(
            f"Invalid JSON in '{posix_path}' at commit '{commit}': {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise GitError(f"'{posix_path}' at commit '{commit}' is not a JSON object")

    # json.loads is typed to return Any; the check above pins it to a dict.
    return cast("dict[str, Any]", data)
