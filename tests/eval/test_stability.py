"""Run-to-run stability: the aggregation, a spread over an injected stub, and
the deterministic zero-variance guard.

The aggregation tests pin ``measure_stability`` against hand-built outcomes and a
``statistics.pstdev`` reference. The stub test drives ``run_stability`` through an
injected non-deterministic ``run_once`` to check the spread over a known
sequence. The determinism guard re-scaffolds the deterministic approach and
asserts one distinct structure, so drift in the gold's signatures would fail it.
"""

from __future__ import annotations

import itertools
import statistics

import pytest

from tests.eval.drivers import ReplayDriver
from tests.eval.scoring import Signature
from tests.eval.spec import read_spec
from tests.eval.stability import (
    RunOutcome,
    Stability,
    context_driven_outcome,
    deterministic_outcome,
    measure_stability,
    run_stability,
)
from tests.eval.test_runner import GREEN_DOMAIN
from tests.eval.transcript import ToolCall, Turn
from tests.eval.workspace import Workspace

pytestmark = pytest.mark.no_test_domain

# Three distinct signature sets to build outcomes from. B carries A's aggregate
# plus a command and C a different aggregate, so no two of them are equal as sets.
_SIGS_A: frozenset[Signature] = frozenset({("aggregate", "Order")})
_SIGS_B: frozenset[Signature] = frozenset(
    {("aggregate", "Order"), ("command", "PlaceOrder")}
)
_SIGS_C: frozenset[Signature] = frozenset({("aggregate", "Cart")})


class TestMeasureStability:
    """The pure aggregation over a list of outcomes."""

    def test_single_outcome_is_perfectly_stable(self) -> None:
        stability = measure_stability([RunOutcome(_SIGS_A, 0.7)])
        assert stability.runs == 1
        assert stability.distinct_results == 1
        assert stability.identical_result_rate == 1.0
        assert stability.score_stdev == 0.0
        assert stability.score_mean == 0.7
        assert stability.score_min == 0.7
        assert stability.score_max == 0.7

    def test_all_identical_outcomes_read_zero_variance(self) -> None:
        outcomes = [RunOutcome(_SIGS_A, 1.0) for _ in range(5)]
        stability = measure_stability(outcomes)
        assert stability.runs == 5
        assert stability.distinct_results == 1
        assert stability.identical_result_rate == 1.0
        assert stability.score_stdev == 0.0

    def test_even_split_of_two_structures_reads_half(self) -> None:
        outcomes = [
            RunOutcome(_SIGS_A, 1.0),
            RunOutcome(_SIGS_B, 0.5),
            RunOutcome(_SIGS_A, 1.0),
            RunOutcome(_SIGS_B, 0.5),
        ]
        stability = measure_stability(outcomes)
        assert stability.distinct_results == 2
        # Two groups of two: the modal fraction is 2/4.
        assert stability.identical_result_rate == 0.5

    def test_three_structures_report_the_plurality_and_the_distinct_count(
        self,
    ) -> None:
        """A 2/2/1 split over three distinct signature sets: the modal fraction
        is the largest group (two of five) even though no group holds a
        majority, and every distinct structure is counted."""
        outcomes = [
            RunOutcome(_SIGS_A, 1.0),
            RunOutcome(_SIGS_A, 1.0),
            RunOutcome(_SIGS_B, 0.5),
            RunOutcome(_SIGS_B, 0.5),
            RunOutcome(_SIGS_C, 0.0),
        ]
        stability = measure_stability(outcomes)
        assert stability.runs == 5
        assert stability.distinct_results == 3
        assert stability.identical_result_rate == pytest.approx(0.4)

    def test_identical_structure_differing_scores_splits_the_two_axes(self) -> None:
        """Identical signature sets carrying different scores count as one
        structural result, and the score spread stays non-zero. The
        identical-result rate reads the signature set; the spread reads the
        score."""
        outcomes = [RunOutcome(_SIGS_A, 1.0), RunOutcome(_SIGS_A, 0.8)]
        stability = measure_stability(outcomes)
        # One structure, so the structural axis is perfectly stable.
        assert stability.distinct_results == 1
        assert stability.identical_result_rate == 1.0
        # The score axis is not: pstdev of [1.0, 0.8] is > 0.
        assert stability.score_stdev == pytest.approx(statistics.pstdev([1.0, 0.8]))
        assert stability.score_stdev > 0.0
        assert stability.score_min == 0.8
        assert stability.score_max == 1.0
        assert stability.score_mean == pytest.approx(0.9)

    def test_empty_outcomes_is_a_caller_error(self) -> None:
        with pytest.raises(ValueError, match="at least one run outcome"):
            measure_stability([])


class TestRunStability:
    """``run_stability`` drives ``run_once`` n times and aggregates."""

    def test_injected_nondeterministic_stub_reports_the_expected_spread(self) -> None:
        """An injected ``run_once`` that cycles through outcomes with two
        distinct structures and known scores reports the modal fraction, the
        distinct count, and the exact score spread."""
        sequence = [
            RunOutcome(_SIGS_A, 1.0),
            RunOutcome(_SIGS_B, 0.5),
            RunOutcome(_SIGS_A, 1.0),
            RunOutcome(_SIGS_A, 1.0),
        ]
        scores = [outcome.score for outcome in sequence]
        run_once = iter(sequence).__next__

        stability = run_stability(run_once, n=len(sequence))

        assert stability.runs == len(sequence)
        # _SIGS_A appears three of four times, _SIGS_B once.
        assert stability.distinct_results == 2
        assert stability.identical_result_rate == 0.75
        assert stability.score_mean == pytest.approx(statistics.fmean(scores))
        assert stability.score_stdev == pytest.approx(statistics.pstdev(scores))
        assert stability.score_min == 0.5
        assert stability.score_max == 1.0

    def test_n_below_one_is_a_caller_error(self) -> None:
        with pytest.raises(ValueError, match="n >= 1"):
            run_stability(lambda: RunOutcome(_SIGS_A, 1.0), n=0)

    def test_run_once_is_called_exactly_n_times(self) -> None:
        counter = itertools.count()

        def run_once() -> RunOutcome:
            next(counter)
            return RunOutcome(_SIGS_A, 1.0)

        run_stability(run_once, n=3)
        assert next(counter) == 3


def test_deterministic_approach_reports_zero_variance(tmp_path) -> None:
    """The deterministic approach, re-scaffolded and re-scored through
    ``run_stability``, produces one distinct structure and exactly zero score
    spread. This is a real determinism regression guard: each run is a fresh
    ``build_gold``, so drift in the scaffold's signatures shows up as more than
    one distinct result. The score cannot move here (each run scores its own
    gold), so the guard rests on the structural axis.

    ``n`` is small on purpose: two real scaffolds are enough to catch drift, and
    the ten-run default belongs to the live lane, not core CI."""
    spec = read_spec("place_order")
    counter = itertools.count()

    def run_once() -> RunOutcome:
        dest = tmp_path / f"gold-{next(counter)}"
        dest.mkdir()
        return deterministic_outcome(spec, dest)

    stability = run_stability(run_once, n=2)

    assert isinstance(stability, Stability)
    assert stability.runs == 2
    assert stability.distinct_results == 1
    assert stability.identical_result_rate == 1.0
    assert stability.score_stdev == 0.0
    assert stability.score_mean == 1.0
    assert stability.score_min == 1.0
    assert stability.score_max == 1.0


# A hand-built gold IR for the context-driven test below: an Order aggregate with
# two fields plus a CreateOrder command. GREEN_DOMAIN builds Order (with
# customer_name, not total) and a PlaceOrder command, so a run against this gold
# recovers the Order aggregate and the customer_name field (2 of 4 signatures),
# and misses CreateOrder and the total field.
_GOLD_IR = {
    "elements": {
        "AGGREGATE": ["gold.order.Order"],
        "COMMAND": ["gold.order.CreateOrder"],
    },
    "clusters": {
        "gold.order.Order": {
            "aggregate": {
                "name": "Order",
                "fqn": "gold.order.Order",
                "fields": {"customer_name": {}, "total": {}},
            }
        }
    },
}


def test_context_driven_outcome_reads_signatures_and_scores(tmp_path) -> None:
    """``context_driven_outcome`` drives a scripted (no-model) run that writes a
    real domain, reads back its IR, and scores it against the gold. This gives
    the context-driven half of the metric core-CI coverage without a live model:
    a ``ReplayDriver`` stands in for the model and writes a known project, so the
    produced signature set and the score are both pinned.

    The run writes ``GREEN_DOMAIN`` (an Order aggregate and a PlaceOrder command)
    and scores it against ``_GOLD_IR`` (Order plus a CreateOrder command and a
    total field the run never builds), so the run recovers the Order aggregate
    and the customer_name field: 2 of the gold's 4 signatures."""
    turns = (
        Turn(
            "write the domain",
            (ToolCall("write_file", {"path": "domain.py", "content": GREEN_DOMAIN}),),
        ),
        Turn("done", ()),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    outcome = context_driven_outcome(
        "place_order",
        _GOLD_IR,
        driver=ReplayDriver(turns),
        workspace=Workspace(run_dir),
    )

    assert isinstance(outcome, RunOutcome)
    # The signature axis reads what the run actually produced: the Order
    # aggregate and the PlaceOrder command GREEN_DOMAIN builds.
    assert ("aggregate", "Order") in outcome.signatures
    assert ("command", "PlaceOrder") in outcome.signatures
    # The gold's CreateOrder command is not in the produced structure.
    assert ("command", "CreateOrder") not in outcome.signatures
    # The score axis: 2 of the gold's 4 signatures recovered.
    assert outcome.score == pytest.approx(0.5)
