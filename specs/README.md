# Formal specs of Protean's core delivery protocols

This directory holds TLA+ specifications of the two two-phase protocols at the
heart of Protean's delivery guarantees, model-checked with TLC:

- **`Checkpoint.tla`**: the `$all` (cross-category) subscription checkpoint
  advance, the settle-then-process low-watermark shipped for #1088
  ([ADR-0025](../docs/adr/0025-all-subscription-gap-safety.md)).
- **`Outbox.tla`**: the transactional outbox two-phase publish (claim, publish
  to the broker, then mark the row).

They exist because these are where Protean's hardest correctness claims live, and
where two silent-corruption bugs surfaced this cycle: #1087 (OCC lost update) and
#1088 (`$all` checkpoint gap-skip). #1088 was an unconsidered-interleaving bug.
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
  invariants of either shipped protocol. The only counterexamples are the
  deliberate ones: the revert tests (which reintroduce a known bug) and the
  reachability probes (which witness that at-least-once redelivery is reachable).

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
`…_claim`, `…_dup`) must fail on its named invariant. It exits non-zero if any
expectation is unmet. Point it at a jar elsewhere with
`TLA_TOOLS=/path/to/tla2tools.jar ./check.sh`.

To run one configuration directly:

```bash
java -cp ~/.tla/tla2tools.jar tlc2.TLC -config Checkpoint.cfg Checkpoint.tla
```

From the repository root, `make verify-specs` delegates to this script.

The runs are small (a few thousand states each) and finish in about a second.

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
| `check.sh` | Runs every config and asserts the expected pass/violation. |

## What is modeled

Both specs are written as action-based TLA+ (a disjunction of next-state actions)
rather than PlusCal. For fault-tolerant protocols the interesting behavior is a
*crash between phases*, which is expressed directly by separating durable state
from volatile state and having a `Crash` action clear only the volatile part.
That is the idiomatic and auditable shape for this kind of spec; PlusCal would
compile down to the same TLA+.

**Checkpoint.** `global_position` is a store-wide sequence assigned at insert (in
order) but made visible at commit, and across categories a lower value can commit
after a higher one. `Commit(p)` makes a committed-fated position visible in any
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

## Revert tests and reachability probes

A spec that passes proves nothing unless its invariants can fail. Each protocol
carries a constant that reintroduces the real bug (`GapSafe`, `AckBeforePublish`,
`ClaimSafe`), and a probe that asserts the negation of a reachable behavior
(`NoRedelivery`, `NoDuplicateDelivery`). `check.sh` asserts TLC fails on the
*named* invariant for each, so a check that stops demonstrating its bug (say a
different invariant fails first) is caught, not silently accepted. The two
headline revert traces:

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

## Constants and bounds

The configs use small bounds (3 to 4 positions, 1 to 2 workers and messages, 1
crash) because the bug class is about *ordering*, and exhaustive checking of a few
positions covers every relevant interleaving. Raising `N`, `Messages`, `Workers`,
or `MaxCrashes` in a `.cfg` explores a larger space at the cost of run time. TLC
reports the state count for each run.

## Out of scope

The issue that produced these specs scoped them to the checkpoint and outbox
two-phase protocols only. The following are related but deliberately not modeled
here, and a reader arriving from `guarantees.md` should not expect them:

- **The subscription recovery-stream ordering** ("Recovery of a failed message is
  crash-safe" in guarantees.md). It has the same record-before-flush shape as the
  checkpoint, but it is a separate protocol (handler failure, not gap safety).
- **Outbox write-side dedup on `(message_id, target_broker)`**. The model uses a
  single broker; the dual-write-per-broker uniqueness is a row-creation concern,
  not part of the publish protocol.
- **The startup reconciliation sweep** (ADR-0015), which is marked interim.
- One nuance the model surfaces but does not assert: `ABANDONED` means the
  framework stops attempting delivery. Because delivery is at-least-once, a
  message published on an earlier attempt but not confirmed (a crash before the
  mark) may in fact have reached the broker before it was later abandoned.
