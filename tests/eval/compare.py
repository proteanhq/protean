"""Run both approaches over a task and report each one's verify-green + score.

For one task the comparison runs two approaches and reports, per approach, a
``verify``-green bool and a correctness score against the same gold:

- **Approach A (deterministic).** Build the gold project from the spec, run
  ``protean verify`` over it, and score its IR against itself. This is 1.0 by
  construction and is the scorer's own oracle check.
- **Approach B (context-driven).** Replay the task's committed transcript into a
  workspace with no model, read the produced project's IR, and score it against
  the gold. Its verify-green is the verdict the replayed ``run_verify`` returned.

The score is the base per-element rubric (:mod:`tests.eval.scoring`). Approach
B's distance from 1.0 is the intended signal: the deterministic scaffold's canned
command and event names differ from the task's own, so a context-driven project
recovers some but not all of the gold's elements.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from protean.dx.pack import PACK_VERSION
from tests.eval.gold import build_gold
from tests.eval.ir_probe import build_ir
from tests.eval.runner import eval_root, replay
from tests.eval.scoring import Correctness, score
from tests.eval.spec import read_spec
from tests.eval.tools import run_verify
from tests.eval.transcript import Transcript, transcript_path
from tests.eval.workspace import Workspace

__all__ = ["ApproachResult", "Comparison", "compare"]


@dataclass(frozen=True)
class ApproachResult:
    """One approach's outcome on a task: whether it verified green and its
    correctness against the gold."""

    verify_green: bool
    correctness: Correctness


@dataclass(frozen=True)
class Comparison:
    """The two approaches' results for a task, side by side."""

    task_id: str
    deterministic: ApproachResult
    context_driven: ApproachResult


def compare(task_id: str, gold_dest: Path | str, replay_dest: Path | str) -> Comparison:
    """Run Approach A and Approach B over *task_id* and report both.

    *gold_dest* and *replay_dest* are caller-owned directories (a test's temp
    dirs): the gold project lands under *gold_dest*, and the replayed
    context-driven project under *replay_dest*. The task's transcript for the
    installed ``PACK_VERSION`` must exist, or replay has nothing to run.
    """
    spec = read_spec(task_id)
    gold = build_gold(spec, gold_dest)

    deterministic = ApproachResult(
        verify_green=run_verify(gold.root)["ok"],
        correctness=score(gold.ir, gold.ir),
    )

    transcript = Transcript.load(transcript_path(eval_root(), PACK_VERSION, task_id))
    workspace = Workspace(Path(replay_dest))
    result = replay(transcript, workspace=workspace)
    produced_ir = build_ir(workspace.root)
    # The last recorded verify verdict is the produced project's verify-green;
    # a transcript that never ran verify counts as not green.
    verify_green = bool(result.verify_results) and result.verify_results[-1]["ok"]
    context_driven = ApproachResult(
        verify_green=verify_green,
        correctness=score(produced_ir, gold.ir),
    )

    return Comparison(
        task_id=task_id,
        deterministic=deterministic,
        context_driven=context_driven,
    )
