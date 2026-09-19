"""The comparison over ``place_order`` reports both approaches (AC1).

Approach A (deterministic) verifies green and scores 1.0 by construction.
Approach B (context-driven) replays the committed transcript and gets a
verify-green verdict plus a correctness score in range. The comparison is built
once per module (it scaffolds the gold and replays the transcript), which keeps
the run quick.
"""

from __future__ import annotations

import pytest

from tests.eval.compare import Comparison, compare

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


def test_deterministic_approach_is_green_and_perfect(comparison: Comparison) -> None:
    """Approach A is the oracle: verify-green and exactly 1.0."""
    assert comparison.deterministic.verify_green is True
    assert comparison.deterministic.correctness.score == 1.0
    assert comparison.deterministic.correctness.missing == ()


def test_context_driven_approach_verifies_and_scores_in_range(
    comparison: Comparison,
) -> None:
    """Approach B replays the committed transcript, verifies green, and lands a
    score in ``[0, 1]`` against the same gold. The number is asserted as a range,
    not pinned, so re-recording the transcript does not break the test."""
    b = comparison.context_driven
    assert b.verify_green is True
    assert 0.0 <= b.correctness.score <= 1.0
    # Both approaches score against the same gold, so the denominators match.
    assert b.correctness.expected == comparison.deterministic.correctness.expected
    # The task asks for an Order aggregate, which the context-driven project does
    # build, so that element is recovered regardless of the naming distance.
    assert ("aggregate", "Order") in b.correctness.recovered
