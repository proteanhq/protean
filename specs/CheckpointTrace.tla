------------------------- MODULE CheckpointTrace -------------------------
(***************************************************************************)
(* Trace validation for the ``$all`` gap-safe checkpoint: check a log of the *)
(* *real code's* observed cursor advance against `Checkpoint.tla`.           *)
(*                                                                          *)
(* `Checkpoint.tla` states what the settle-then-process low-watermark        *)
(* (ADR-0025, the #1088 gap-skip fix) is allowed to do; TLC never reads the   *)
(* Python, so nothing there confirms the shipped subscription behaves the way  *)
(* the model says. This module closes that gap the other way round. `Trace` is  *)
(* a recorded log: one entry per observable transition of the real            *)
(* `_gap_safe_batch` walk (`src/protean/utils/checkpoint_trace.py`), in the    *)
(* order the code produced them:                                             *)
(*                                                                          *)
(*   - a "commit" entry: a `global_position` the batch first saw present      *)
(*     (its transaction became visible);                                     *)
(*   - an "abandon" entry: a hole the batch stepped over after its gap timer  *)
(*     elapsed (a rolled-back append);                                       *)
(*   - an "advance" entry: the watermark the cursor actually moved to.        *)
(*                                                                          *)
(* `Fate` binds each modeled position's commit/rollback fate from the same    *)
(* recording (a committed position is "C", an abandoned one "R"), so the       *)
(* replay drives `Checkpoint.tla`'s own actions rather than re-deriving them.  *)
(* The conversion lives in `specs/checkpoint_trace.py`; `specs/check.sh`        *)
(* drives the whole check.                                                    *)
(*                                                                          *)
(* The judge is `Checkpoint.tla` itself, not a re-encoding. Each entry is       *)
(* replayed through the matching action: "commit" -> `Checkpoint!Commit`,      *)
(* "abandon" -> `Checkpoint!AgeGap`, "advance" -> `Checkpoint!Tick` with the    *)
(* recorded watermark required to equal the cursor `Tick` computes. Under the   *)
(* fix `Tick` moves the cursor to `SafeWatermark`; if the code diverged and     *)
(* advanced past a held gap (the #1088 bug), the recorded watermark is higher   *)
(* than `SafeWatermark`, `Tick` cannot satisfy `cursor' = safe`, the step is    *)
(* disabled, the replay stalls, and `TraceAccepted` fails on the first step no  *)
(* spec action explains.                                                       *)
(*                                                                          *)
(* Two negative checks keep a green run honest, mirroring the model's own       *)
(* revert test and reachability probe (see `specs/README.md`):                 *)
(*                                                                          *)
(*   - a seeded gap-skip divergence (an "advance" past a still-open gap) makes  *)
(*     `TraceAccepted` fail, because `Tick` holds at the gap where the           *)
(*     recording claims it advanced; and                                        *)
(*   - `CoverGap` must be *violated* by a real log, which witnesses that the     *)
(*     log actually exercised an out-of-order gap (a visible position stranded   *)
(*     above the settled watermark). An in-order log never strands one, leaves   *)
(*     `CoverGap` holding, and `check.sh` rejects it as under-covered.           *)
(***************************************************************************)
EXTENDS Checkpoint, Sequences

CONSTANTS
    Trace,  \* Seq of transitions: [kind |-> "commit"|"abandon", pos |-> Nat]
            \* or [kind |-> "advance", safe |-> Nat], in the order the code produced them.
    Fate    \* [Positions -> {"C","R"}]: each position's recorded fate (committed / rolled back).

VARIABLE
    ti      \* 1-based read pointer into Trace; the log is consumed when it passes the end.

tvars == <<fate, visible, gapAged, cursor, durable,
           delivered, redelivered, abandoned, crashes, ti>>

\* Pin `fate` to the recording so the replay drives the one commit/rollback
\* assignment the code actually observed, rather than every assignment `Init`
\* would otherwise explore (a conforming log would spuriously stall on the wrong
\* fate). Everything else starts from `Checkpoint!Init`.
TInit == Init /\ fate = Fate /\ ti = 1

AtEnd == ti > Len(Trace)

Cur == Trace[ti]

(***************************************************************************)
(* Replay a recorded "commit" through `Checkpoint!Commit`: the position became  *)
(* visible. `Commit` requires `fate[p] = "C"`, which `Fate` guarantees for a     *)
(* recorded commit, and that the position is not already visible, which the      *)
(* converter guarantees by emitting one commit per position.                    *)
(***************************************************************************)
DoCommit ==
    /\ ~AtEnd
    /\ Cur.kind = "commit"
    /\ Commit(Cur.pos)
    /\ ti' = ti + 1

(***************************************************************************)
(* Replay a recorded "abandon" through `Checkpoint!AgeGap`: the hole's gap       *)
(* timer elapsed. Under `AbandonScope = "holes"`, `AgeGap` requires               *)
(* `fate[p] = "R"`, which `Fate` guarantees for a recorded abandon.              *)
(***************************************************************************)
DoAbandon ==
    /\ ~AtEnd
    /\ Cur.kind = "abandon"
    /\ AgeGap(Cur.pos)
    /\ ti' = ti + 1

(***************************************************************************)
(* Replay a recorded "advance" through `Checkpoint!Tick`, then require the        *)
(* watermark `Tick` computed to equal the one the code recorded. `Tick` moves     *)
(* the cursor to `SafeWatermark` under the fix; if the code diverged (advanced     *)
(* past a held gap), `SafeWatermark` is below the recorded `safe`, `cursor' = safe` *)
(* is unsatisfiable, and this step is disabled — the built-in revert test.         *)
(* The converter drops no-progress ticks (`safe` equal to the running cursor), so  *)
(* every recorded advance makes real progress and `Tick` (which fires only when     *)
(* it advances) is enabled.                                                         *)
(***************************************************************************)
DoAdvance ==
    /\ ~AtEnd
    /\ Cur.kind = "advance"
    /\ Tick
    /\ cursor' = Cur.safe
    /\ ti' = ti + 1

Progress == DoCommit \/ DoAbandon \/ DoAdvance

\* Stutter once the whole log is consumed, so a fully-replayed trace does not
\* deadlock; a stalled (diverging) trace has no enabled step and cannot reach here.
TNext == Progress \/ (AtEnd /\ UNCHANGED tvars)

\* Weak fairness on Progress forces the replay forward while a step is enabled, so
\* the only way `AtEnd` is never reached is a genuine stall at a diverging entry.
TSpec == TInit /\ [][TNext]_tvars /\ WF_tvars(Progress)

(***************************************************************************)
(* The conformance property: the whole log is a behaviour of `Checkpoint.tla`,   *)
(* i.e. the read pointer reaches the end. Violated exactly when some recorded     *)
(* step matches no spec action (a diverging advance stalls the replay).           *)
(***************************************************************************)
TraceAccepted == <>AtEnd

\* The conformance config also checks `Checkpoint.tla`'s own `NoSilentSkip` safety
\* invariant (imported via EXTENDS) on the replayed run, as a second, authoritative
\* read on the same log rather than trusting `TraceAccepted` alone.

(***************************************************************************)
(* Reachability probe (NOT a safety property).                               *)
(*                                                                          *)
(* A green conformance run means nothing unless the log actually exercised an  *)
(* out-of-order gap. `CoverGap` asserts "the settled watermark always reaches   *)
(* the frontier", i.e. nothing is ever stranded above the cursor by a lower      *)
(* gap. TLC must find a counterexample, which witnesses that the recorded log    *)
(* stranded a visible position above the watermark — a real gap. An in-order log *)
(* never strands one, leaves `CoverGap` holding, and `check.sh` rejects it as     *)
(* under-covered. This is the checkpoint analog of OCC's `NoConflict` probe.      *)
(***************************************************************************)
CoverGap == SafeWatermark = Frontier

=============================================================================
