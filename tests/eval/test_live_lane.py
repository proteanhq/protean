"""The live lane: drive each task through a real model and record its transcript.

This lane is opt-in and maintainer-side. It skips unless a live driver is
configured through ``PROTEAN_EVAL_LIVE_DRIVER`` (see ``tests/eval/README.md``),
so core CI never needs model access. Selecting it explicitly, and recording:

    PROTEAN_EVAL_LIVE_DRIVER='my_driver:make_driver' pytest tests/eval -m live
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.eval.drivers import LIVE_DRIVER_ENV_VAR, resolve_live_driver
from tests.eval.runner import build_pack_prompt, eval_root, record, replay
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
