# Comparison-eval harness

This directory holds the eval machinery for the comparison-eval epic: running a
scaffolding task through the **context-driven path**, recording it as a
replayable fixture, and scoring both approaches against a deterministic gold. It
is test-and-eval infrastructure. It is not shipped in the wheel (the wheel
packages only `src/protean`).

## The two lanes

- **Replay lane (default, CI, no model).** `pytest tests/eval` replays every
  committed transcript for the installed pack version and asserts the produced
  project tree hashes to the recorded value and `protean verify` is green. It
  needs no model access.
- **Live lane (opt-in, maintainer-side).** `pytest tests/eval -m live` drives a
  task through a real model, produces a project, and records the transcript. It
  doubles as the recorder. It skips when no live driver is configured.

## Scoring the two approaches

For one task the comparison (`compare(task_id)`) runs two approaches and reports,
per approach, whether `protean verify` is green, a base correctness score, and a
boundary/aggregate recovery score against the same gold:

- **Approach A (deterministic).** `build_gold` scaffolds the task's gold project
  from its `spec.json`: `protean new` (with the example slice off), then one
  `protean add aggregate <Name>` per aggregate. Scoring the gold's IR against
  itself is 1.0 by construction, so Approach A is the scorer's own oracle check.
- **Approach B (context-driven).** Replay the task's committed transcript into a
  workspace, read the produced project's IR, and score it against the gold.

Both verdicts are a fresh `protean verify` of the finished project, not a verify
the run recorded along the way: a transcript can verify green and then write a
breaking change, so the reported verdict has to describe the same project whose
IR is scored.

A replay is scored only when it still reproduces its recording. If the replayed
tree hashes differently than the recorded hash, or a re-run tool no longer
answers what the recording saw, `compare` raises `StaleTranscriptError` rather
than publishing a score for a stale transcript. Re-record the transcript from
the live lane.

### The gold and its recipe

The gold is the reference structure. Its recipe is the task's `spec.json`, a
plain data file naming the project and the aggregate(s):

```json
{"project_name": "place_order", "aggregates": ["Order"]}
```

`protean add aggregate Order` emits more than the task names: a canned command
and event, a command handler, and also a projector and a read-model. The base
rubric scores only **aggregates, fields, commands, events, and handlers**, so the
projector and read-model stay out of scope: a context-driven project that skips
them loses no points for it.

### The rubric

The correctness score is per-element partial credit: the fraction of the gold's
scored elements the produced project recovers, every element weighted equally (a
missing field counts the same as a missing aggregate). An element is recovered
when the produced IR carries one of the **same category and same class name**.
Matching uses the class name, the final segment of the IR FQN. It ignores the
full FQN because the gold and the context-driven project use different package
names. Fields match on `(aggregate class name, field name)`, so renaming the
aggregate drops every field under it. Matching is exact per category; fuzzy or
semantic matching is a later dimension.

Matching on the class name only works on a gold whose class names tell its
elements apart. A gold carrying both `sales.commands.CreateOrder` and
`billing.commands.CreateOrder` reduces them to one signature, which would shrink
the denominator and let a single produced command recover two gold elements.
`score` raises `AmbiguousGoldError` on such a gold instead of reporting that
number. The produced project is not checked the same way: the gold still asks
for one element there, so one of the produced elements matching it is a real
recovery.

### Boundary and aggregate recovery

The base rubric counts names. It cannot see whether a recovered command sits under
the right aggregate, or whether an aggregate sits in the right bounded context. A
project that recovers every element name but puts them under the wrong aggregate
scores a full 1.0 on the base rubric. `score_boundary` adds the two scores that
tell that apart, reading the per-aggregate `clusters` the base rubric only uses
for fields:

- **Placement.** Of the per-cluster elements (commands, events, handlers,
  entities) the produced project recovers by class name, the fraction it attaches
  to the correct aggregate. The denominator is the count the produced project
  recovered, so placement scores only the elements the project got back, on
  whether each landed under the right aggregate. An element the project wrote but
  attached to no aggregate at all (the IR lists it under `elements` and in no
  cluster) counts as misplaced. The same names under the wrong aggregate score
  high on the base rubric and 0 here, which is the discriminator.
- **Context.** Of the aggregates the produced project recovers, the fraction that
  sit in the matching bounded context. The context is the aggregate's
  package-relative first module segment (`Order` at `shop.order.aggregate` is in
  the `order` context), so a gold under package `sales` and a produced project
  under `app` still match on `order`. The package is read off the aggregate
  modules themselves: it is the first segment they all share. A project packaged
  as `ecommerce` whose domain is named `Ordering` still splits into its `order`
  and `payment` contexts. A gold with a single context has no boundary between
  contexts to score, so its recovered aggregates match whatever module they sit
  in, as long as the produced project keeps them in one context too. That is the
  `place_order` shape: the gold scaffolds `place_order.order.aggregate` and the
  replay writes a root `domain.py`, and the task asked for neither layout.
  Splitting a one-context gold into two contexts is still a miss.

Both scores are `0.0` when nothing is recovered (an empty produced or gold IR),
the same guard the base rubric uses, and `score_boundary` raises the same
`AmbiguousGoldError` when the gold cannot be scored by class name. The base
`score` and its `Correctness` are unchanged; recovery is returned alongside as a
`Recovery`.

The `order_and_customer` task foregrounds placement (two aggregates, each owning
its own slice); `order_and_payment` foregrounds context (an `Order` and a
`Payment` in separate context modules). A task declares its context grouping in
`spec.json` with a `contexts` object (`{"order": ["Order"], "payment":
["Payment"]}`) instead of a flat `aggregates` list; both forms scaffold the same
gold. `protean add aggregate` builds each aggregate into its own slice module, so
a context names the one aggregate whose slug is the context name. `read_spec`
rejects any other grouping, so a spec never scaffolds a gold whose contexts are
not the ones it declared.

What the two new tasks omit, until their transcripts are recorded: only
`place_order` carries a committed transcript, so `compare()` runs both approaches
for it alone. The other two tasks score their gold through the harness (Approach
A and the scorer), and Approach B joins them once the live lane records a
transcript for each.

### Reading Approach B's number

The scaffold's canned command and event names (`CreateOrder`, `OrderCreated`)
differ from a task-faithful project's own (`PlaceOrder`, and often no separate
event), so a context-driven project recovers some but not all of the gold's
elements. That graded distance is the intended signal: the score measures how
close the context-driven structure lands to the deterministic one.

The score is structural recall against the `add` scaffold. It is not a measure of
how faithful the project is to `task.md`. A project that builds exactly what the
task asks (a `PlaceOrder` command and no separate event) still scores below 1.0,
because the gold carries the scaffold's `CreateOrder` and `OrderCreated`. So a
more task-faithful project can score lower here. A per-task expected set of
commands, events, and fields (so the score tracks the task, and the scaffold is
just one way to author it) is a later dimension (#1350).

## Layout

```
tests/eval/
  tasks/<task_id>/task.md          # the prompt the context-driven path sees
  tasks/<task_id>/spec.json        # the gold recipe: project name + aggregates (flat or by context)
  transcripts/<pack_version>/<task_id>.json   # recorded runs, keyed to the pack
  workspace.py transcript.py tools.py drivers.py runner.py   # the run harness
  discovery.py ir_probe.py spec.py gold.py scoring.py compare.py  # the scorer
```

Adding a task's gold and scoring side means adding `tasks/<task_id>/task.md` and
`tasks/<task_id>/spec.json`: `list_task_specs()` discovers the task from those two
files alone, and `build_gold` and the rubric run from them. Approach B (the
context-driven half of `compare`) also needs a recorded transcript at
`transcripts/<pack_version>/<task_id>.json`, so a new task's full comparison needs
a maintainer-side recording too (see "Recording a transcript" below).

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
