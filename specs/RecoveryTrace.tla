------------------------- MODULE RecoveryTrace -------------------------
(***************************************************************************)
(* Trace validation for the recovery protocol: check a log of the *real       *)
(* code's* observed transitions against `Recovery.tla`.                        *)
(*                                                                          *)
(* `Recovery.tla` states what the record-before-advance protocol is allowed to  *)
(* do; TLC never reads the Python, so nothing there confirms the shipped        *)
(* `EventStoreSubscription` behaves the way the model says. This module closes   *)
(* that gap the other way round. `Trace` is a recorded log, in order, of the raw *)
(* transitions the real recovery path emitted (`src/protean/utils/recovery_     *)
(* trace.py`): a handler success (`handle_ok`), a handler failure (`fail`), a    *)
(* durable Failed record (`record`), a cursor advance past a failed position     *)
(* (`advance`), a durable cursor flush (`flush`), a recovery-pass terminal       *)
(* (`recover`, carrying whether it delivered), and a crash/resume (`crash`). The *)
(* instrumentation and the conversion to this constant live in                  *)
(* `specs/recovery_trace.py`; `specs/check.sh` drives the whole check.           *)
(*                                                                          *)
(* The judge is `Recovery.tla` itself: each recorded entry is replayed by taking  *)
(* the matching `Recovery` action at the entry's position, advancing a 1-based     *)
(* pointer `ti`. If the code diverged from the protocol, the matching action is    *)
(* disabled, the log cannot be consumed, and `TraceAccepted` fails on the first    *)
(* step no spec action explains. Two things are hand-authored on top of the        *)
(* spec's own actions, both disclosed below: `TInit` pins `fate` from the trace    *)
(* instead of exploring it, and `DoRecord` also accepts a re-record of an already-  *)
(* recorded position as a no-op on `recordDur` (a real recovery-retry or post-crash *)
(* re-record, which `Recovery!Record` does not model). The headline catch: under   *)
(* `RecordFirst = TRUE`, `Recovery!Advance` is gated on the durable record        *)
(* existing first, so a log that advanced past a failed position with no record    *)
(* leaves `Advance` disabled and the replay stalls — the seeded-divergence catch, *)
(* for free, from the real spec.                                                  *)
(*                                                                          *)
(* Two points where recovery differs from OCC's trace validation:                *)
(*                                                                          *)
(*   - `fate` is pinned from the trace. `Recovery!Init` picks `fate`             *)
(*     nondeterministically over every success/failure pattern; `<>AtEnd` would   *)
(*     then be checked over assignments that don't match the log. `TInit` fixes    *)
(*     `fate[p] = "F"` for exactly the positions the log fails, `"S"` otherwise.   *)
(*   - the recorded `recover` outcome is cross-checked: `Recovery!Recover` is a   *)
(*     disjunction (delivered or exhausted), so the recorded `delivered` pins the  *)
(*     branch, exactly as OCC's trace validation pins the commit verdict.          *)
(*                                                                          *)
(* Two negative checks keep a green run honest, mirroring OCC's:                 *)
(*                                                                          *)
(*   - a seeded advance-without-record (`traces/recovery_divergence.jsonl`) makes *)
(*     `TraceAccepted` fail, because `Advance` is disabled without the durable     *)
(*     record under `RecordFirst = TRUE`; and                                     *)
(*   - `NoRedeliver` (imported from `Recovery.tla`) must be *violated* by a real   *)
(*     log, which witnesses that a crash after the record but before the durable    *)
(*     flush re-read a recorded failed message (the exact window the protocol       *)
(*     exists for). A log with no such crash leaves `NoRedeliver` holding, and      *)
(*     `check.sh` rejects it as under-covered.                                      *)
(***************************************************************************)
EXTENDS Recovery, Sequences

CONSTANT
    Trace   \* Seq of [action |-> ..., pos |-> Nat, delivered |-> BOOLEAN]: the
            \* recorded log, one entry per observed transition, in order.

VARIABLE
    ti      \* 1-based read pointer into Trace; the log is consumed when it passes the end

tvars == <<fate, cursorMem, cursorDur, pending, recordDur,
           resolved, delivered, redelivered, crashes, ti>>

(***************************************************************************)
(* The positions the log records a handler failure on. `fate` is pinned from     *)
(* this: those positions fail (`"F"`), every other position succeeds (`"S"`).     *)
(* Deriving it from the trace, rather than a separate constant, keeps the log the  *)
(* single source of truth.                                                        *)
(***************************************************************************)
FailedPositions ==
    { Trace[i].pos : i \in { j \in DOMAIN Trace : Trace[j].action = "fail" } }

TInit ==
    /\ fate = [p \in Positions |-> IF p \in FailedPositions THEN "F" ELSE "S"]
    /\ cursorMem = 0
    /\ cursorDur = 0
    /\ pending = {}
    /\ recordDur = {}
    /\ resolved = {}
    /\ delivered = {}
    /\ redelivered = {}
    /\ crashes = 0
    /\ ti = 1

AtEnd == ti > Len(Trace)

(***************************************************************************)
(* Replay one recorded entry by taking the matching `Recovery` action at the      *)
(* entry's position, then advancing the pointer. Each action is only enabled when  *)
(* the recorded transition is one the spec permits from the current state; a       *)
(* divergence leaves no matching action enabled and the replay stalls here.        *)
(***************************************************************************)
DoHandleOk ==
    /\ ~AtEnd
    /\ Trace[ti].action = "handle_ok"
    /\ HandleOk(Trace[ti].pos)
    /\ ti' = ti + 1

DoFail ==
    /\ ~AtEnd
    /\ Trace[ti].action = "fail"
    /\ Fail(Trace[ti].pos)
    /\ ti' = ti + 1

\* A re-record of an already-recorded position is a legitimate real write that
\* `Recovery!Record` (guarded on `p \notin recordDur`) does not model. It happens two
\* real ways: the recovery retry re-records a still-failing position (advanced out of
\* `pending`), and a post-crash redelivery re-records a re-read position (fail put it
\* back in `pending`). Either way the durable-record *set* is unchanged, so this is a
\* no-op on `recordDur` rather than a `Record` transition. This is the one hand-
\* authored step that goes beyond `Recovery`'s own actions (see the header). It does
\* not weaken the advance-without-record catch: `recordDur` is monotonic, so a no-op
\* record can never *create* the durable record an `Advance` is gated on — a position
\* only reaches `recordDur` through a genuine `Record`, which requires it be pending.
DoRecord ==
    /\ ~AtEnd
    /\ Trace[ti].action = "record"
    /\ \/ Record(Trace[ti].pos)
       \/ (Trace[ti].pos \in recordDur /\ UNCHANGED vars)
    /\ ti' = ti + 1

DoAdvance ==
    /\ ~AtEnd
    /\ Trace[ti].action = "advance"
    /\ Advance(Trace[ti].pos)
    /\ ti' = ti + 1

DoFlush ==
    /\ ~AtEnd
    /\ Trace[ti].action = "flush"
    /\ Flush
    /\ ti' = ti + 1

\* Replay the recovery-pass terminal, then require its verdict to match the
\* recording: `delivered = TRUE` means the retry delivered (the position ends in
\* `delivered`), `FALSE` means it exhausted (it does not). `Recover` is a
\* disjunction, so this pins the branch the real pass took.
DoRecover ==
    /\ ~AtEnd
    /\ Trace[ti].action = "recover"
    /\ Recover(Trace[ti].pos)
    /\ (Trace[ti].delivered <=> Trace[ti].pos \in delivered')
    /\ ti' = ti + 1

DoCrash ==
    /\ ~AtEnd
    /\ Trace[ti].action = "crash"
    /\ Crash
    /\ ti' = ti + 1

Progress ==
    \/ DoHandleOk \/ DoFail \/ DoRecord \/ DoAdvance
    \/ DoFlush \/ DoRecover \/ DoCrash

\* Stutter once the whole log is consumed, so a fully-replayed trace does not
\* deadlock; a stalled (diverging) trace has no enabled step and cannot reach here.
TNext == Progress \/ (AtEnd /\ UNCHANGED tvars)

\* Weak fairness on Progress forces the replay forward while a step is enabled, so
\* the only way `AtEnd` is never reached is a genuine stall at a diverging entry.
TSpec == TInit /\ [][TNext]_tvars /\ WF_tvars(Progress)

(***************************************************************************)
(* The conformance property: the whole log is a behaviour of `Recovery.tla`,     *)
(* i.e. the read pointer reaches the end. Violated exactly when some recorded     *)
(* step matches no `Recovery` action from the state it was replayed into.         *)
(***************************************************************************)
TraceAccepted == <>AtEnd

\* The conformance config also checks `Recovery.tla`'s own safety invariants
\* (`TypeOK`, `NoDrop`, `DurableBehindCursor`, imported via EXTENDS) on the
\* replayed run, as a second, authoritative read on the same log. The coverage
\* config checks `NoRedeliver` must be *violated*, witnessing the redelivery from a
\* crash after the record but before the durable flush.

=============================================================================
