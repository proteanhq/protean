"""A git repository holding a committed IR, for tests of the git-based IR commands.

Use it with the ``isolated_git`` fixture, which keeps the caller's git
environment and config out of these commands.
"""

import json
import subprocess
from pathlib import Path
from typing import Any


def commit_ir(repo: Path, ir: Any, ir_dir: str = ".protean") -> None:
    """Create a git repository at *repo* holding *ir* committed as
    ``<ir_dir>/ir.json``."""
    (repo / ir_dir).mkdir(parents=True, exist_ok=True)
    (repo / ir_dir / "ir.json").write_text(json.dumps(ir), encoding="utf-8")
    for command in (
        ["git", "init", "-q"],
        ["git", "add", f"{ir_dir}/ir.json"],
        ["git", "commit", "-q", "-m", "baseline"],
    ):
        subprocess.run(command, cwd=repo, capture_output=True, check=True)
