"""The live lane: drive a task through a real model and record the transcript.

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
from tests.eval.tools import TOOL_SPECS
from tests.eval.workspace import Workspace

pytestmark = [pytest.mark.live, pytest.mark.no_test_domain]


def test_live_lane_records_a_replayable_green_transcript(tmp_path: Path) -> None:
    """Drive the ``place_order`` task through the live model, record the run,
    and confirm the recorded transcript replays deterministically and green."""
    if not os.environ.get(LIVE_DRIVER_ENV_VAR):
        pytest.skip(
            "live lane needs a driver: set "
            "PROTEAN_EVAL_LIVE_DRIVER='module.path:factory'"
        )
    driver = resolve_live_driver(build_pack_prompt(), TOOL_SPECS)
    assert driver is not None  # the env var is set, so resolution returns one

    transcript = record("place_order", driver)

    # Validate before saving: a non-replayable or non-green run must not leave a
    # bad fixture in the checkout for a later replay to pick up.
    result = replay(transcript, workspace=Workspace(tmp_path))
    assert result.project_hash == transcript.project_hash
    assert result.verify_results, "the live run recorded no run_verify call"
    assert result.verify_results[-1]["verdict"] == "pass"

    transcript.save(eval_root())  # the live lane doubles as the recorder
