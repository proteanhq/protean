"""The multi-turn loop that drives a run, plus record and replay.

:func:`run` is lane-agnostic: it asks a driver for the next assistant turn,
executes that turn's tool calls, feeds the results back into the conversation,
and repeats until the driver stops. The live lane and the replay lane are the
same loop with a different driver.

- :func:`record` runs a driver against a task, produces a project in a temporary
  workspace, and captures the run as a :class:`~tests.eval.transcript.Transcript`
  keyed to the current ``PACK_VERSION``. The live lane doubles as the recorder.
- :func:`replay` runs a transcript's recorded turns through the same loop with a
  :class:`~tests.eval.drivers.ReplayDriver`, into a caller-supplied workspace, so
  the caller can then compare the recomputed project hash against the recorded
  one and confirm ``protean verify`` is green.

The build the agent produces is a pure function of the assistant turns: replay
recomputes every tool result by re-running the tool. It also compares each
recomputed result against the one the transcript recorded and reports the
differences as :attr:`RunResult.result_divergences`, so a tool that now answers
differently shows up as a stale transcript even when the project hash still
matches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace
from pathlib import Path
from tempfile import TemporaryDirectory

from protean.dx.pack import (
    PACK_VERSION,
    SKILL_FILE,
    SKILLS_DIR,
    iter_skills,
    load_agents_source,
    read_pack_text,
)
from tests.eval.drivers import Conversation, Driver, Message, ReplayDriver
from tests.eval.tools import VerifyResult, execute_tool_call
from tests.eval.transcript import TASK_FILE, TASKS_DIRNAME, Transcript, Turn
from tests.eval.workspace import Workspace

__all__ = [
    "DEFAULT_MAX_TURNS",
    "RunResult",
    "RunnerError",
    "build_pack_prompt",
    "eval_root",
    "read_task",
    "record",
    "replay",
    "run",
]

# A run that never stops is a runaway loop, not a valid transcript; cap it. A
# real context-driven run works the pack over a handful of turns, well under
# this. Replay stops when the recorded turns run out, so it never reaches it.
DEFAULT_MAX_TURNS = 40


class RunnerError(Exception):
    """A run that did not stop within its turn budget."""


@dataclass
class RunResult:
    """The outcome of one run: the assistant turns (each carrying the results of
    its tool calls), the produced project's hash, and the ``run_verify`` results
    the run recorded, in order.

    ``result_divergences`` is filled in by :func:`replay` only: one line per
    recorded tool result the re-run tools no longer return. Empty on a live run,
    which has nothing to compare against.
    """

    turns: tuple[Turn, ...]
    project_hash: str
    verify_results: list[VerifyResult] = field(default_factory=list)
    result_divergences: tuple[str, ...] = ()


def eval_root() -> Path:
    """The ``tests/eval`` directory, the root for tasks and transcripts."""
    return Path(__file__).resolve().parent


def read_task(task_id: str, *, root: Path | None = None) -> str:
    """Return the prompt text of task *task_id* (its ``task.md``)."""
    base = root if root is not None else eval_root()
    return (base / TASKS_DIRNAME / task_id / TASK_FILE).read_text(encoding="utf-8")


def build_pack_prompt() -> str:
    """Assemble the system prompt a live driver gives the model: the packaged
    AGENTS.md followed by each bundled skill, at the installed pack version."""
    parts = [load_agents_source()]
    parts.extend(
        f"# Skill: {skill}\n\n{read_pack_text(SKILLS_DIR, skill, SKILL_FILE)}"
        for skill in iter_skills()
    )
    return "\n\n---\n\n".join(parts)


def run(
    task_input: str,
    driver: Driver,
    *,
    workspace: Workspace,
    system_prompt: str = "",
    max_turns: int = DEFAULT_MAX_TURNS,
) -> RunResult:
    """Drive *driver* over the tools until it stops, producing a project in
    *workspace*.

    The loop records each assistant turn, runs its tool calls, and appends the
    results to the conversation the driver sees next. It stops when the driver
    returns ``None`` or a turn with no tool calls (a final answer). A driver that
    keeps calling tools past *max_turns* raises :class:`RunnerError`.

    The returned turns carry the results the tools actually returned, so a
    recording captures what the agent saw. A driver's own ``tool_results`` are
    ignored: the loop ran the tools, so its results are the ones that count.
    """
    conversation = Conversation(
        system_prompt=system_prompt,
        messages=[Message(role="user", text=task_input)],
    )
    turns: list[Turn] = []
    verify_results: list[VerifyResult] = []

    for _ in range(max_turns):
        turn = driver.next_turn(conversation)
        if turn is None:
            break
        turns.append(turn)
        conversation.messages.append(
            Message(role="assistant", text=turn.text, tool_calls=turn.tool_calls)
        )
        if not turn.tool_calls:
            break
        results = []
        for call in turn.tool_calls:
            result = execute_tool_call(workspace, call)
            results.append(result)
            # A malformed run_verify call (extra args) comes back as a plain
            # error dict with no "verdict"; keep only real VerifyResults, so a
            # later verify_results[-1]["verdict"] read cannot KeyError.
            if call.name == "run_verify" and "verdict" in result:
                verify_results.append(result)
        turns[-1] = dataclass_replace(turn, tool_results=tuple(results))
        conversation.messages.append(Message(role="tool", tool_results=tuple(results)))
    else:
        raise RunnerError(f"driver did not stop within {max_turns} turns")

    return RunResult(
        turns=tuple(turns),
        project_hash=workspace.project_hash(),
        verify_results=verify_results,
    )


def record(
    task_id: str,
    driver: Driver,
    *,
    root: Path | None = None,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> Transcript:
    """Run *driver* against task *task_id* and capture it as a transcript.

    The run happens in a temporary workspace that is discarded afterwards; the
    transcript holds everything replay needs to land the same project again. The
    transcript is keyed to the current ``PACK_VERSION``.
    """
    task_input = read_task(task_id, root=root)
    with TemporaryDirectory(prefix="protean-eval-") as tmp:
        workspace = Workspace(Path(tmp))
        result = run(
            task_input,
            driver,
            workspace=workspace,
            system_prompt=build_pack_prompt(),
            max_turns=max_turns,
        )
    return Transcript(
        pack_version=PACK_VERSION,
        task_id=task_id,
        task_input=task_input,
        turns=result.turns,
        project_hash=result.project_hash,
    )


def replay(transcript: Transcript, *, workspace: Workspace) -> RunResult:
    """Replay *transcript*'s recorded turns into *workspace* with no model.

    The turn budget is the recorded turn count plus one: the extra turn lets the
    replay driver return ``None`` and stop cleanly when the last recorded turn
    still carries tool calls, so a replay cannot loop.

    Two signals tell the caller the transcript is stale, and it should check
    both: ``result.project_hash`` against ``transcript.project_hash``, and
    ``result.result_divergences`` for a recorded tool result the re-run tools no
    longer return.
    """
    driver = ReplayDriver(transcript.turns)
    result = run(
        transcript.task_input,
        driver,
        workspace=workspace,
        max_turns=len(transcript.turns) + 1,
    )
    return dataclass_replace(
        result,
        result_divergences=_result_divergences(transcript.turns, result.turns),
    )


def _result_divergences(
    recorded: tuple[Turn, ...], recomputed: tuple[Turn, ...]
) -> tuple[str, ...]:
    """Compare the recorded tool results against the recomputed ones, one line
    per difference and empty when they agree.

    A recorded turn carrying no results at all is skipped: there is nothing to
    compare, which is what a transcript recorded before results were captured
    looks like. The turns are zipped without ``strict``: a recorded final answer
    mid-transcript ends the replay early, leaving fewer recomputed turns.
    """
    lines: list[str] = []
    for index, (before, after) in enumerate(zip(recorded, recomputed, strict=False)):
        if not before.tool_results:
            continue
        if len(before.tool_results) != len(after.tool_results):
            lines.append(
                f"turn {index}: recorded {len(before.tool_results)} tool results, "
                f"recomputed {len(after.tool_results)}"
            )
            continue
        # after came from run(), so its results are one per tool call.
        for position, call in enumerate(after.tool_calls):
            was, now = before.tool_results[position], after.tool_results[position]
            if was != now:
                lines.append(
                    f"turn {index} call {position} ({call.name}): recorded {was!r}, "
                    f"recomputed {now!r}"
                )
    return tuple(lines)
