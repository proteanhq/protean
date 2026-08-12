-------------------------- MODULE OCCTrace --------------------------
(***************************************************************************)
(* Trace validation for the OCC protocol: check a log of the *real code's*   *)
(* observed compare-and-sets against `OCC.tla`.                              *)
(*                                                                          *)
(* `OCC.tla` states what the aggregate optimistic-concurrency protocol is     *)
(* allowed to do; TLC never reads the Python, so nothing there confirms the    *)
(* shipped adapters behave the way the model says. This module closes that gap  *)
(* the other way round. `Trace` is a recorded log: one entry per unit of work,  *)
(* in commit order, each holding the raw values the real commit path observed   *)
(* (`src/protean/utils/occ_trace.py`): the version the writer read as its base,  *)
(* the outcome ("committed" or "conflicted"), and the stored version it left     *)
(* behind. The instrumentation and the conversion to this constant live in       *)
(* `specs/occ_trace.py`; `specs/check.sh` drives the whole check.                 *)
(*                                                                          *)
(* The judge is `OCC.tla` itself, not a re-encoding of the protocol. Each       *)
(* recorded unit of work is replayed as a `Read` that captures the recorded      *)
(* base and then the real `OCC!Commit` action, whose verdict (committed or       *)
(* conflicted, and the resulting stored version) must match what was recorded.   *)
(* If the code diverged from the protocol, `OCC!Commit`'s verdict disagrees with *)
(* the recording, the step is disabled, the log cannot be consumed, and          *)
(* `TraceAccepted` fails on the first step no spec action explains.              *)
(*                                                                          *)
(* Two negative checks keep a green run honest, exactly mirroring the model's    *)
(* own revert test and reachability probe (see `specs/README.md`):              *)
(*                                                                          *)
(*   - a seeded divergence (a lost update: two "committed" entries from the same *)
(*     base) makes `TraceAccepted` fail, because `OCC!Commit` conflicts the       *)
(*     second one where the recording claims it committed; and                    *)
(*   - `NoConflict` (imported from `OCC.tla`) must be *violated* by a real log,   *)
(*     which witnesses that the log actually exercised contention. A log with no  *)
(*     conflict leaves `NoConflict` holding, and `check.sh` rejects it as         *)
(*     under-covered.                                                            *)
(***************************************************************************)
EXTENDS OCC, Sequences

CONSTANT
    Trace   \* Seq of [w |-> writer, base |-> Nat, outcome |-> "committed"|"conflicted",
            \* after |-> Nat]: the recorded log, one entry per unit of work in commit order.

VARIABLE
    ti      \* 1-based read pointer into Trace; the log is consumed when it passes the end

tvars == <<version, high, base, phase, ti>>

TInit == Init /\ ti = 1

AtEnd == ti > Len(Trace)

(***************************************************************************)
(* Replay the recorded Read: this writer observed `Trace[ti].base` as its       *)
(* version. This is faithful to `OCC!Read`, which captures the stored version at *)
(* some earlier point; the recorded base must be a version the cell actually      *)
(* reached, which under the monotonic protocol means `base <= high`.             *)
(* No explicit read/commit phase counter is needed: each entry uses a distinct    *)
(* writer, so this writer's own `phase` ("start" -> "read" -> terminal) already    *)
(* forces the Read then the Commit, in order.                                     *)
(***************************************************************************)
DoRead ==
    /\ ~AtEnd
    /\ phase[Trace[ti].w] = "start"
    /\ Trace[ti].base <= high
    /\ base'  = [base  EXCEPT ![Trace[ti].w] = Trace[ti].base]
    /\ phase' = [phase EXCEPT ![Trace[ti].w] = "read"]
    /\ UNCHANGED <<version, high, ti>>

(***************************************************************************)
(* Replay the recorded Commit by taking the real `OCC!Commit` action, then       *)
(* require its verdict to match the recording: the primed phase must equal the    *)
(* recorded outcome, and on a commit the resulting stored version must equal the   *)
(* recorded `after`. `Commit` is only enabled once `DoRead` has set this writer's  *)
(* phase to "read". When the code diverges, `OCC!Commit` and the recording         *)
(* disagree, this action is disabled, and the log stalls here.                    *)
(***************************************************************************)
DoCommit ==
    /\ ~AtEnd
    /\ Commit(Trace[ti].w)
    /\ phase'[Trace[ti].w] = Trace[ti].outcome
    /\ (Trace[ti].outcome = "committed" => version' = Trace[ti].after)
    /\ ti' = ti + 1

Progress == DoRead \/ DoCommit

\* Stutter once the whole log is consumed, so a fully-replayed trace does not
\* deadlock; a stalled (diverging) trace has no enabled step and cannot reach here.
TNext == Progress \/ (AtEnd /\ UNCHANGED tvars)

\* Weak fairness on Progress forces the replay forward while a step is enabled, so
\* the only way `AtEnd` is never reached is a genuine stall at a diverging entry.
TSpec == TInit /\ [][TNext]_tvars /\ WF_tvars(Progress)

(***************************************************************************)
(* The conformance property: the whole log is a behaviour of `OCC.tla`, i.e. the *)
(* read pointer reaches the end. Violated exactly when some recorded step matches  *)
(* no `OCC!Commit` verdict.                                                        *)
(***************************************************************************)
TraceAccepted == <>AtEnd

\* The conformance config also checks `OCC.tla`'s own `NoLostUpdate` invariant
\* (imported via EXTENDS) on the replayed run, as a second, authoritative read on
\* the same log rather than trusting `TraceAccepted` alone.

=============================================================================
