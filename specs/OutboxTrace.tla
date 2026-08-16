------------------------- MODULE OutboxTrace -------------------------
(***************************************************************************)
(* Trace validation for the transactional outbox: check a log of the *real    *)
(* code's* observed transitions against `Outbox.tla`.                          *)
(*                                                                          *)
(* `Outbox.tla` states what the claim/publish/mark two-phase protocol is allowed *)
(* to do; TLC never reads the Python, so nothing there confirms the shipped      *)
(* `OutboxProcessor` behaves the way the model says. This module closes that gap  *)
(* the other way round. `Trace` is a recorded log, in order, of the raw           *)
(* transitions the real outbox path emitted (`src/protean/utils/outbox_trace.py`):*)
(* a row claimed under a lock (`claim`), a broker publish that did or did not      *)
(* land (`publish`, carrying `ok`/`fail`), the row's terminal status set in the    *)
(* commit (`mark`, carrying the resulting status), a worker dropping a message     *)
(* mid-flight (`crash`), and a crashed row's lock lapsing (`lock_expire`). The     *)
(* instrumentation and the conversion to this constant live in                    *)
(* `specs/outbox_trace.py`; `specs/check.sh` drives the whole check.               *)
(*                                                                          *)
(* The judge is `Outbox.tla` itself: each recorded entry is replayed by taking    *)
(* the matching `Outbox` action, advancing a 1-based pointer `ti`. If the code     *)
(* diverged from the protocol, the matching action is disabled, the log cannot be  *)
(* consumed, and `TraceAccepted` fails on the first step no spec action explains.  *)
(* The config binds the shipped constants (`AckBeforePublish = FALSE`,             *)
(* `ClaimSafe = TRUE`), so the replay uses the shipped `Publish`/`MarkPublished`/  *)
(* `MarkFailed`/`Claim` actions: the ack-before-publish bug actions (`MarkFirst`   *)
(* and `PublishAfter`) are disabled, and `ClaimSafe = TRUE` keeps the `Claim`      *)
(* guard exclusive, exactly as the real code behaves.                             *)
(*                                                                          *)
(* Two recorded outcomes are cross-checked, so the replay pins the branch the real *)
(* code took rather than exploring both, as OCC's trace validation pins the commit *)
(* verdict:                                                                        *)
(*                                                                          *)
(*   - `publish` pins the `Publish` disjunction: `ok` requires the worker reach    *)
(*     `pubok` (the broker received it), `fail` requires `pubfail`; and            *)
(*   - a failing `mark` pins the `MarkFailed` terminal: `abandoned` requires the   *)
(*     row reach ABANDONED, `failed` requires it not.                             *)
(*                                                                          *)
(* The headline catch: a log that marks a row PUBLISHED without a preceding        *)
(* successful publish leaves the worker in `claimed`, where `MarkPublished`        *)
(* (guarded on `phase = "pubok"`) is disabled, so the replay stalls — the          *)
(* phantom-delivery divergence the spec's `PublishedImpliesDelivered` forbids,     *)
(* caught for free from the real spec.                                            *)
(*                                                                          *)
(* Two negative checks keep a green run honest, mirroring OCC's and recovery's:    *)
(*                                                                          *)
(*   - a seeded mark-without-publish (`traces/outbox_divergence.jsonl`) makes      *)
(*     `TraceAccepted` fail, because `MarkPublished` is disabled without a          *)
(*     successful publish first; and                                              *)
(*   - `NoDuplicateDelivery` (imported from `Outbox.tla`, the same probe           *)
(*     `Outbox_dup.cfg` uses) must be *violated* by a real log, which witnesses    *)
(*     that a crash after the broker publish but before the mark re-published the  *)
(*     message (the at-least-once window the protocol exists for). A log with no   *)
(*     such redelivery leaves `NoDuplicateDelivery` holding, and `check.sh`         *)
(*     rejects it as under-covered.                                              *)
(***************************************************************************)
EXTENDS Outbox, Sequences

CONSTANT
    Trace   \* Seq of [action |-> ..., worker |-> Nat, msg |-> Nat, outcome |-> ...]:
            \* the recorded log, one entry per observed transition, in order.

VARIABLE
    ti      \* 1-based read pointer into Trace; the log is consumed when it passes the end

tvars == <<status, retry, lockLive, published, duplicated, busy, phase, crashes, ti>>

TInit == Init /\ ti = 1

AtEnd == ti > Len(Trace)

(***************************************************************************)
(* Replay one recorded entry by taking the matching `Outbox` action, then          *)
(* advancing the pointer. Each action is only enabled when the recorded transition  *)
(* is one the spec permits from the current state; a divergence leaves no matching  *)
(* action enabled and the replay stalls here.                                       *)
(***************************************************************************)
DoClaim ==
    /\ ~AtEnd
    /\ Trace[ti].action = "claim"
    /\ Claim(Trace[ti].worker, Trace[ti].msg)
    /\ ti' = ti + 1

\* Replay the publish, then require its outcome to match the recording: `ok` pins the
\* success branch (the worker reaches `pubok`, the broker received the message),
\* `fail` pins the failure branch (`pubfail`). `Publish` is a disjunction, so this
\* fixes the branch the real attempt took.
DoPublish ==
    /\ ~AtEnd
    /\ Trace[ti].action = "publish"
    /\ Publish(Trace[ti].worker, Trace[ti].msg)
    /\ phase'[Trace[ti].worker] =
           IF Trace[ti].outcome = "ok" THEN "pubok" ELSE "pubfail"
    /\ ti' = ti + 1

DoMarkPublished ==
    /\ ~AtEnd
    /\ Trace[ti].action = "mark"
    /\ Trace[ti].outcome = "published"
    /\ MarkPublished(Trace[ti].worker, Trace[ti].msg)
    /\ ti' = ti + 1

\* Replay a failing mark, then require its terminal to match the recording:
\* `abandoned` means retries were exhausted (the row reaches ABANDONED), `failed`
\* means it will retry (it does not). `MarkFailed` computes the terminal from the
\* attempt count, so this pins that the recorded status is the one the spec derives.
DoMarkFailed ==
    /\ ~AtEnd
    /\ Trace[ti].action = "mark"
    /\ Trace[ti].outcome \in {"failed", "abandoned"}
    /\ MarkFailed(Trace[ti].worker, Trace[ti].msg)
    /\ (status'[Trace[ti].msg] = "ABANDONED") = (Trace[ti].outcome = "abandoned")
    /\ ti' = ti + 1

DoCrash ==
    /\ ~AtEnd
    /\ Trace[ti].action = "crash"
    /\ Crash(Trace[ti].worker)
    /\ ti' = ti + 1

DoLockExpire ==
    /\ ~AtEnd
    /\ Trace[ti].action = "lock_expire"
    /\ LockExpire(Trace[ti].msg)
    /\ ti' = ti + 1

Progress ==
    \/ DoClaim \/ DoPublish \/ DoMarkPublished \/ DoMarkFailed
    \/ DoCrash \/ DoLockExpire

\* Stutter once the whole log is consumed, so a fully-replayed trace does not
\* deadlock; a stalled (diverging) trace has no enabled step and cannot reach here.
TNext == Progress \/ (AtEnd /\ UNCHANGED tvars)

\* Weak fairness on Progress forces the replay forward while a step is enabled, so
\* the only way `AtEnd` is never reached is a genuine stall at a diverging entry.
TSpec == TInit /\ [][TNext]_tvars /\ WF_tvars(Progress)

(***************************************************************************)
(* The conformance property: the whole log is a behaviour of `Outbox.tla`, i.e.    *)
(* the read pointer reaches the end. Violated exactly when some recorded step       *)
(* matches no `Outbox` action from the state it was replayed into.                  *)
(***************************************************************************)
TraceAccepted == <>AtEnd

\* The conformance config also checks `Outbox.tla`'s own safety invariants
\* (`TypeOK`, `PublishedImpliesDelivered`, `NoDoubleActiveClaim`,
\* `AbandonedAfterRetries`, `LockImpliesProcessing`, imported via EXTENDS) on the
\* replayed run, as a second, authoritative read on the same log. The coverage
\* config checks `NoDuplicateDelivery` must be *violated*, witnessing the redelivery
\* from a crash after the broker publish but before the mark.

=============================================================================
