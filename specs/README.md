# Formal specs of Protean's core correctness protocols

This directory holds TLA+ specifications of the core protocols at the heart of
Protean's correctness guarantees, model-checked with TLC:

- **`Checkpoint.tla`**: the `$all` (cross-category) subscription checkpoint
  advance, the settle-then-process low-watermark shipped for #1088
  ([ADR-0025](../docs/adr/0025-all-subscription-gap-safety.md)).
- **`Outbox.tla`**: the transactional outbox two-phase publish (claim, publish
  to the broker, then mark the row).
- **`OCC.tla`**: the aggregate optimistic-concurrency no-lost-update protocol,
  the version check made atomic with the write (compare-and-set) shipped for
  #1087 (SQL) and #1258 (Memory)
  ([ADR-0013](../docs/adr/0013-optimistic-concurrency-and-claim-contract.md)).
- **`Recovery.tla`**: the event-store subscription's failure-recovery
  record-before-advance protocol, where a handler failure is written durably to
  the recovery stream *before* the read cursor advances past it, so a failed
  message is never silently dropped.

They exist because these are where Protean's hardest correctness claims live, and
where two silent-corruption bugs surfaced this cycle: #1087 (OCC lost update, now
modeled by `OCC.tla`) and #1088 (`$all` checkpoint gap-skip). #1088 was an
unconsidered-interleaving bug.
Randomized property tests (#1251) *sample* interleavings; a model checker is
*exhaustive* over interleavings up to a bound, which is exactly what catches that
bug class. Writing the protocols down forces every state, transition, and crash
point to be explicit.

## This is design-time verification, not a CI gate

TLA+ verifies the *spec*, not the Python. There is always a spec-to-code gap. So:

- The value is front-loaded at **design time** and at **each protocol change**,
  not continuously.
- These specs are **not** kept in CI lockstep with the code. That lockstep is a
  maintenance trap that breeds false confidence in a stale model. Re-run TLC
  deliberately when a modeled protocol changes; otherwise the checked-in spec is
  documentation of the verified design.
- Any counterexample TLC finds against a shipped protocol should be turned into a
  concrete case in the #1251 property suite, which *does* run against the real
  code. As of this writing TLC finds **no** counterexample against the guarantee
  invariants of any of the shipped protocols. The only counterexamples are the
  deliberate ones: the revert tests (which reintroduce a known bug) and the
  reachability probes (which witness that at-least-once redelivery, and OCC
  contention, are reachable).

**Trace validation is the exception.** It checks the *real code* against a spec
rather than the spec against itself, so it cannot go silently stale the way a
hand-maintained model can. It is designed to run as a per-PR gate, invoked through
`check.sh`. OCC is the first protocol wired up; see the next section.

## Running the checks

You need a Java runtime and the TLA+ tools jar (`tla2tools.jar`, from the
[TLA+ releases](https://github.com/tlaplus/tlaplus/releases)).

```bash
# one-time: a JDK and the tools jar
brew install openjdk                     # or any JDK 11+
mkdir -p ~/.tla && curl -sSL -o ~/.tla/tla2tools.jar \
  https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar

# run every configuration and assert its expected outcome
export PATH="$(brew --prefix openjdk)/bin:$PATH"
./check.sh
```

`check.sh` runs each configuration and asserts the expected result: the
shipped-protocol configs must pass, and each revert/probe config (`…_bug`,
`…_claim`, `…_dup`, `…_conflict`) must fail on its named invariant. It exits non-zero if any
expectation is unmet. Point it at a jar elsewhere with
`TLA_TOOLS=/path/to/tla2tools.jar ./check.sh`.

To run one configuration directly:

```bash
java -cp ~/.tla/tla2tools.jar tlc2.TLC -config Checkpoint.cfg Checkpoint.tla
```

From the repository root, `make verify-specs` delegates to this script.

The runs are small (a few thousand states each) and finish in about a second.

## Trace validation: proving the code conforms to the spec

The model checks above verify the *design*. Trace validation verifies the
*shipped code*: it records what the real commit paths actually do, then asks TLC
whether that recording is a behaviour the spec permits. OCC is the first protocol
wired up (#1382); the harness (`OCCTrace.tla`, the two cfgs, `occ_trace.py`, and
the `check.sh` plumbing) is built to be reused by the others. The `$all` gap-safe
checkpoint is the second (#1384) and reuses it verbatim; Recovery is the third
(#1385); the transactional outbox is the fourth (#1383). See "Checkpoint trace
validation", "Recovery trace validation", and "Outbox trace validation" below.

How it works, end to end:

1. **Record observations.** `src/protean/utils/occ_trace.py` is a recorder that is
   inactive by default. When a capture is active, the real commit paths emit, per
   unit of work, the state the spec talks about — the version read as the base, the
   outcome (`committed`/`conflicted`), and the resulting stored version — captured
   under the same lock or transaction as the real compare-and-set.
   `MemorySession.commit` and the SQLAlchemy `_update` version check are
   instrumented. Almost every value is read straight from the store rather than
   derived, so the log cannot share a blind spot with the spec; the one exception
   is the SQLAlchemy committed version, recorded as `base + 1` (the value the
   `version_id_col` guard is guaranteed to set), since the standalone commit closes
   the connection before the row can be read back.
2. **Replay against the real `.tla`.** `OCCTrace.tla` reads the log as a constant
   `Trace` and replays each entry as a read that captures the recorded base (a
   `DoRead` faithful to `OCC!Read`) and then the real `OCC!Commit` action, whose
   verdict must match what was recorded. The judge is `OCC.tla` itself, not a
   re-encoding of the protocol. If the code diverged, `OCC!Commit` and the
   recording disagree, the replay stalls, and `TraceAccepted` fails on the first
   step no spec action explains.
3. **Two negative checks, so green means something.** A seeded lost-update log
   (`traces/occ_bug.jsonl`: two commits from the same base) must fail conformance;
   a log with no conflict (`traces/occ_no_conflict.jsonl`) leaves `NoConflict`
   holding and is rejected as under-covered. Both mirror the model's own revert
   test and reachability probe.

`check.sh` runs all three: it records a fresh Memory-adapter trace and asserts it
is **accepted** (conforms to `OCC.tla` *and* exercises contention), and asserts
the two fixtures are **rejected** for the right reason (the seeded one fails
conformance, the uncontended one fails coverage). `python3` is required for the
whole leg (it converts each log to TLA+); recording a fresh trace additionally
needs `protean` importable, so when only that is missing the real-trace leg is
skipped and the two fixtures still run. No external services are needed — the
Memory adapter's compare-and-set produces a genuine one-winner/rest-conflict trace
on its own.

**Adapter coverage.** The Memory path is validated end to end. The SQLAlchemy
`_update` path emits the same observations for a standalone (non-UoW) update, which
is what `tests/adapters/repository/sqlalchemy_repo/postgresql/test_postgresql_occ_trace.py`
pins. Under `repository.add` the version-guarded flush is deferred to the Unit of
Work commit, so both a *concurrent* SQL commit and its conflict resolve there
rather than in `_update` (the SQL emits are gated on the standalone path for that
reason); capturing that deferred outcome is left for a follow-up, and `check.sh`
uses the deterministic Memory trace as its conformance source.

### Checkpoint trace validation

The same harness, pointed at the `$all` gap-safe checkpoint (#1384).
`src/protean/utils/checkpoint_trace.py` records, per
`_gap_safe_batch` call, the raw state the walk observed: the cursor it started
from, the `global_position` values it saw present, the holes it abandoned, and the
watermark it settled on. `specs/checkpoint_trace.py record` drives the real
`_gap_safe_batch` through a scripted out-of-order gap (reusing the #1251 model's
subscription via `tests/verification/strategies.py`, so no store is re-driven) with
the recorder active. `to-tla` expands each raw batch into the atomic transitions
`CheckpointTrace.tla` replays: a `commit` the first time a position is seen
present, an `abandon` per stepped-over hole, and an `advance` per real cursor move
(no-progress holds are dropped). `CheckpointTrace.tla` replays each through
`Checkpoint.tla`'s own `Commit` / `AgeGap` / `Tick` actions, requiring the recorded
watermark to equal the one `Tick` computes; if the code advanced past a held gap
(the #1088 bug), `Tick` holds where the recording claims it advanced, the replay
stalls, and `TraceAccepted` fails. The two negative fixtures mirror OCC's: a
gap-skip log (`traces/checkpoint_bug.jsonl`) is rejected on conformance, and an
in-order log (`traces/checkpoint_no_gap.jsonl`) leaves `CoverGap` holding and is
rejected as under-covered. The coverage probe `CoverGap == SafeWatermark = Frontier`
must be *violated* by a real log — that violation is a visible position stranded
above the watermark, the witness that the log actually exercised a gap.

### Recovery trace validation

The same harness, applied to the recovery protocol (#1385). The recorder
`src/protean/utils/recovery_trace.py` is a sibling of `occ_trace.py`, inactive by
default. When a capture is active, the real `EventStoreSubscription` recovery path
emits the transitions `Recovery.tla` talks about, in order: `handle_ok` (a non-failed
advance), `fail`, `record` (a durable `Failed` write), `advance` (past a failed
position), `flush` (a durable cursor checkpoint), and `recover` (a recovery-pass
terminal, carrying whether it delivered). A `crash` is a process event, not a code
branch, so the recording harness records it at the point it drops and rebuilds the
subscription.

`RecoveryTrace.tla` (`EXTENDS Recovery`) replays each entry through `Recovery.tla`'s
own actions, advancing a pointer. Two points differ from OCC:

- **`fate` is pinned from the trace.** `Recovery!Init` picks the per-position
  success/failure pattern nondeterministically; `RecoveryTrace`'s `TInit` fixes
  `fate[p] = "F"` for exactly the positions the log fails, `"S"` otherwise, so
  `<>AtEnd` is checked only against the pattern the log actually observed.
- **the recorded `recover` outcome is cross-checked**, pinning the branch of
  `Recovery!Recover` (delivered or exhausted) the real pass took, exactly as OCC's
  trace validation pins the commit verdict.

The conformance catch is free from the real spec: under `RecordFirst = TRUE`,
`Recovery!Advance` is gated on the durable record existing first, so a log that
advanced past a failed position with no record leaves `Advance` disabled, the replay
stalls, and `TraceAccepted` fails. The coverage check is `NoRedeliver`, which TLC
must *violate*: a real trace has to witness a crash after the record but before the
durable flush that re-reads the recorded failed position (the exact window the
protocol exists for). A
log with no such crash leaves `NoRedeliver` holding and is rejected as under-covered.
`check.sh` runs all three — a fresh recorded trace accepted, `traces/recovery_
divergence.jsonl` rejected on conformance, `traces/recovery_no_crash.jsonl` rejected
on coverage.

### Outbox trace validation

The same harness, applied to the transactional outbox (#1383). The recorder
`src/protean/utils/outbox_trace.py` is a sibling of `occ_trace.py`, inactive by
default. When a capture is active, the real outbox path emits the transitions
`Outbox.tla` talks about, in order: `claim` (a row atomically claimed and marked
PROCESSING under a lock, from the production `OutboxRepository.claim_batch`),
`publish` (the broker publish, carrying `ok`/`fail`), and `mark` (the terminal status
set in the commit, carrying `published`/`failed`/`abandoned`). A `crash` (a worker
dropping a message before the mark) and a `lock_expire` (a crashed row's lock
lapsing) are process and time events, not code branches, so the harness records them.

`OutboxTrace.tla` (`EXTENDS Outbox`) replays each entry through `Outbox.tla`'s own
`Claim` / `Publish` / `MarkPublished` / `MarkFailed` / `Crash` / `LockExpire`
actions, advancing a pointer. The config binds the shipped constants
(`AckBeforePublish = FALSE`, `ClaimSafe = TRUE`), so the replay uses the shipped
actions: the ack-before-publish bug actions (`MarkFirst`/`PublishAfter`) are
disabled, and `ClaimSafe = TRUE` keeps the `Claim` guard exclusive. Two
recorded outcomes are cross-checked, pinning the branch the real code took: `publish`
pins the `Publish` disjunction (`ok` reaches `pubok`, `fail` reaches `pubfail`), and a
failing `mark` pins the `MarkFailed` terminal (`abandoned` reaches ABANDONED,
`failed` does not) — exactly as OCC's trace validation pins the commit verdict.

The conformance catch is free from the real spec: `MarkPublished` is gated on the
worker being in `pubok`, so a log that marks a row PUBLISHED without a preceding
successful publish leaves it in `claimed`, the action is disabled, the replay stalls,
and `TraceAccepted` fails — the phantom-delivery divergence `PublishedImpliesDelivered`
forbids. The coverage check is `NoDuplicateDelivery` (the same probe `Outbox_dup.cfg`
uses), which TLC must *violate*: a real trace has to witness a crash after the broker
publish but before the mark, then a reclaim and republish (the at-least-once window
the protocol exists for). A log with no such redelivery leaves `NoDuplicateDelivery`
holding and is rejected as under-covered. `check.sh` runs all three — a fresh recorded
trace accepted, `traces/outbox_divergence.jsonl` rejected on conformance,
`traces/outbox_no_redelivery.jsonl` rejected on coverage.

### Adding a protocol

The harness generalizes. All four current protocol specs (OCC, Checkpoint,
Recovery, Outbox) now have one; to trace-validate a spec added later:

1. Add the raw fields the spec talks about to the recorder (or a sibling
   recorder), and emit them from the real path under its lock/transaction.
2. Write `<Spec>Trace.tla`: `EXTENDS <Spec>`, read a `Trace` constant, and replay
   each entry through the spec's own actions, cross-checking the recorded outcome.
   Reuse the spec's invariants and reachability probes rather than restating them.
3. Add a converter path (or reuse `occ_trace.py`'s `to-tla`) and the `check.sh`
   plumbing: a conformance cfg (the accept property), a coverage cfg (a reachability
   probe that must be witnessed), and fixtures for the two negative checks.

## Files

| File | What it is |
|---|---|
| `Checkpoint.tla` | The `$all` gap-safe checkpoint protocol. |
| `Checkpoint.cfg` | Shipped fix within its stated regime; all invariants + liveness hold. |
| `Checkpoint_timeout.cfg` | The documented timeout trade-off (a slow commit can be dropped, but never silently). |
| `Checkpoint_bug.cfg` | Revert test: reintroduces the gap-skip bug; TLC must fail on `NoSkip`. |
| `Checkpoint_dup.cfg` | Reachability probe: TLC must fail on `NoRedelivery`, witnessing crash-resume redelivery. |
| `Outbox.tla` | The transactional outbox two-phase publish. |
| `Outbox.cfg` | Shipped ordering (publish then mark); all invariants + liveness hold. |
| `Outbox_bug.cfg` | Revert test: mark then publish; TLC must fail on `PublishedImpliesDelivered`. |
| `Outbox_claim.cfg` | Revert test: an unguarded claim; TLC must fail on `NoDoubleActiveClaim`. |
| `Outbox_dup.cfg` | Reachability probe: TLC must fail on `NoDuplicateDelivery`, witnessing at-least-once duplicates. |
| `OCC.tla` | The aggregate optimistic-concurrency no-lost-update protocol (the atomic compare-and-set). |
| `OCC.cfg` | Shipped protocol (atomic compare-and-set); all invariants + liveness hold. |
| `OCC_bug.cfg` | Revert test: split the commit into compare then unconditional write; TLC must fail on `NoLostUpdate`. |
| `OCC_conflict.cfg` | Reachability probe: TLC must fail on `NoConflict`, witnessing that two writers genuinely contend from the same base. |
| `Recovery.tla` | The subscription failure-recovery record-before-advance protocol. |
| `Recovery.cfg` | Shipped protocol (record before advance); all invariants + liveness hold. |
| `Recovery_bug.cfg` | Revert test: advance the cursor past a failed message without its record; TLC must fail on `NoDrop`. |
| `Recovery_dup.cfg` | Reachability probe: TLC must fail on `NoRedeliver`, witnessing a crash-resume re-reading an already-recorded failed message. |
| `OCCTrace.tla` | Trace validation for OCC: replays a recorded log through `OCC!Commit` and checks it is a behaviour `OCC.tla` permits (#1382). |
| `OCCTrace_conform.cfg` | Conformance check: `TraceAccepted` holds iff the whole recorded log matched an OCC verdict. |
| `OCCTrace_cover.cfg` | Coverage check: `NoConflict` must be *violated*, witnessing the log actually exercised contention. |
| `occ_trace.py` | Records a real Memory-adapter OCC trace, and converts a JSON-lines log into a runnable `OCCTrace_*.tla`. |
| `traces/occ_bug.jsonl` | Negative fixture: a seeded lost update (two commits from one base); conformance must reject it. |
| `traces/occ_no_conflict.jsonl` | Negative fixture: an uncontended log; the coverage check must reject it as under-covered. |
| `CheckpointTrace.tla` | Trace validation for the checkpoint: replays a recorded log through `Checkpoint!Commit` / `AgeGap` / `Tick` and checks it is a behaviour `Checkpoint.tla` permits (#1384). |
| `CheckpointTrace_conform.cfg` | Conformance check: `TraceAccepted` holds iff the whole recorded log matched a Checkpoint action. Also checks `NoSilentSkip`. |
| `CheckpointTrace_cover.cfg` | Coverage check: `CoverGap` must be *violated*, witnessing the log stranded a visible position above the watermark behind a gap. |
| `checkpoint_trace.py` | Records a real `_gap_safe_batch` trace, and converts a JSON-lines log into a runnable `CheckpointTrace_*.tla`. |
| `traces/checkpoint_bug.jsonl` | Negative fixture: a gap-skip advance past a still-open gap; conformance must reject it. |
| `traces/checkpoint_no_gap.jsonl` | Negative fixture: an in-order (gapless) log; the coverage check must reject it as under-covered. |
| `RecoveryTrace.tla` | Trace validation for recovery: replays a recorded log through `Recovery.tla`'s actions and checks it is a behaviour the spec permits (#1385). |
| `RecoveryTrace_conform.cfg` | Conformance check: `TraceAccepted` holds iff the whole recorded log matched a `Recovery` action. |
| `RecoveryTrace_cover.cfg` | Coverage check: `NoRedeliver` must be *violated*, witnessing a crash after the record but before the durable flush re-read the failed message. |
| `recovery_trace.py` | Records a real recovery trace, and converts a JSON-lines log into a runnable `RecoveryTrace_*.tla`. |
| `traces/recovery_divergence.jsonl` | Negative fixture: an advance past a failed position with no durable record; conformance must reject it. |
| `traces/recovery_no_crash.jsonl` | Negative fixture: a log with a durable flush but no crash redelivery; conformance (including `Flush`) holds, so the coverage check must reject it as under-covered. |
| `OutboxTrace.tla` | Trace validation for the outbox: replays a recorded log through `Outbox.tla`'s `Claim` / `Publish` / `MarkPublished` / `MarkFailed` / `Crash` / `LockExpire` actions and checks it is a behaviour `Outbox.tla` permits (#1383). |
| `OutboxTrace_conform.cfg` | Conformance check: `TraceAccepted` holds iff the whole recorded log matched an Outbox action. |
| `OutboxTrace_cover.cfg` | Coverage check: `NoDuplicateDelivery` must be *violated*, witnessing the log re-published a message after a crash. |
| `outbox_trace.py` | Records a real OutboxProcessor crash-redelivery trace, and converts a JSON-lines log into a runnable `OutboxTrace_*.tla`. |
| `traces/outbox_divergence.jsonl` | Negative fixture: a row marked published with no preceding successful publish; conformance must reject it. |
| `traces/outbox_no_redelivery.jsonl` | Negative fixture: a single publish-then-mark with no crash redelivery; the coverage check must reject it as under-covered. |
| `check.sh` | Runs every config, asserts the expected pass/violation, and runs OCC, checkpoint, recovery, and outbox trace validation. |

## What is modeled

All four specs are written as action-based TLA+ (a disjunction of next-state
actions) rather than PlusCal. For fault-tolerant protocols the interesting
behavior is a *crash between phases*, which is expressed directly by separating
durable state from volatile state and having a `Crash` action clear only the
volatile part. That is the idiomatic and auditable shape for this kind of spec;
PlusCal would compile down to the same TLA+.

**Checkpoint.** `global_position` is a store-wide sequence assigned at insert (in
order) but made visible at commit, and across categories a lower value can commit
after a higher one. `Commit(p)` makes a commit-fated position visible in any
order, which is exactly the gap. The subscription processes the contiguous run
from its cursor and holds at the first gap. A gap that stays unfilled past
`gap_timeout_seconds` is abandoned (a rolled-back append leaves a permanent
hole). `Flush` writes the durable checkpoint; `Crash` resets the in-memory cursor
to the durable one, so resume re-reads rather than skips. The `GapSafe` constant
toggles the fix against the gap-skip bug (advance to the highest seen). The
`AbandonScope` constant chooses whether a gap can age out only on a genuine hole
(`"holes"`, modeling `gap_timeout_seconds` >= commit latency) or on any unfilled
position (`"all"`, modeling a commit slower than the timeout).

**Outbox.** Concurrent workers each claim a row atomically (marking it
`PROCESSING` under a time-boxed lock), publish it to the broker, then mark it
`PUBLISHED` (or `FAILED`/`ABANDONED`). A claimed row is `PROCESSING` under a live
lock, so no second worker can claim it. `Crash` drops a worker's in-flight
message without marking it; the lock later expires and the row is reclaimable, so
a crash after the publish but before the mark re-delivers (at-least-once, with
duplicates that handlers must tolerate). The `AckBeforePublish` constant toggles
the shipped ordering (publish then mark) against the classic bug (mark then
publish); the `ClaimSafe` constant toggles the guarded claim against an unguarded
one so the no-double-claim invariant has a demonstrable failure.

**OCC.** Two concurrent writers each update one aggregate. Each `Read`s the stored
version as its expected base, then `Commit`s. Under the shipped protocol the commit
is a single indivisible compare-and-set: advance the stored version to base + 1
only if it is still the base, else conflict (`ExpectedVersionError`). One writer per
base wins; the rest conflict. This one atomic action is the faithful abstraction of
both shipped fixes: the SQL `version_id_col` flush (`UPDATE … SET _version = <b+1>
WHERE _version = :b`, zero rows → conflict, #1087) and the Memory
`MemorySession.commit` compare-and-set under the provider lock (#1258). Per ADR-0013
the aggregate root is the single concurrency boundary, so one version cell is the
right granularity and one parameterized model covers both adapters. The `Atomic`
constant toggles the shipped compare-and-set against the bug: when `FALSE` the commit
splits into a `Compare` step (decide "ok" without writing) and a later unconditional
`Write` (set the version to the stale base + 1), so two writers that both read base
`b` both write `b + 1` and one committed update is silently overwritten. That split
is the read-compare-write race of #1087 / #1258.

**Recovery.** When the handler fails on the message at the cursor, the failure is
written durably to the failed-positions stream (`Record`) *before* the read cursor
advances past it (`Advance`). The cursor's durable checkpoint is batched, so
`Flush` copies the in-memory cursor to the durable one at any time, and a `Crash`
resets the in-memory cursor to the durable one and drops the volatile pending
state (the durable Failed records, the resolved set, and delivered side effects
all survive, matching `_rebuild_retry_counts` rebuilding from the stream on
restart). A periodic `Recover` pass takes each recorded, unresolved position
terminal — resolved on a retry success, or given up (an abstraction of exhausting
`max_retries`; the retry count and the stream reconstruction are not modeled, see
"Out of scope"). The
`RecordFirst` constant toggles the shipped ordering (record before advance)
against the bug: when `FALSE` the cursor can advance past a failed message without
its record, so a `Flush` and `Crash` there leave the durable cursor past a failed
position with no durable record and no delivery — a silent drop.

## Invariant-to-guarantee mapping

Each modeled invariant corresponds to a stated guarantee in
[`docs/reference/guarantees.md`](../docs/reference/guarantees.md) (the per-port
contract, #1200). Where a property here and that page disagree, the page is the
oracle. Three kinds of check appear below: **guarantee** invariants (the real
promises), **model-trust** invariants (should hold by construction; a failure
signals a modeling bug, not a protocol bug), and **reachability probes** (asserted
negations whose counterexample witnesses that a behavior is reachable).

### Checkpoint (`Checkpoint.tla`) → guarantees.md, "Subscriptions & delivery"

| Invariant / property | Kind | Guarantee it checks |
|---|---|---|
| `NoSkip` | guarantee | "No silent skip for `$all`": no committed `$all` event is skipped. Strong form, within the timeout regime (a gap timer fires only on a genuine hole). #1088 / [ADR-0025](../docs/adr/0025-all-subscription-gap-safety.md). |
| `NoSilentSkip` | guarantee | The full sentence: "no committed `$all` event is silently skipped; a genuinely slow commit (> `gap_timeout_seconds`) is logged and dropped." A dropped position is always recorded (logged), never silent. Holds even under the timeout trade-off. |
| `DurableBehindCursor` | guarantee | The durable checkpoint never leads the in-memory cursor, so a crash-resume re-reads from before a gap rather than skipping it (the crash-safety consequence of ADR-0025). |
| `DeliveredAreVisible` | model-trust | A position is only ever delivered after it committed and became visible (the inclusive, ordered read-position contract, [ADR-0024](../docs/adr/0024-event-store-read-position-contract.md)). |
| `VisibleAreCommitted` | model-trust | Only committed positions ever become visible; guards against a rolled-back position leaking into `delivered` unnoticed. |
| `NoRedelivery` (probe, `Checkpoint_dup.cfg`) | reachability | "Asynchronous delivery is at-least-once ... a crash re-delivers ... Handlers must tolerate duplicates." The witness is a crash-resume that redelivers an already-handled position. |
| `AllCommittedDelivered` (liveness) | guarantee | No permanent stall; a held gap resolves and processing resumes, so every committed position is eventually delivered. |

### Outbox (`Outbox.tla`) → guarantees.md, "Outbox"

| Invariant / property | Kind | Guarantee it checks |
|---|---|---|
| `PublishedImpliesDelivered` | guarantee | Delivery: "At-least-once to the broker: a crash after `broker.publish` but before the row is marked published re-delivers." A row is never marked published unless the broker actually received it, so a crash re-delivers rather than dropping. |
| `NoDoubleActiveClaim` | guarantee | "The `_claim` contract ([ADR-0013](../docs/adr/0013-optimistic-concurrency-and-claim-contract.md)) guarantees no double-claim." At most one worker holds a message at a time. `Outbox_claim.cfg` reverts the claim guard to demonstrate TLC catches a double-claim. |
| `AbandonedAfterRetries` | guarantee | Terminal state: "After `max_retries` ... marked `abandoned`, permanently not delivered, retained." Abandonment is only ever reached by exhausting retries. |
| `LockImpliesProcessing` | model-trust | A live claim lock exists only on a row that is actually being processed. |
| `WorkerStateAgree` | model-trust | A worker is idle exactly when it holds no message (`phase` and `busy` never drift apart). |
| `DuplicatedArePublished` | model-trust | A duplicate is a repeat receipt, so the duplicate set can never exceed the published set. |
| `NoDuplicateDelivery` (probe, `Outbox_dup.cfg`) | reachability | Delivery: at-least-once means "handlers must tolerate duplicates." The witness is a crash-after-publish, reclaim, and republish, so a message reaches the broker twice. |
| `EventuallyResolved` (liveness) | guarantee | No permanent stall: every message eventually reaches a terminal state (`PUBLISHED` or `ABANDONED`). |

### OCC (`OCC.tla`) → guarantees.md, "No lost update" (#1087 SQL, #1258 Memory)

| Invariant / property | Kind | Guarantee it checks |
|---|---|---|
| `NoLostUpdate` | guarantee | "The aggregate OCC check is atomic with the write ... so two concurrent updates can no longer both succeed and silently drop one" (#1087, #1258; [ADR-0013](../docs/adr/0013-optimistic-concurrency-and-claim-contract.md)). The stored version equals the number of successful commits, so no committed update was overwritten. `OCC_bug.cfg` splits the commit to demonstrate TLC catches the lost update. |
| `AtMostOneWinnerPerBase` | guarantee | The same promise restated over the base version: at most one writer that read a given base commits; every other writer from that base conflicts. The essence of "no lost update" at the compare-and-set. |
| `VersionMonotonic` | model-trust | The stored version never decreases; it always sits at the highest version any commit has reached. Holds at the two-writer bound `OCC_bug.cfg` checks, including under the split-commit bug there, so it cannot pre-empt `NoLostUpdate` in that revert run. Not general: with three or more writers a delayed write from a stale base can drop the version below a value already reached. |
| `ConflictImpliesStale` | model-trust | A writer only conflicts when the stored version has already moved past its base (a genuinely stale expected version), never on a fresh read. Holds at the two-writer bound the configs check, under both the atomic protocol and the split-commit bug. Not general: with three or more writers a delayed stale write can drop the version below a later reader's base, so that reader conflicts with its base at or above the stored version. |
| `NoConflict` (probe, `OCC_conflict.cfg`) | reachability | The witness that two writers genuinely race from the same base and one is forced to conflict, so the model is not vacuously safe and the revert test is meaningful. |
| `EventuallyResolved` (liveness) | guarantee | No permanent stall: every writer eventually reaches a terminal state (committed or conflicted). |

### Recovery (`Recovery.tla`) → guarantees.md, "Recovery of a failed message is crash-safe"

| Invariant / property | Kind | Guarantee it checks |
|---|---|---|
| `NoDrop` | guarantee | "The failure is recorded to the recovery stream *before* the read cursor advances past it ... never dropped." A failed position the durable cursor has passed is either present as a durable Failed record (the recovery pass picks it up) or already delivered. `Recovery_bug.cfg` advances past a failed message without its record to demonstrate TLC catches the drop. |
| `DurableBehindCursor` | guarantee | The durable checkpoint never leads the in-memory cursor, so a crash-resume re-reads from a safe position rather than skipping past a failed message. |
| `RecordedAreFailed` | model-trust | Only genuinely failed positions ever get a durable record; guards against a successful position leaking into the record set and making `NoDrop` pass for the wrong reason. |
| `ResolvedImpliesRecorded` | model-trust | The recovery pass only ever resolves a position that has a durable record; a resolve out of nowhere would be a modeling bug. |
| `DeliveredImpliesHandled` | model-trust | Every delivered position was actually handled — a success on the first pass, or a recorded failed position recovered by the pass — so `NoDrop` cannot pass vacuously through its `delivered` disjunct. |
| `NoRedeliver` (probe, `Recovery_dup.cfg`) | reachability | "Asynchronous delivery is at-least-once ... Handlers must tolerate duplicates." The witness is a crash after the record but before the flush that rewinds the cursor and re-reads the failed message. |
| `AllFailedResolved` (liveness) | guarantee | No permanent stall: every failed message is eventually retried until it resolves (recovered) or is exhausted. |

## Revert tests and reachability probes

A spec that passes proves nothing unless its invariants can fail. Each protocol
carries a constant that reintroduces the real bug (`GapSafe`, `AckBeforePublish`,
`ClaimSafe`, `Atomic`, `RecordFirst`), and a probe that asserts the negation of a
reachable behavior (`NoRedelivery`, `NoDuplicateDelivery`, `NoConflict`,
`NoRedeliver`). `check.sh` asserts
TLC fails on the *named* invariant for each, so a check that stops demonstrating
its bug (say a different invariant fails first) is caught, not silently accepted.
The headline revert traces:

**Checkpoint, `GapSafe = FALSE` (the gap-skip bug).** With three committed
positions, position 2 becomes visible before position 1, the buggy cursor jumps
to the highest visible (2), and position 1 (committed) is stepped over and never
delivered:

```
State 1: fate = <<"C","C","C">>  visible = {}   cursor = 0  delivered = {}
State 2: Commit(2)               visible = {2}   cursor = 0  delivered = {}
State 3: Tick (advance-to-highest)
         visible = {2}  cursor = 2  delivered = {2}
         -> NoSkip violated: position 1 is committed and <= cursor but undelivered
```

**Outbox, `AckBeforePublish = TRUE` (mark before publish).** The row is marked
`PUBLISHED` before the broker publish, so the durable state claims a delivery that
never happened; a crash here loses the message permanently:

```
State 1: status = PENDING     published = {}   phase = idle
State 2: Claim                status = PROCESSING  phase = claimed
State 3: MarkFirst            status = PUBLISHED   published = {}  phase = marked
         -> PublishedImpliesDelivered violated: PUBLISHED but the broker has nothing
```

**OCC, `Atomic = FALSE` (split compare/write).** Both writers read base 0, both
pass the compare, then both write version 1 using their stale base, so two commits
succeed but the stored version only reaches 1 and one update is silently dropped:

```
State 1: version = 0  base = <<0,0>>  phase = <<start,   start>>
State 3: Read, Read   version = 0  base = <<0,0>>  phase = <<read,    read>>
State 5: Compare×2     version = 0  base = <<0,0>>  phase = <<checked, checked>>
State 6: Write(w1)     version = 1  base = <<0,0>>  phase = <<committed, checked>>
State 7: Write(w2)     version = 1  base = <<0,0>>  phase = <<committed, committed>>
         -> NoLostUpdate violated: two writers committed but version = 1
```

**Recovery, `RecordFirst = FALSE` (advance before record).** The handler fails on
position 1, the buggy cursor advances past it without writing the durable record,
and a flush moves the durable cursor past it too, so a crash there would lose the
message with no record to recover it:

```
State 1: fate = <<"F","S","S">>  cursorMem = 0  cursorDur = 0  recordDur = {}
State 2: Fail(1)                 cursorMem = 0  cursorDur = 0  recordDur = {}  pending = {1}
State 3: Advance(1)              cursorMem = 1  cursorDur = 0  recordDur = {}  pending = {}
State 4: Flush                   cursorMem = 1  cursorDur = 1  recordDur = {}
         -> NoDrop violated: position 1 is failed and <= cursorDur, with no
            durable record and not delivered
```

## Constants and bounds

The configs use small bounds (3 to 4 positions, 1 to 2 workers and messages, 2
writers, 1 crash) because the bug class is about *ordering*, and exhaustive
checking of a few positions covers every relevant interleaving. Two writers from
the same base is the minimal shape that generates the OCC lost-update
counterexample. Raising `N`, `Messages`, `Workers`, `Writers`, or `MaxCrashes` in a
`.cfg` explores a larger space at the cost of run time. TLC reports the state count
for each run.

## Out of scope

The following are related but deliberately not modeled here, and a reader arriving
from `guarantees.md` should not expect them:

- **Outbox write-side dedup on `(message_id, target_broker)`**. The model uses a
  single broker; the dual-write-per-broker uniqueness is a row-creation concern,
  not part of the publish protocol.
- **The startup reconciliation sweep** (ADR-0015), which is marked interim.
- **The recovery pass's retry machinery.** `Recovery.tla` proves the durable
  Failed record *survives a crash* (the record-before-advance ordering), not that
  the recovery pass then re-reads and retries it. `Recover` is an atomic,
  always-terminal step off the durable `recordDur`: the `retry_count` /
  `max_retries` threshold and the `_rebuild_retry_counts` watermark-and-snapshot
  reconstruction of `_failed_positions` from the stream are abstracted away. A bug
  in that reconstruction that dropped a still-unresolved position would leave
  `NoDrop` green, so it is outside this model.
- One nuance the model surfaces but does not assert: `ABANDONED` means the
  framework stops attempting delivery. Because delivery is at-least-once, a
  message published on an earlier attempt but not confirmed (a crash before the
  mark) may in fact have reached the broker before it was later abandoned.
