"""The comparison over ``place_order`` reports both approaches (AC1).

Approach A (deterministic) verifies green and scores 1.0 by construction.
Approach B (context-driven) replays the committed transcript and gets a
verify-green verdict plus a correctness score in range. The comparison is built
once per module (it scaffolds the gold and replays the transcript), which keeps
the run quick.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from protean.dx.pack import PACK_VERSION
from tests.eval import compare as compare_module
from tests.eval.compare import (
    Comparison,
    StaleTranscriptError,
    _reject_stale,
    compare,
)
from tests.eval.gold import GoldProject
from tests.eval.runner import RunResult, eval_root
from tests.eval.spec import TaskSpec
from tests.eval.transcript import Transcript, transcript_path
from tests.eval.workspace import Workspace

pytestmark = pytest.mark.no_test_domain


@pytest.fixture(scope="module")
def comparison(tmp_path_factory: pytest.TempPathFactory) -> Comparison:
    gold_dest = tmp_path_factory.mktemp("gold")
    replay_dest = tmp_path_factory.mktemp("replay")
    return compare("place_order", gold_dest, replay_dest)


def test_reports_both_approaches(comparison: Comparison) -> None:
    assert comparison.task_id == "place_order"
    for approach in (comparison.deterministic, comparison.context_driven):
        assert isinstance(approach.verify_green, bool)
        assert 0.0 <= approach.correctness.score <= 1.0
        assert approach.correctness.expected >= 1
        # AC1: every task run through the harness reports a boundary/aggregate
        # recovery score, in range alongside the base correctness.
        assert 0.0 <= approach.recovery.placement <= 1.0
        assert 0.0 <= approach.recovery.context <= 1.0


def test_deterministic_approach_is_green_and_perfect(comparison: Comparison) -> None:
    """Approach A is the oracle: verify-green and exactly 1.0, on both the base
    rubric and the boundary/aggregate recovery layer."""
    assert comparison.deterministic.verify_green is True
    assert comparison.deterministic.correctness.score == 1.0
    assert comparison.deterministic.correctness.missing == ()
    # The gold scored against itself places every element and matches its own
    # context, so recovery is 1.0 by construction, and over real elements.
    assert comparison.deterministic.recovery.placement == 1.0
    assert comparison.deterministic.recovery.context == 1.0
    assert comparison.deterministic.recovery.placement_expected >= 1


def test_context_driven_approach_verifies_and_scores_in_range(
    comparison: Comparison,
) -> None:
    """Approach B replays the committed transcript, verifies green, and lands a
    graded score strictly between 0 and 1 against the same gold. The exact number
    is not pinned, so re-recording the transcript does not break the test, but the
    graded-score decision is: a scorer that reported full recovery would fail the
    upper bound, and one that recovered nothing would fail the lower bound and the
    recovered/missing pins."""
    b = comparison.context_driven
    assert b.verify_green is True
    # The graded-score decision: B is a near-miss, so it must land strictly below
    # the deterministic 1.0 and strictly above 0. A binary match would collapse a
    # near-miss and a total miss; this is the signal the whole comparison exists
    # for, so pin it, not just the [0, 1] range.
    assert 0.0 < b.correctness.score < 1.0
    # Both approaches score against the same gold, so the denominators match.
    assert b.correctness.expected == comparison.deterministic.correctness.expected
    # The task asks for an Order aggregate, which the context-driven project does
    # build, so that element is recovered regardless of the naming distance.
    assert ("aggregate", "Order") in b.correctness.recovered
    # The gold carries the `add` scaffold's canned `CreateOrder` command, which
    # the task-faithful project never builds, so it is a known-missing element.
    # Pinning it defends the graded score against a scorer that reports it
    # recovered.
    assert ("command", "CreateOrder") in b.correctness.missing


class TestStalenessGuard:
    """A transcript that no longer reproduces its recording is not scored."""

    @staticmethod
    def _transcript() -> Transcript:
        return Transcript.load(
            transcript_path(eval_root(), PACK_VERSION, "place_order")
        )

    def test_a_clean_replay_passes(self) -> None:
        transcript = self._transcript()
        result = RunResult(turns=(), project_hash=transcript.project_hash)
        _reject_stale(transcript, result)

    def test_a_different_project_hash_is_rejected(self) -> None:
        """The recorded turns no longer land the recorded tree, so the project
        being scored is not the one the transcript describes."""
        transcript = self._transcript()
        result = RunResult(turns=(), project_hash="deadbeef")
        with pytest.raises(StaleTranscriptError, match="deadbeef"):
            _reject_stale(transcript, result)

    def test_a_tool_result_divergence_is_rejected(self) -> None:
        """The hash covers only the files the agent wrote, so a tool answering
        differently is the second staleness signal and is rejected on its own."""
        transcript = self._transcript()
        result = RunResult(
            turns=(),
            project_hash=transcript.project_hash,
            result_divergences=(
                "turn 0 call 0 (run_verify): recorded X, recomputed Y",
            ),
        )
        with pytest.raises(StaleTranscriptError, match="run_verify"):
            _reject_stale(transcript, result)


def test_a_stale_replay_is_rejected_before_scoring(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``compare`` raises rather than publishing a score for a stale transcript,
    and it raises before the produced IR is ever read."""
    gold_root = tmp_path / "gold"
    gold_root.mkdir()
    replay_dest = tmp_path / "replay"
    replay_dest.mkdir()
    monkeypatch.setattr(
        compare_module,
        "build_gold",
        lambda spec, dest: GoldProject(root=gold_root, ir={}),
    )
    monkeypatch.setattr(
        compare_module,
        "replay",
        lambda transcript, *, workspace: RunResult(turns=(), project_hash="deadbeef"),
    )
    monkeypatch.setattr(
        compare_module,
        "build_ir",
        lambda root: pytest.fail("the produced IR was read for a stale transcript"),
    )
    with pytest.raises(StaleTranscriptError):
        compare("place_order", tmp_path / "gold_dest", replay_dest)


def test_context_driven_verify_green_describes_the_final_tree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The reported verdict is a fresh verify of the tree the replay produced,
    not the last verify the transcript happened to record. A run that verified
    green and then broke the project is not green."""
    gold_root = tmp_path / "gold"
    gold_root.mkdir()
    replay_dest = tmp_path / "replay"
    replay_dest.mkdir()
    monkeypatch.setattr(
        compare_module,
        "build_gold",
        lambda spec, dest: GoldProject(root=gold_root, ir={}),
    )

    def fake_replay(transcript: Transcript, *, workspace: Workspace) -> RunResult:
        """A clean replay whose last recorded verify was green, into a workspace
        holding no project at all."""
        return RunResult(
            turns=(),
            project_hash=transcript.project_hash,
            verify_results=[
                {
                    "ok": True,
                    "verdict": "pass",
                    "counts": {"errors": 0, "warnings": 0, "infos": 0},
                    "codes": [],
                    "errors": [],
                    "exit_code": 0,
                }
            ],
        )

    monkeypatch.setattr(compare_module, "replay", fake_replay)

    comparison = compare("place_order", tmp_path / "gold_dest", replay_dest)

    assert comparison.context_driven.verify_green is False


def _context_ir(package: str, placement: dict[str, str]) -> dict[str, Any]:
    """A minimal IR putting each aggregate in the context module named for it.

    *placement* maps an aggregate class name to its context segment, which is all
    the context score reads: the aggregate's package-relative first module
    segment.
    """
    fqns = {
        aggregate: f"{package}.{context}.aggregate.{aggregate}"
        for aggregate, context in placement.items()
    }
    return {
        "elements": {"AGGREGATE": sorted(fqns.values())},
        "clusters": {
            fqns[aggregate]: {
                "aggregate": {
                    "name": aggregate,
                    "fqn": fqns[aggregate],
                    "module": f"{package}.{context}.aggregate",
                    "fields": {},
                }
            }
            for aggregate, context in placement.items()
        },
    }


def test_the_task_contexts_are_scored_against_the_declaration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A task that declares a bounded-context grouping has both approaches scored
    against it. A context-driven project that collapses the two contexts into one
    scores below 1.0; without the declaration reaching the scorer, every recovered
    aggregate would match whatever module it landed in and report 1.0."""
    replay_dest = tmp_path / "replay"
    replay_dest.mkdir()
    spec = TaskSpec(
        task_id="place_order",
        project_name="shop",
        aggregates=("Order", "Payment"),
        contexts=(("order", ("Order",)), ("payment", ("Payment",))),
    )
    gold_ir = _context_ir("gold", {"Order": "order", "Payment": "payment"})
    # The collapse: both aggregates written into the one `order` context.
    produced_ir = _context_ir("produced", {"Order": "order", "Payment": "order"})
    monkeypatch.setattr(compare_module, "read_spec", lambda task_id: spec)
    monkeypatch.setattr(
        compare_module,
        "build_gold",
        lambda spec, dest: GoldProject(root=tmp_path / "gold", ir=gold_ir),
    )
    monkeypatch.setattr(
        compare_module,
        "replay",
        lambda transcript, *, workspace: RunResult(
            turns=(), project_hash=transcript.project_hash
        ),
    )
    monkeypatch.setattr(compare_module, "build_ir", lambda root: produced_ir)
    monkeypatch.setattr(compare_module, "run_verify", lambda root: {"ok": True})

    comparison = compare("place_order", tmp_path / "gold_dest", replay_dest)

    b = comparison.context_driven
    assert b.recovery.context == pytest.approx(1 / 2)
    assert b.recovery.contexts_mismatched == ("Payment",)
    assert b.recovery.contexts_matched == ("Order",)
    # Approach A is the oracle: the gold sits where the spec declares, over both
    # declared contexts rather than a vacuous denominator.
    assert comparison.deterministic.recovery.context == 1.0
    assert comparison.deterministic.recovery.context_expected == 2
