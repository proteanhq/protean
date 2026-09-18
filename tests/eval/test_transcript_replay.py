"""The replay lane and the pack-staleness guard.

These run in core CI with no model access. The staleness guard asserts a
transcript exists for the installed pack version; the replay test replays each
committed transcript and asserts it lands the recorded project and verifies
green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean.dx.pack import PACK_VERSION
from tests.eval.runner import eval_root, read_task, replay
from tests.eval.tools import run_verify
from tests.eval.transcript import Transcript, list_transcripts
from tests.eval.workspace import Workspace

pytestmark = pytest.mark.no_test_domain

# The transcripts committed for the installed pack version. Empty means the pack
# moved and nothing has been re-recorded, which the staleness guard reports.
_CURRENT_TRANSCRIPTS = list_transcripts(eval_root(), PACK_VERSION)
_IDS = [p.stem for p in _CURRENT_TRANSCRIPTS]


def test_a_transcript_exists_for_the_current_pack_version() -> None:
    """The staleness guard: the pack version must have at least one transcript,
    or the replay lane has nothing to run."""
    assert _CURRENT_TRANSCRIPTS, (
        f"stale pack, re-record: no transcript under "
        f"transcripts/{PACK_VERSION}/. Run the live lane "
        f"(`pytest tests/eval -m live`) and commit the new fixture."
    )


@pytest.mark.parametrize("transcript_path", _CURRENT_TRANSCRIPTS, ids=_IDS)
def test_transcript_pack_version_matches_its_directory(transcript_path: Path) -> None:
    """A transcript's internal ``pack_version`` must equal the installed
    ``PACK_VERSION`` and its directory, and its ``task_id`` must equal the
    filename. Otherwise a stale or misfiled fixture dropped into
    ``transcripts/{PACK_VERSION}/`` would satisfy the existence guard and replay
    against the wrong pack or under the wrong task."""
    transcript = Transcript.load(transcript_path)
    assert transcript.pack_version == PACK_VERSION == transcript_path.parent.name, (
        f"transcript {transcript.task_id!r} records pack_version "
        f"{transcript.pack_version!r} but sits under {transcript_path.parent.name!r} "
        f"for installed pack {PACK_VERSION!r}; re-record it."
    )
    assert transcript.task_id == transcript_path.stem, (
        f"transcript at {transcript_path.name} records task_id "
        f"{transcript.task_id!r}; the canonical key is <task_id>.json."
    )


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
