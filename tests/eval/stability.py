"""Measure how stable an approach is when a task is run more than once.

The comparison eval scores each approach once (:mod:`tests.eval.compare`). This
module layers a run-to-run stability metric on top: run a task ``n`` times for
one approach and report two things per approach.

- **How often the produced structure is the same.** Each run reduces to the set
  of IR element signatures it built (the same set the rubric scores on, from
  :func:`tests.eval.scoring.element_signatures`). Two runs are the same result
  when their signature sets are equal. Signatures match on class name, not on
  fully-qualified name (see :mod:`tests.eval.scoring`), so the structural axis is
  class-name equality. The identical-result rate is the modal fraction: the size
  of the largest group of runs sharing one signature set, divided by the run
  count. It reads ``1.0`` for a perfectly stable approach and needs no reference
  run.
- **How the correctness score spreads.** The mean, population standard deviation,
  min, and max of the correctness score across the runs. A stable approach has a
  standard deviation of exactly ``0.0``.

The two axes are independent: the identical-result rate reads the signature set,
the spread reads the score. Under today's scorer the score is a function of the
signature set against a fixed gold, so the two move together. They are computed
independently, so a later scorer that adds noise to the score would leave the
structural rate unchanged.

Stability is measured on the live-model lane. Transcript replay is deterministic
by construction, so the context-driven variance number comes from the opt-in
live lane; the deterministic path reports zero variance as its determinism guard.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tests.eval.drivers import Driver
from tests.eval.gold import build_gold
from tests.eval.ir_probe import build_ir
from tests.eval.runner import build_pack_prompt, read_task, run
from tests.eval.scoring import Signature, element_signatures, score
from tests.eval.spec import TaskSpec
from tests.eval.workspace import Workspace

__all__ = [
    "DEFAULT_RUNS",
    "RunOutcome",
    "Stability",
    "context_driven_outcome",
    "deterministic_outcome",
    "measure_stability",
    "run_stability",
]

# The run count the live lane measures variance over. A config knob: pass ``n``
# to :func:`run_stability` to override it. Ten runs is enough to see a model's
# run-to-run spread without turning the live lane into a long job.
DEFAULT_RUNS = 10


@dataclass(frozen=True)
class RunOutcome:
    """One run reduced to its structure and its score.

    ``signatures`` is the set of IR element signatures the run produced, held as
    a ``frozenset`` so distinct outcomes are hashable and countable. ``score`` is
    the run's correctness against the gold, in ``[0, 1]``.
    """

    signatures: frozenset[Signature]
    score: float


@dataclass(frozen=True)
class Stability:
    """An approach's run-to-run stability over ``runs`` runs.

    ``identical_result_rate`` is the modal fraction: the share of runs that
    produced the most common signature set, ``1.0`` when every run built the same
    structure. ``distinct_results`` is how many different signature sets appeared.
    ``score_mean``, ``score_stdev`` (population standard deviation), ``score_min``,
    and ``score_max`` describe the correctness score's spread; ``score_stdev`` is
    ``0.0`` for a single run and for runs that all scored the same.
    """

    runs: int
    identical_result_rate: float
    distinct_results: int
    score_mean: float
    score_stdev: float
    score_min: float
    score_max: float


def measure_stability(outcomes: Sequence[RunOutcome]) -> Stability:
    """Aggregate *outcomes* into a :class:`Stability`.

    Groups the runs by their signature set: ``identical_result_rate`` is the
    largest group's size over the run count, and ``distinct_results`` is the
    number of groups. The score fields are the mean, population standard
    deviation, min, and max of the run scores. Population standard deviation
    (:func:`statistics.pstdev`) is defined for one run, so a stable approach
    reports exactly ``0.0`` for it.

    Raises :class:`ValueError` on empty *outcomes*, since zero runs is a caller
    error.
    """
    if not outcomes:
        raise ValueError("measure_stability needs at least one run outcome")

    runs = len(outcomes)
    group_sizes: dict[frozenset[Signature], int] = {}
    for outcome in outcomes:
        group_sizes[outcome.signatures] = group_sizes.get(outcome.signatures, 0) + 1

    scores = [outcome.score for outcome in outcomes]
    return Stability(
        runs=runs,
        identical_result_rate=max(group_sizes.values()) / runs,
        distinct_results=len(group_sizes),
        score_mean=statistics.fmean(scores),
        score_stdev=statistics.pstdev(scores),
        score_min=min(scores),
        score_max=max(scores),
    )


def run_stability(
    run_once: Callable[[], RunOutcome], *, n: int = DEFAULT_RUNS
) -> Stability:
    """Call *run_once* ``n`` times and aggregate the outcomes into a
    :class:`Stability`.

    *run_once* is the injection seam: the deterministic guard, the live
    context-driven test, and a stub all drive stability through the same call.
    Raises :class:`ValueError` when *n* is less than one, since there is nothing
    to measure.
    """
    if n < 1:
        raise ValueError(f"run_stability needs n >= 1, got {n}")
    return measure_stability([run_once() for _ in range(n)])


def deterministic_outcome(spec: TaskSpec, dest: Path | str) -> RunOutcome:
    """Build *spec*'s gold under *dest* and reduce it to a :class:`RunOutcome`.

    The deterministic approach scores its own IR against itself, which is ``1.0``
    by construction, and carries one fixed signature set. Re-running it through
    :func:`run_stability` is a real determinism guard: it re-scaffolds the gold
    each call, so drift in the scaffold's signatures shows up as more than one
    distinct result. The score cannot move here (each run scores its own gold),
    so the guard rests on the structural axis.
    """
    gold = build_gold(spec, dest)
    correctness = score(gold.ir, gold.ir)
    return RunOutcome(
        signatures=frozenset(element_signatures(gold.ir)),
        score=correctness.score,
    )


def context_driven_outcome(
    task_id: str,
    gold_ir: dict[str, object],
    *,
    driver: Driver,
    workspace: Workspace,
) -> RunOutcome:
    """Drive *task_id* through *driver* into *workspace* and score it.

    Runs the task's prompt through the live driver the same way the recorder
    does, reads the produced project's IR, and scores it against *gold_ir*. The
    returned outcome carries the produced signature set and the correctness
    score, the two stability axes. This helper is exercised from the live lane
    and from a scripted-driver unit test; the CI variance number comes from the
    deterministic guard.
    """
    # The run writes the project into the workspace; its RunResult is not needed
    # here, the IR is read back from the tree the run produced.
    run(
        read_task(task_id),
        driver,
        workspace=workspace,
        system_prompt=build_pack_prompt(),
    )
    produced_ir = build_ir(workspace.root)
    correctness = score(produced_ir, gold_ir)
    return RunOutcome(
        signatures=frozenset(element_signatures(produced_ir)),
        score=correctness.score,
    )
