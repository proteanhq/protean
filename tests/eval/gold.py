"""Build a task's gold project deterministically, from its spec.

The gold is the reference structure the scorer compares a produced project
against. It is built by the scaffold path the eval measures against: ``protean
new`` for the project, then one ``protean add aggregate <Name>`` per aggregate
in the spec. Because the gold's IR is read from that scaffold, the deterministic
approach scores 1.0 against it by construction, which is the scorer's own oracle
check.

``protean new`` is scaffolded with ``include_example=false`` so the gold carries
only the spec's aggregates, not the template's example slice, which the task
never asks for and which would otherwise pad the denominator the score divides
by.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.eval.discovery import stripped_env
from tests.eval.ir_probe import build_ir
from tests.eval.spec import TaskSpec

__all__ = ["GoldProject", "build_gold"]

# A ceiling on a scaffold subprocess. ``protean new`` shells copier and
# ``protean add`` writes a slice; neither runs a test suite, so a plain
# wait-with-timeout is enough.
_SCAFFOLD_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class GoldProject:
    """A built gold project: its root directory and its parsed IR.

    ``root`` lets the deterministic approach also run ``protean verify`` over the
    gold; ``ir`` is what the scorer compares a produced project against.
    """

    root: Path
    ir: dict[str, Any]


def _run_protean(args: list[str], *, cwd: Path | None = None) -> None:
    """Run ``protean <args>`` in a subprocess, raising on a non-zero exit.

    A failed scaffold is a real error, not a low score: the gold is the oracle,
    so it must build cleanly or the run cannot proceed. The stderr tail rides
    along in the raised message so the failure is diagnosable.
    """
    process = subprocess.run(
        [sys.executable, "-m", "protean", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        errors="replace",
        env=stripped_env(),
        timeout=_SCAFFOLD_TIMEOUT_SECONDS,
        check=False,
    )
    if process.returncode != 0:
        tail = " / ".join(process.stderr.strip().splitlines()[-5:])
        raise RuntimeError(
            f"protean {' '.join(args)} failed (exit {process.returncode}): {tail}"
        )


def build_gold(spec: TaskSpec, dest: Path | str) -> GoldProject:
    """Scaffold *spec*'s gold project under *dest* and read back its IR.

    *dest* is a caller-owned directory (a test's temp dir); the project lands at
    ``dest/<project_name>`` and is left in place so the caller can verify it. The
    build is: ``protean new`` with the example slice off, then one ``protean add
    aggregate <Name>`` per aggregate in the spec.
    """
    dest_path = Path(dest)
    _run_protean(
        [
            "new",
            spec.project_name,
            "-o",
            str(dest_path),
            "--defaults",
            "--skip-setup",
            "--data",
            "include_example=false",
        ]
    )
    root = dest_path / spec.project_name
    for aggregate in spec.aggregates:
        _run_protean(["add", "aggregate", aggregate, "-p", str(root)])
    return GoldProject(root=root, ir=build_ir(root))
