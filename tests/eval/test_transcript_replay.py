"""The replay lane and the pack-staleness guard.

These run in core CI with no model access. The staleness guard asserts a live
transcript exists for the installed pack's minor; the replay test replays each
committed transcript and asserts it lands the recorded project and verifies
green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean.dx.pack import PACK_VERSION
from tests.eval.runner import eval_root, read_task, replay
from tests.eval.tools import run_verify
from tests.eval.transcript import (
    Transcript,
    current_transcripts,
    key_problems,
    live_marker_problems,
    missing_transcript_problem,
)
from tests.eval.workspace import Workspace

pytestmark = pytest.mark.no_test_domain

# The transcripts committed for the installed pack's minor. Empty means a new
# minor has nothing recorded yet, which the staleness guard reports.
_CURRENT_TRANSCRIPTS = current_transcripts(eval_root(), PACK_VERSION)
_IDS = [p.stem for p in _CURRENT_TRANSCRIPTS]


def test_a_live_transcript_exists_for_the_current_minor() -> None:
    """The staleness guard: the installed pack's minor must have at least one
    transcript, or the replay lane has nothing to run. An older minor's
    directory does not count."""
    problem = missing_transcript_problem(eval_root(), PACK_VERSION)
    assert problem is None, problem


@pytest.mark.parametrize("transcript_path", _CURRENT_TRANSCRIPTS, ids=_IDS)
def test_transcript_is_a_live_recording(transcript_path: Path) -> None:
    """A committed transcript must carry ``recorded_by="live"`` and a
    ``model_id``, so a scripted or copied file cannot satisfy the guard."""
    problems = live_marker_problems(Transcript.load(transcript_path), transcript_path)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("transcript_path", _CURRENT_TRANSCRIPTS, ids=_IDS)
def test_transcript_pack_version_matches_its_directory(transcript_path: Path) -> None:
    """A transcript's internal ``pack_version`` must equal its directory and the
    installed pack's minor, and its ``task_id`` must equal the filename.
    Otherwise a misfiled fixture would satisfy the existence guard and replay
    against the wrong pack or under the wrong task."""
    problems = key_problems(
        Transcript.load(transcript_path), transcript_path, PACK_VERSION
    )
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("transcript_path", _CURRENT_TRANSCRIPTS, ids=_IDS)
def test_replay_is_deterministic_and_verifies_green(
    transcript_path: Path, tmp_path: Path
) -> None:
    """Replaying a committed transcript lands the recorded project and verifies
    green: the produced tree hashes to the recorded value, the re-run tools
    return what the recording saw, the recorded run exercised verify, and a
    fresh verify of the produced tree passes."""
    transcript = Transcript.load(transcript_path)
    workspace = Workspace(tmp_path)

    result = replay(transcript, workspace=workspace)

    assert result.project_hash == transcript.project_hash, (
        "stale transcript: replaying the recorded turns produced a different "
        "project tree than the recorded hash. Re-record this transcript."
    )
    # The hash covers only the files the agent wrote, so a tool that now answers
    # differently (a verify verdict, a new diagnostic code) is invisible to it.
    # The recorded results are the second staleness signal.
    assert not result.result_divergences, (
        "stale transcript: the tools no longer return what the recorded run "
        "saw. Re-record this transcript.\n" + "\n".join(result.result_divergences)
    )
    assert result.verify_results, (
        "the transcript records no run_verify call, so 'verify is green' was "
        "never checked during the run"
    )
    assert result.verify_results[-1]["verdict"] == "pass", (
        "the run's last recorded verify was not green; the transcript ends on a "
        f"failing project: {result.verify_results[-1]}"
    )
    # Authoritative: verify the tree the replay actually produced, so a
    # transcript that verifies mid-run and then breaks the project cannot pass.
    final = run_verify(workspace.root)
    assert final["verdict"] == "pass", (
        f"the produced project does not verify green: {final}"
    )


@pytest.mark.parametrize("transcript_path", _CURRENT_TRANSCRIPTS, ids=_IDS)
def test_transcript_is_stored_canonically(transcript_path: Path) -> None:
    """A committed transcript's bytes equal its own canonical serialization, so
    a recorder that wrote non-canonical JSON (churning diffs) is caught."""
    transcript = Transcript.load(transcript_path)
    assert transcript_path.read_text(encoding="utf-8") == transcript.dumps()


@pytest.mark.parametrize("transcript_path", _CURRENT_TRANSCRIPTS, ids=_IDS)
def test_transcript_matches_its_task_prompt(transcript_path: Path) -> None:
    """A transcript's recorded task input must equal its task's current
    ``task.md``, so editing a prompt without re-recording is caught."""
    transcript = Transcript.load(transcript_path)
    assert transcript.task_input == read_task(transcript.task_id), (
        f"transcript {transcript.task_id!r} was recorded against a different "
        f"task prompt than tasks/{transcript.task_id}/task.md holds now; "
        f"re-record it."
    )
