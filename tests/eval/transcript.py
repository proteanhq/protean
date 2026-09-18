"""The provider-neutral record/replay format for an eval run.

A transcript is one JSON file per run, at
``tests/eval/transcripts/<pack_version>/<task_id>.json``, holding:

- ``pack_version``: the DX pack version the run was recorded against.
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

Two things can diverge on replay, and either one means re-record: the project
hash, and a recorded tool result the tools no longer return.

The format is provider-neutral: it records what the agent decided (text and tool
calls), not any one model's wire format, so a run recorded against any live
driver replays through the same deterministic loop.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "TASKS_DIRNAME",
    "TASK_FILE",
    "TRANSCRIPTS_DIRNAME",
    "ToolCall",
    "Transcript",
    "Turn",
    "list_transcripts",
    "transcript_path",
    "transcripts_dir",
]

TRANSCRIPTS_DIRNAME = "transcripts"
TASKS_DIRNAME = "tasks"
TASK_FILE = "task.md"


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
    the project they produced, all keyed to a pack version."""

    pack_version: str
    task_id: str
    task_input: str
    turns: tuple[Turn, ...]
    project_hash: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transcript:
        return cls(
            pack_version=data["pack_version"],
            task_id=data["task_id"],
            task_input=data["task_input"],
            turns=tuple(Turn.from_dict(t) for t in data.get("turns", [])),
            project_hash=data["project_hash"],
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
