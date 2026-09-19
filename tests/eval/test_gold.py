"""The gold builds from the spec, verifies green, and self-scores 1.0.

This is the scorer's own oracle check: the deterministic path is built from
``protean add``, so scoring its IR against itself must be a perfect 1.0. The gold
is scaffolded once per module (it shells ``protean new`` + ``protean add``),
which keeps the run quick.
"""

from __future__ import annotations

import pytest

from tests.eval.gold import GoldProject, _run_protean, build_gold
from tests.eval.scoring import _context_map, score, score_boundary
from tests.eval.spec import read_spec
from tests.eval.tools import run_verify

pytestmark = pytest.mark.no_test_domain


def test_run_protean_raises_with_the_stderr_tail_on_a_nonzero_exit() -> None:
    """A failed protean command is a real error, not a low score: ``_run_protean``
    raises ``RuntimeError`` and carries the exit code so the failure is
    diagnosable. Uses a bogus subcommand so the exit is non-zero without a
    scaffold."""
    with pytest.raises(RuntimeError, match="failed"):
        _run_protean(["definitely-not-a-protean-subcommand"])


@pytest.fixture(scope="module")
def gold(tmp_path_factory: pytest.TempPathFactory) -> GoldProject:
    dest = tmp_path_factory.mktemp("gold")
    return build_gold(read_spec("place_order"), dest)


def test_gold_project_lands_under_the_dest(gold: GoldProject) -> None:
    assert gold.root.is_dir()
    assert (gold.root / "src" / "place_order" / "domain.py").is_file()


def test_gold_ir_carries_the_scored_elements(gold: GoldProject) -> None:
    """The gold IR is non-empty and carries the Order aggregate and its slice, so
    the 1.0 self-score below is over real elements, not a vacuous empty set."""
    result = score(gold.ir, gold.ir)
    # Order aggregate + its two fields (id, name) + the scaffold's CreateOrder
    # command + OrderCreated event + OrderCommandHandler = 6 scored elements. A
    # regained example slice would push this past 6 and be caught here.
    assert result.expected == 6
    assert ("aggregate", "Order") in result.recovered
    assert ("command", "CreateOrder") in result.recovered
    assert ("event", "OrderCreated") in result.recovered
    assert ("handler", "OrderCommandHandler") in result.recovered


def test_gold_self_scores_one(gold: GoldProject) -> None:
    result = score(gold.ir, gold.ir)
    assert result.score == 1.0
    assert result.missing == ()


def test_gold_verifies_green(gold: GoldProject) -> None:
    assert run_verify(gold.root)["ok"] is True


def test_place_order_gold_self_scores_placement_and_context(
    gold: GoldProject,
) -> None:
    """The single-aggregate gold self-scores placement 1.0 over its real slice,
    and its one aggregate is not penalized on context."""
    result = score_boundary(gold.ir, gold.ir)
    assert result.placement == 1.0
    assert result.placement_expected >= 1
    assert ("command", "CreateOrder") in result.placed
    assert result.context == 1.0
    assert result.context_expected == 1


@pytest.fixture(scope="module")
def two_aggregate_gold(tmp_path_factory: pytest.TempPathFactory) -> GoldProject:
    dest = tmp_path_factory.mktemp("gold_two_aggregate")
    return build_gold(read_spec("order_and_customer"), dest)


@pytest.fixture(scope="module")
def two_context_gold(tmp_path_factory: pytest.TempPathFactory) -> GoldProject:
    dest = tmp_path_factory.mktemp("gold_two_context")
    return build_gold(read_spec("order_and_payment"), dest)


def test_two_aggregate_gold_self_scores_placement(
    two_aggregate_gold: GoldProject,
) -> None:
    """The placement task's gold: each aggregate's create command, event, and
    handler lands under that aggregate, so the gold self-scores placement 1.0 over
    real elements (both aggregates' slices are recovered, not a vacuous set)."""
    result = score_boundary(two_aggregate_gold.ir, two_aggregate_gold.ir)
    assert result.placement == 1.0
    assert result.misplaced == ()
    # Two aggregates, each with a create command, a created event, and a command
    # handler: six per-cluster placement elements.
    assert result.placement_expected == 6
    assert ("command", "CreateOrder") in result.placed
    assert ("command", "CreateCustomer") in result.placed


def test_two_aggregate_gold_verifies_green(
    two_aggregate_gold: GoldProject,
) -> None:
    assert run_verify(two_aggregate_gold.root)["ok"] is True


def test_two_context_gold_self_scores_context(
    two_context_gold: GoldProject,
) -> None:
    """The context task's gold: the Order and Payment aggregates land in the
    ``order`` and ``payment`` context modules the spec declares, so the gold
    self-scores context 1.0 over both recovered aggregates."""
    spec = read_spec("order_and_payment")
    assert spec.contexts == (("order", ("Order",)), ("payment", ("Payment",)))
    # The two aggregates must land in two distinct context segments, or a self-score
    # of 1.0 would say nothing: a single-context collapse (both under one segment)
    # scores context 1.0 against itself just the same. Guard the "two-context" shape
    # so a future scaffold layout change that merged the segments is caught here.
    assert len(set().union(*_context_map(two_context_gold.ir).values())) == 2
    result = score_boundary(two_context_gold.ir, two_context_gold.ir)
    assert result.context == 1.0
    assert result.context_expected == 2
    assert set(result.contexts_matched) == {"Order", "Payment"}
    # Placement also holds for the two-context gold: each slice is under its own
    # aggregate.
    assert result.placement == 1.0


def test_two_context_gold_verifies_green(
    two_context_gold: GoldProject,
) -> None:
    assert run_verify(two_context_gold.root)["ok"] is True
