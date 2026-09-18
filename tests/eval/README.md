# Comparison-eval harness

This directory holds the eval machinery for the comparison-eval epic: running a
scaffolding task through the **context-driven path** and recording it as a
replayable fixture. It is test-and-eval infrastructure. It is not shipped in the
wheel (the wheel packages only `src/protean`).

Scoring lives with the comparison eval that consumes these transcripts. This
harness produces and records a project; it does not score it.

## The two lanes

- **Replay lane (default, CI, no model).** `pytest tests/eval` replays every
  committed transcript for the installed pack version and asserts the produced
  project tree hashes to the recorded value and `protean verify` is green. It
  needs no model access.
- **Live lane (opt-in, maintainer-side).** `pytest tests/eval -m live` drives a
  task through a real model, produces a project, and records the transcript. It
  doubles as the recorder. It skips when no live driver is configured.

## Layout

```
tests/eval/
  tasks/<task_id>/task.md          # one prompt per task; nothing else
  transcripts/<pack_version>/<task_id>.json   # recorded runs, keyed to the pack
  workspace.py transcript.py tools.py drivers.py runner.py   # the harness
```

Adding a task means adding `tasks/<task_id>/task.md`. The expected structure and
scoring live with the comparison eval that consumes these transcripts.

## The transcript format

One JSON file per run, holding the pack version, the task id, the task prompt,
the ordered assistant `turns` (each turn's text, its `tool_calls` as
`[{name, input}]`, and the `tool_results` those calls returned), and a
`project_hash` of the produced tree.

Replay never feeds a recorded result back. It recomputes every one by re-running
the tool, so the project a transcript lands is a pure function of the assistant
turns. The recorded results are the second staleness signal: replay compares
them against the recomputed ones. Either divergence means re-record, the project
hash or a tool result. The hash covers only the files the agent wrote, so on its
own it would miss a verify verdict or a diagnostic code that changed. A replay
that stops short of the recorded turns is a divergence too, since the tail then
goes unchecked.

`run_verify`'s `errors` text is left out of that comparison. An init failure
puts a traceback in it, naming files outside the workspace whose paths differ
from machine to machine, so a replay cannot reproduce it. The verdict, the codes,
the counts and the exit code are, and they are what the comparison checks.

## The agent's tools

Generic file operations plus a verify signal, and nothing else: `write_file`,
`read_file`, `list_dir`, and `run_verify` (which runs `protean verify` and
returns its verdict). The agent does **not** get `protean add`: handing it the
scaffold command would collapse the context-driven path into the deterministic
`add` path and void the comparison.

## Pack staleness

Transcripts are keyed to `PACK_VERSION`. When the pack version changes, the old
version's transcripts are orphaned and a new directory must be recorded. The
replay lane asserts a transcript exists for the current version and otherwise
fails with "stale pack, re-record".

## Recording a transcript (maintainer)

The live lane uses your existing model access through a small driver you point
the harness at, so the harness ships no model dependency and no metered API key.
Set the driver as `module.path:factory`:

```bash
export PROTEAN_EVAL_LIVE_DRIVER='my_eval_driver:make_driver'
pytest tests/eval -m live
```

The factory is called as `factory(system_prompt, tool_specs)` and returns an
object with `next_turn(conversation) -> Turn | None`. `system_prompt` is the
packaged AGENTS.md plus the bundled skills at the installed pack version;
`tool_specs` describes the tools. The driver runs a normal tool-use loop:
each turn it returns the assistant's text and tool calls, and the harness feeds
the tool results back into the conversation it sees next. Returning `None` (or a
turn with no tool calls) ends the run. The recorded transcript is written under
`transcripts/<pack_version>/` for you to commit.

The committed `place_order.json` is a bootstrap fixture, authored with a scripted
driver so the replay lane has something to run in CI before a real recording
exists. Re-record it from a live run when the pack version changes.
