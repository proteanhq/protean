"""Run both approaches over a task and report each one's verify-green + score.

For one task the comparison runs two approaches and reports, per approach, a
``verify``-green bool and a correctness score against the same gold:

- **Approach A (deterministic).** Build the gold project from the spec, run
  ``protean verify`` over it, and score its IR against itself. This is 1.0 by
  construction and is the scorer's own oracle check.
- **Approach B (context-driven).** Replay the task's committed transcript into a
  workspace with no model, run ``protean verify`` over the tree the replay
  produced, and score its IR against the gold.

Both verdicts come from a fresh ``protean verify`` of the final project, not
from a verify the run recorded along the way: a transcript can verify green and
then write a breaking change, and the reported verdict has to describe the same
project whose IR is scored.

A replayed transcript is only scored when it still reproduces what it recorded.
:func:`compare` raises :class:`StaleTranscriptError` when the replayed tree
hashes differently than the recording, or when a re-run tool no longer answers
what the recording saw, rather than publishing a score for a stale transcript.

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
from tests.eval.runner import RunResult, eval_root, replay
from tests.eval.scoring import Correctness, score
from tests.eval.spec import read_spec
from tests.eval.tools import run_verify
from tests.eval.transcript import Transcript, transcript_path
from tests.eval.workspace import Workspace

__all__ = ["ApproachResult", "Comparison", "StaleTranscriptError", "compare"]


class StaleTranscriptError(RuntimeError):
    """A replayed transcript no longer reproduces what it recorded."""


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


def _reject_stale(transcript: Transcript, result: RunResult) -> None:
    """Raise when *result* diverges from what *transcript* recorded.

    Both of replay's staleness signals are checked. The project hash covers only
    the files the agent wrote, so a tool that now answers differently (a changed
    verify verdict, a new diagnostic code) is invisible to it; the recorded tool
    results are the second signal. Either one differing means the transcript no
    longer describes a run of today's code, and a score read off it would
    describe the recording rather than the harness.
    """
    reasons = list(result.result_divergences)
    if result.project_hash != transcript.project_hash:
        reasons.insert(
            0,
            f"replayed tree hashes to {result.project_hash}, "
            f"recorded {transcript.project_hash}",
        )
    if reasons:
        raise StaleTranscriptError(
            f"stale transcript for task {transcript.task_id!r}; re-record it "
            "by running the live lane.\n" + "\n".join(reasons)
        )


def compare(task_id: str, gold_dest: Path | str, replay_dest: Path | str) -> Comparison:
    """Run Approach A and Approach B over *task_id* and report both.

    *gold_dest* and *replay_dest* are caller-owned directories (a test's temp
    dirs): the gold project lands under *gold_dest*, and the replayed
    context-driven project under *replay_dest*. The task's transcript for the
    installed ``PACK_VERSION`` must exist, or replay has nothing to run, and it
    must replay clean or this raises :class:`StaleTranscriptError`.
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
    _reject_stale(transcript, result)
    context_driven = ApproachResult(
        verify_green=run_verify(workspace.root)["ok"],
        correctness=score(build_ir(workspace.root), gold.ir),
    )

    return Comparison(
        task_id=task_id,
        deterministic=deterministic,
        context_driven=context_driven,
    )
