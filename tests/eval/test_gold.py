"""The gold builds from the spec, verifies green, and self-scores 1.0.

This is the scorer's own oracle check: the deterministic path is built from
``protean add``, so scoring its IR against itself must be a perfect 1.0. The gold
is scaffolded once per module (it shells ``protean new`` + ``protean add``),
which keeps the run quick.
"""

from __future__ import annotations

import pytest

from tests.eval.gold import GoldProject, _run_protean, build_gold
from tests.eval.scoring import score
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
