"""The provider-neutral record/replay format for an eval run.

A transcript is one JSON file per run, at
``tests/eval/transcripts/<pack_version>/<task_id>.json``, holding:

- ``pack_version``: the minor the run was recorded against, as
  ``<major>.<minor>.0`` (see :func:`transcript_version`). Every patch release of
  a minor replays that minor's transcripts.
- ``task_id``: the task directory name under ``tests/eval/tasks/``.
- ``task_input``: the task prompt (the text of ``task.md``).
- ``turns``: the ordered assistant turns, each turn's text, its tool calls as
  ``[{name, input}]``, and the ``tool_results`` those calls returned, aligned by
  position. Replay never feeds a recorded result back: it recomputes every one
  by re-running the tool, so the project a transcript lands stays a pure
  function of the turns. The recorded copy is a staleness signal, compared
  against the recomputed one.
- ``project_hash``: the hash of the project tree the run produced. On replay,
  the recomputed hash must equal this; a divergence means the transcript no
  longer lands the same project (a stale transcript).
- ``recorded_by``: ``"live"`` when the live lane recorded the run through a real
  model, and absent otherwise. The guard rejects a transcript without it, so a
  scripted record, which never carries it, cannot stand in for a recording.
- ``model_id``: the model the live driver ran, stamped next to ``recorded_by``.

Two things can diverge on replay, and either one means re-record: the project
hash, and a recorded tool result the tools no longer return.

The format is provider-neutral: it records what the agent decided (text and tool
calls), not any one model's wire format, so a run recorded against any live
driver replays through the same deterministic loop.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "LIVE_LANE_COMMAND",
    "LIVE_RECORDER",
    "TASKS_DIRNAME",
    "TASK_FILE",
    "TRANSCRIPTS_DIRNAME",
    "ToolCall",
    "Transcript",
    "Turn",
    "current_transcripts",
    "guard_problems",
    "key_problems",
    "list_transcripts",
    "live_marker_problems",
    "missing_transcript_problem",
    "transcript_path",
    "transcript_version",
    "transcripts_dir",
]

TRANSCRIPTS_DIRNAME = "transcripts"
TASKS_DIRNAME = "tasks"
TASK_FILE = "task.md"

# The ``recorded_by`` value the live lane stamps on a transcript it recorded.
LIVE_RECORDER = "live"

# The command that runs the live lane, named in every guard message.
LIVE_LANE_COMMAND = "pytest tests/eval -m live"

_RELEASE_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation an assistant turn asked for: a tool name and its
    keyword arguments. ``input`` mirrors the JSON key in the stored format."""

    name: str
    input: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCall:
        return cls(name=data["name"], input=dict(data.get("input", {})))


@dataclass(frozen=True)
class Turn:
    """One assistant turn: its text, the tool calls it requested, and what those
    calls returned. A turn with no tool calls is a final answer, which ends the
    run.

    ``tool_results`` is aligned by position with ``tool_calls`` and holds what
    the agent saw when the run was recorded. A driver never sets it; the run
    loop fills it in from the tools it actually ran. Replay recomputes the
    results rather than reading them back, and compares the two: a recorded
    result the tools no longer return flags a stale transcript.
    """

    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[dict[str, Any], ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Turn:
        calls = tuple(ToolCall.from_dict(c) for c in data.get("tool_calls", []))
        results = tuple(dict(r) for r in data.get("tool_results", []))
        return cls(text=data.get("text", ""), tool_calls=calls, tool_results=results)


@dataclass(frozen=True)
class Transcript:
    """A recorded run: the task, the ordered assistant turns, and the hash of
    the project they produced, all keyed to a pack minor.

    ``recorded_by`` and ``model_id`` are ``None`` on a transcript the live lane
    did not stamp, including a file written before the fields existed."""

    pack_version: str
    task_id: str
    task_input: str
    turns: tuple[Turn, ...]
    project_hash: str
    recorded_by: str | None = None
    model_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transcript:
        return cls(
            pack_version=data["pack_version"],
            task_id=data["task_id"],
            task_input=data["task_input"],
            turns=tuple(Turn.from_dict(t) for t in data.get("turns", [])),
            project_hash=data["project_hash"],
            recorded_by=data.get("recorded_by"),
            model_id=data.get("model_id"),
        )

    def dumps(self) -> str:
        """Serialize to canonical JSON: sorted keys, two-space indent, trailing
        newline, so a re-recorded transcript diffs cleanly against its
        predecessor."""
        return (
            json.dumps(asdict(self), indent=2, sort_keys=True, ensure_ascii=False)
            + "\n"
        )

    @classmethod
    def loads(cls, text: str) -> Transcript:
        return cls.from_dict(json.loads(text))

    @classmethod
    def load(cls, path: Path) -> Transcript:
        return cls.loads(Path(path).read_text(encoding="utf-8"))

    def save(self, eval_root: Path) -> Path:
        """Write the transcript to its canonical path under *eval_root* and
        return that path, creating the pack-version directory if needed."""
        path = transcript_path(eval_root, self.pack_version, self.task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # newline="" keeps the canonical LF bytes from dumps(), so a transcript
        # saved on one OS is byte-identical to the same run saved on another.
        path.write_text(self.dumps(), encoding="utf-8", newline="")
        return path


def transcripts_dir(eval_root: Path, pack_version: str) -> Path:
    """The directory holding transcripts recorded against *pack_version*."""
    return Path(eval_root) / TRANSCRIPTS_DIRNAME / pack_version


def transcript_path(eval_root: Path, pack_version: str, task_id: str) -> Path:
    """The canonical path of one task's transcript for *pack_version*."""
    return transcripts_dir(eval_root, pack_version) / f"{task_id}.json"


def list_transcripts(eval_root: Path, pack_version: str) -> list[Path]:
    """Return the sorted transcript files recorded against *pack_version*, or an
    empty list when none have been recorded (the pack is stale, or new)."""
    directory = transcripts_dir(eval_root, pack_version)
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.json"))


def transcript_version(version: str) -> str:
    """Return the transcript key for pack *version*: its minor, as
    ``<major>.<minor>.0``, so ``0.19.1`` maps to ``0.19.0``.

    Raises :class:`ValueError` when *version* is not three dot-separated
    integers, so a pre-release or a malformed version fails loudly instead of
    keying a directory nobody records into.
    """
    match = _RELEASE_VERSION.fullmatch(version)
    if match is None:
        raise ValueError(
            f"pack version {version!r} is not <major>.<minor>.<patch> integers"
        )
    major, minor, _ = (int(part) for part in match.groups())
    return f"{major}.{minor}.0"


def current_transcripts(eval_root: Path, version: str) -> list[Path]:
    """Return the sorted transcript files for the minor of pack *version*.

    Only that minor's directory is read. An older minor's transcripts never
    stand in for it, so a new minor with nothing recorded returns an empty list.
    """
    return list_transcripts(eval_root, transcript_version(version))


def missing_transcript_problem(eval_root: Path, version: str) -> str | None:
    """Return the guard message when the minor of pack *version* has no
    transcript, or ``None`` when it has at least one."""
    if current_transcripts(eval_root, version):
        return None
    key = transcript_version(version)
    return (
        f"no live transcript under {TRANSCRIPTS_DIRNAME}/{key}/ for pack "
        f"{version}. Record one with the live lane (`{LIVE_LANE_COMMAND}`) "
        f"and commit it."
    )


def live_marker_problems(transcript: Transcript, path: Path) -> list[str]:
    """Return one message per missing live-recording mark on *transcript*, read
    from *path*; empty when it carries ``recorded_by="live"`` and a non-empty
    ``model_id``."""
    problems: list[str] = []
    if transcript.recorded_by != LIVE_RECORDER:
        problems.append(
            f"{path} has recorded_by={transcript.recorded_by!r}, not "
            f"{LIVE_RECORDER!r}: only a live recording counts. Re-record it with "
            f"`{LIVE_LANE_COMMAND}`."
        )
    if not isinstance(transcript.model_id, str) or not transcript.model_id.strip():
        problems.append(
            f"{path} records no model_id; a live recording names the model it "
            f"ran. Re-record it with `{LIVE_LANE_COMMAND}`."
        )
    return problems


def key_problems(transcript: Transcript, path: Path, version: str) -> list[str]:
    """Return one message per key mismatch on *transcript*, read from *path*;
    empty when its ``pack_version`` equals both its directory and the minor of
    pack *version*, and its ``task_id`` equals the file name."""
    problems: list[str] = []
    key = transcript_version(version)
    if not transcript.pack_version == path.parent.name == key:
        problems.append(
            f"{path} records pack_version {transcript.pack_version!r} but sits "
            f"under {path.parent.name!r} for pack {version} (minor {key!r}); "
            f"re-record it."
        )
    if transcript.task_id != path.stem:
        problems.append(
            f"{path} records task_id {transcript.task_id!r}; the canonical key "
            f"is <task_id>.json."
        )
    return problems


def guard_problems(eval_root: Path, version: str) -> list[str]:
    """Return every reason the committed transcripts for pack *version* fail the
    guard, empty when they pass: the minor has none, or a file lacks the live
    mark or sits under the wrong key."""
    missing = missing_transcript_problem(eval_root, version)
    if missing is not None:
        return [missing]
    problems: list[str] = []
    for path in current_transcripts(eval_root, version):
        transcript = Transcript.load(path)
        problems.extend(live_marker_problems(transcript, path))
        problems.extend(key_problems(transcript, path, version))
    return problems
