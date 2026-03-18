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
from typing import Any

__all__ = ["load_ir_from_commit", "GitError"]


class GitError(Exception):
    """Raised when a git operation fails."""


def load_ir_from_commit(
    commit: str,
    path: str = ".protean/ir.json",
) -> dict[str, Any]:
    """Load an IR JSON file from a specific git commit.

    Uses ``git show <commit>:<path>`` to retrieve the file contents
    without checking out the commit.

    Parameters
    ----------
    commit:
        A git commit reference — branch name, tag, SHA, ``HEAD``,
        ``HEAD~1``, etc.
    path:
        Path to the IR file relative to the repository root.
        Defaults to ``.protean/ir.json``.

    Returns
    -------
    dict
        The parsed IR dict.

    Raises
    ------
    GitError
        If the git command fails (e.g. commit not found, file doesn't
        exist at that commit, not a git repository).
    """
    ref = f"{commit}:{path}"
    try:
        result = subprocess.run(
            ["git", "show", ref],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        raise GitError("git is not installed or not found on PATH")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip()
        raise GitError(
            f"Failed to load '{path}' from commit '{commit}': {stderr}"
        ) from exc

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GitError(f"Invalid JSON in '{path}' at commit '{commit}': {exc}") from exc
