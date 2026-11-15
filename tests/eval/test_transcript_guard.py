"""The minor-version key, the transcript guard and the live stamp.

Every test here builds its own eval root under ``tmp_path`` and passes an
explicit pack version, so none of them depends on the committed transcripts or
the installed pack.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.eval.drivers import LiveDriverError, stamp_live
from tests.eval.transcript import (
    LIVE_LANE_COMMAND,
    LIVE_RECORDER,
    Transcript,
    Turn,
    current_transcripts,
    guard_problems,
    missing_transcript_problem,
    transcript_path,
    transcript_version,
)

pytestmark = pytest.mark.no_test_domain


def _transcript(
    pack_version: str = "0.19.0",
    task_id: str = "place_order",
    *,
    recorded_by: str | None = LIVE_RECORDER,
    model_id: str | None = "model-1",
) -> Transcript:
    return Transcript(
        pack_version,
        task_id,
        "place an order",
        (Turn("done"),),
        "sha256:recorded",
        recorded_by=recorded_by,
        model_id=model_id,
    )


def _write(root: Path, transcript: Transcript, *, directory: str | None = None) -> Path:
    """Write *transcript* under *root*, in *directory* when given instead of its
    own ``pack_version``, and return the path."""
    path = transcript_path(
        root, directory or transcript.pack_version, transcript.task_id
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(transcript.dumps(), encoding="utf-8")
    return path


class TestTranscriptVersion:
    @pytest.mark.parametrize(
        ("version", "key"),
        [
            ("0.19.1", "0.19.0"),
            ("0.19.0", "0.19.0"),
            ("1.2.30", "1.2.0"),
            ("10.0.7", "10.0.0"),
        ],
    )
    def test_maps_a_release_to_its_minor(self, version: str, key: str) -> None:
        assert transcript_version(version) == key

    @pytest.mark.parametrize("version", ["0.19", "0.19.0rc1", "x.y.z", "", "1.2.3.4"])
    def test_rejects_a_version_that_is_not_three_integers(self, version: str) -> None:
        with pytest.raises(ValueError, match="major"):
            transcript_version(version)


class TestGuard:
    def test_a_patch_replays_its_minors_live_transcript(self, tmp_path: Path) -> None:
        """Pack 0.19.1 reads the 0.19.0 directory, and a live transcript there
        passes the guard."""
        written = _write(tmp_path, _transcript())

        assert current_transcripts(tmp_path, "0.19.1") == [written]
        assert missing_transcript_problem(tmp_path, "0.19.1") is None
        assert guard_problems(tmp_path, "0.19.1") == []

    def test_a_new_minor_does_not_fall_back_to_the_previous_one(
        self, tmp_path: Path
    ) -> None:
        """Pack 0.19.0 with only 0.18.0 recorded fails, and the message names the
        directory it looked in and the live lane."""
        _write(tmp_path, _transcript("0.18.0"))

        assert current_transcripts(tmp_path, "0.19.0") == []
        problem = missing_transcript_problem(tmp_path, "0.19.0")
        assert problem is not None
        assert "transcripts/0.19.0/" in problem
        assert LIVE_LANE_COMMAND in problem
        assert LIVE_LANE_COMMAND == "pytest tests/eval -m live"
        assert guard_problems(tmp_path, "0.19.0") == [problem]

    @pytest.mark.parametrize("recorded_by", [None, "scripted"])
    def test_a_transcript_without_the_live_mark_fails_and_is_named(
        self, tmp_path: Path, recorded_by: str | None
    ) -> None:
        path = _write(tmp_path, _transcript(recorded_by=recorded_by))

        problems = guard_problems(tmp_path, "0.19.0")

        assert len(problems) == 1
        assert str(path) in problems[0]
        assert "recorded_by" in problems[0]

    def test_a_file_written_before_the_mark_existed_fails(self, tmp_path: Path) -> None:
        """A transcript whose JSON has no ``recorded_by`` or ``model_id`` key, as
        the earlier recordings had, loads and fails on both marks."""
        path = transcript_path(tmp_path, "0.19.0", "place_order")
        path.parent.mkdir(parents=True)
        path.write_text(
            '{"pack_version": "0.19.0", "project_hash": "sha256:x", '
            '"task_id": "place_order", "task_input": "in", "turns": []}\n',
            encoding="utf-8",
        )

        problems = guard_problems(tmp_path, "0.19.0")

        assert len(problems) == 2
        assert all(str(path) in problem for problem in problems)
        assert "recorded_by=None" in problems[0]
        assert "model_id" in problems[1]

    @pytest.mark.parametrize("model_id", [None, "", "   "])
    def test_a_live_transcript_without_a_model_fails(
        self, tmp_path: Path, model_id: str | None
    ) -> None:
        path = _write(tmp_path, _transcript(model_id=model_id))

        problems = guard_problems(tmp_path, "0.19.0")

        assert len(problems) == 1
        assert str(path) in problems[0]
        assert "model_id" in problems[0]

    def test_a_pack_version_other_than_its_directory_fails(
        self, tmp_path: Path
    ) -> None:
        """A transcript recording 0.18.0 copied into 0.19.0/ is caught."""
        path = _write(tmp_path, _transcript("0.18.0"), directory="0.19.0")

        problems = guard_problems(tmp_path, "0.19.0")

        assert len(problems) == 1
        assert str(path) in problems[0]
        assert "'0.18.0'" in problems[0]

    def test_a_patch_number_in_pack_version_fails(self, tmp_path: Path) -> None:
        """The key is the minor, so a transcript recording ``0.19.1`` in 0.19.0/
        does not match."""
        _write(tmp_path, _transcript("0.19.1"), directory="0.19.0")

        problems = guard_problems(tmp_path, "0.19.1")

        assert len(problems) == 1
        assert "pack_version '0.19.1'" in problems[0]

    def test_a_task_id_other_than_its_file_name_fails(self, tmp_path: Path) -> None:
        transcript = _transcript(task_id="other_task")
        path = transcript_path(tmp_path, "0.19.0", "place_order")
        path.parent.mkdir(parents=True)
        path.write_text(transcript.dumps(), encoding="utf-8")

        problems = guard_problems(tmp_path, "0.19.0")

        assert len(problems) == 1
        assert "task_id 'other_task'" in problems[0]


@dataclass
class _StubDriver:
    model_id: object

    def next_turn(self, conversation: object) -> None:
        return None


class _DriverWithoutModel:
    def next_turn(self, conversation: object) -> None:
        return None


class TestStampLive:
    def test_stamps_the_live_mark_and_the_drivers_model(self) -> None:
        unstamped = _transcript(recorded_by=None, model_id=None)

        stamped = stamp_live(unstamped, _StubDriver(model_id="m-1"))

        assert stamped.recorded_by == "live"
        assert stamped.model_id == "m-1"
        assert stamped.turns == unstamped.turns
        assert stamped.project_hash == unstamped.project_hash

    def test_a_stamped_transcript_passes_the_guard(self, tmp_path: Path) -> None:
        stamped = stamp_live(
            _transcript(recorded_by=None, model_id=None), _StubDriver(model_id="m-1")
        )
        stamped.save(tmp_path)

        assert guard_problems(tmp_path, "0.19.0") == []

    @pytest.mark.parametrize(
        "driver",
        [_DriverWithoutModel(), _StubDriver(model_id=7), _StubDriver(model_id="")],
        ids=["missing", "not-a-str", "empty"],
    )
    def test_a_driver_without_a_usable_model_id_fails(self, driver: object) -> None:
        with pytest.raises(LiveDriverError, match="model_id"):
            stamp_live(_transcript(recorded_by=None, model_id=None), driver)
