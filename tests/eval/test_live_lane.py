"""The live lane: drive each task through a real model and record its transcript.

This lane is opt-in and maintainer-side. It skips unless a live driver is
configured through ``PROTEAN_EVAL_LIVE_DRIVER`` (see ``tests/eval/README.md``),
so core CI never needs model access. Selecting it explicitly, and recording:

    PROTEAN_EVAL_LIVE_DRIVER='my_driver:make_driver' pytest tests/eval -m live
"""

from __future__ import annotations

import itertools
import os
from pathlib import Path

import pytest

from tests.eval.drivers import LIVE_DRIVER_ENV_VAR, resolve_live_driver
from tests.eval.gold import build_gold
from tests.eval.runner import build_pack_prompt, eval_root, record, replay
from tests.eval.spec import read_spec
from tests.eval.stability import DEFAULT_RUNS, context_driven_outcome, run_stability
from tests.eval.tools import TOOL_SPECS, run_verify
from tests.eval.transcript import TASK_FILE, TASKS_DIRNAME
from tests.eval.workspace import Workspace

pytestmark = [pytest.mark.live, pytest.mark.no_test_domain]


def _task_ids() -> list[str]:
    tasks_dir = eval_root() / TASKS_DIRNAME
    if not tasks_dir.is_dir():
        return []
    return sorted(
        child.name for child in tasks_dir.iterdir() if (child / TASK_FILE).is_file()
    )


@pytest.mark.parametrize("task_id", _task_ids())
def test_live_lane_records_a_replayable_green_transcript(
    task_id: str, tmp_path: Path
) -> None:
    """Drive a task through the live model, record the run, and confirm the
    recorded transcript replays deterministically and verifies green. Every
    ``tasks/<task_id>/`` is exercised, so adding a task needs only its prompt."""
    if not os.environ.get(LIVE_DRIVER_ENV_VAR):
        pytest.skip(
            "live lane needs a driver: set "
            "PROTEAN_EVAL_LIVE_DRIVER='module.path:factory'"
        )
    driver = resolve_live_driver(build_pack_prompt(), TOOL_SPECS)
    assert driver is not None  # the env var is set, so resolution returns one

    transcript = record(task_id, driver)

    # Validate before saving: a non-replayable or non-green run must not leave a
    # bad fixture in the checkout. Verify the tree the replay actually produced,
    # not just a mid-run recorded result.
    workspace = Workspace(tmp_path)
    result = replay(transcript, workspace=workspace)
    assert result.project_hash == transcript.project_hash
    # A divergence here is not a stale fixture (it was just recorded); it means
    # a tool answers differently run to run, which would make the fixture fail
    # in CI the moment it is committed.
    assert not result.result_divergences, "\n".join(result.result_divergences)
    # The recorded run must itself have verified green (the task asks the agent
    # to run verify), and a fresh verify of the produced tree must also pass.
    assert result.verify_results, "the live run recorded no run_verify call"
    assert result.verify_results[-1]["verdict"] == "pass"
    assert run_verify(workspace.root)["verdict"] == "pass"

    transcript.save(eval_root())  # the live lane doubles as the recorder


def test_live_lane_reports_context_driven_stability(tmp_path: Path) -> None:
    """Drive the context-driven approach through the live model N times, score
    each run against the gold, and report its run-to-run stability. The
    context-driven variance number comes from this lane, because transcript
    replay is deterministic by construction and its stability is always perfect.
    It skips without a driver exactly like the recorder test above, so core CI
    never reaches a model.

    The variance value itself is not pinned; it depends on the live model. The
    test asserts the shape: ``runs`` matches the run count and every field is in
    range, and it requires the driver to have produced a scored project on at
    least one run, so a driver that generates nothing every run fails here
    instead of reading as perfectly stable."""
    if not os.environ.get(LIVE_DRIVER_ENV_VAR):
        pytest.skip(
            "live lane needs a driver: set "
            "PROTEAN_EVAL_LIVE_DRIVER='module.path:factory'"
        )
    task_id = "place_order"
    # ``protean new`` needs its output folder to already exist, and ``build_gold``
    # takes a caller-owned destination, so create it here before building.
    gold_dest = tmp_path / "gold"
    gold_dest.mkdir()
    gold = build_gold(read_spec(task_id), gold_dest)
    counter = itertools.count()

    def run_once():
        # A fresh driver and a fresh workspace per run: the whole point is to see
        # how much the model varies across independent runs of the same task.
        driver = resolve_live_driver(build_pack_prompt(), TOOL_SPECS)
        assert driver is not None  # the env var is set, so resolution returns one
        run_dir = tmp_path / f"run-{next(counter)}"
        run_dir.mkdir()
        return context_driven_outcome(
            task_id, gold.ir, driver=driver, workspace=Workspace(run_dir)
        )

    stability = run_stability(run_once, n=DEFAULT_RUNS)

    assert stability.runs == DEFAULT_RUNS
    assert stability.distinct_results >= 1
    assert 0.0 <= stability.identical_result_rate <= 1.0
    assert stability.score_stdev >= 0.0
    assert 0.0 <= stability.score_min <= stability.score_max <= 1.0
    assert 0.0 <= stability.score_mean <= 1.0
    # A driver that produces no readable domain on every run scores 0.0 across
    # the board, which aggregates to the same shape as a perfect approach
    # (one distinct result, rate 1.0, stdev 0.0). Require at least one run to
    # have recovered something, so a silent driver failure fails the lane.
    assert stability.score_max > 0.0
