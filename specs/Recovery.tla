---------------------------- MODULE Recovery ----------------------------
(***************************************************************************)
(* The event-store subscription's failure-recovery record-before-advance     *)
(* protocol: how a handler failure is made crash-safe so a failed message is  *)
(* never silently dropped.                                                   *)
(*                                                                          *)
(* When the handler fails on the message at the read cursor, the failure is   *)
(* written durably to the failed-positions stream (`_record_failed_position`, *)
(* a per-message synchronous write) BEFORE the read cursor advances past it.   *)
(* The cursor's durable checkpoint is batched (flushed every                  *)
(* `position_update_interval` messages), so the durable Failed record always   *)
(* lands before the cursor is durably flushed past the position. A periodic    *)
(* recovery pass (`run_recovery_pass`) re-reads each unresolved position and    *)
(* retries until it resolves or exhausts. On restart `_rebuild_retry_counts`   *)
(* rebuilds the in-memory tracking from the durable failed-positions stream,    *)
(* so the record survives a crash.                                            *)
(*                                                                          *)
(* This is the one two-phase window in the subscription path that the          *)
(* Checkpoint and Outbox specs deliberately left out. It has the same          *)
(* record-before-flush shape as the checkpoint, so this spec mirrors           *)
(* `Checkpoint.tla`: a durable-vs-volatile state split and a `Crash` action    *)
(* that clears only the volatile part.                                        *)
(*                                                                          *)
(* Guarantee modeled (docs/reference/guarantees.md, "Recovery of a failed      *)
(* message is crash-safe"):                                                   *)
(*                                                                          *)
(*   "the failure is recorded to the recovery stream *before* the read cursor  *)
(*    advances past it ... If the record is written and the process then        *)
(*    crashes, the durable cursor is either still behind the position (the      *)
(*    message is re-read) or already past it (the durable record is picked up   *)
(*    by the recovery pass) -- never dropped."                                 *)
(*                                                                          *)
(* The `RecordFirst` constant toggles the fix against the bug, so TLC's         *)
(* counterexample IS the bug: a built-in revert test. TRUE = record before      *)
(* advance (shipped). FALSE = the cursor may advance past a failed message      *)
(* before (or without) its record, which is exactly the silent drop            *)
(* `enable_recovery`'s crash-safety guard prevents.                           *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
    N,            \* highest position modeled; positions are 1..N
    RecordFirst,  \* TRUE  = write the durable Failed record before advancing the
                  \*         cursor past a failed message (the shipped protocol)
                  \* FALSE = the cursor may advance without the record (the drop bug)
    MaxCrashes    \* bound on crash/resume events (keeps liveness checkable)

ASSUME N \in Nat /\ N >= 1
ASSUME RecordFirst \in BOOLEAN
ASSUME MaxCrashes \in Nat

Positions == 1..N

VARIABLES
    fate,        \* [Positions -> {"S","F"}]: the handler succeeds or fails on each
    cursorMem,   \* in-memory read cursor (current_position); 0 = nothing read (volatile)
    cursorDur,   \* last durably-flushed cursor checkpoint; a crash resumes here (durable)
    pending,     \* failed positions awaiting a durable record / advance (volatile)
    recordDur,   \* positions with a durable Failed record; monotonic (durable)
    resolved,    \* positions the recovery pass has taken terminal, Resolved or Exhausted (durable)
    delivered,   \* positions whose handler side effect has happened
    redelivered, \* failed positions re-read after a crash rewound the cursor (aux, for the probe)
    crashes      \* number of crash/resume events so far

vars == <<fate, cursorMem, cursorDur, pending, recordDur,
          resolved, delivered, redelivered, crashes>>

TypeOK ==
    /\ fate \in [Positions -> {"S", "F"}]
    /\ cursorMem \in 0..N
    /\ cursorDur \in 0..N
    /\ pending \subseteq Positions
    /\ recordDur \subseteq Positions
    /\ resolved \subseteq Positions
    /\ delivered \subseteq Positions
    /\ redelivered \subseteq Positions
    /\ crashes \in 0..MaxCrashes

Init ==
    /\ fate \in [Positions -> {"S", "F"}]  \* explore every success/failure pattern
    /\ cursorMem = 0
    /\ cursorDur = 0
    /\ pending = {}
    /\ recordDur = {}
    /\ resolved = {}
    /\ delivered = {}
    /\ redelivered = {}
    /\ crashes = 0

(***************************************************************************)
(* The handler succeeds on the message at the cursor: the side effect happens *)
(* and the cursor advances. No recovery record (nothing failed).             *)
(***************************************************************************)
HandleOk(p) ==
    /\ p = cursorMem + 1
    /\ p <= N
    /\ fate[p] = "S"
    /\ delivered' = delivered \cup {p}
    /\ cursorMem' = p
    /\ UNCHANGED <<fate, cursorDur, pending, recordDur,
                   resolved, redelivered, crashes>>

(***************************************************************************)
(* The handler fails on the message at the cursor: mark the position as        *)
(* needing a durable record. The cursor does NOT move yet. Re-reading a         *)
(* message that already has a durable record (a crash rewound the cursor        *)
(* below it) is the at-least-once redelivery the probe witnesses.              *)
(***************************************************************************)
Fail(p) ==
    /\ p = cursorMem + 1
    /\ p <= N
    /\ fate[p] = "F"
    /\ p \notin pending
    /\ pending' = pending \cup {p}
    /\ redelivered' = IF p \in recordDur THEN redelivered \cup {p} ELSE redelivered
    /\ UNCHANGED <<fate, cursorMem, cursorDur, recordDur,
                   resolved, delivered, crashes>>

(***************************************************************************)
(* Write the durable Failed record (the per-message synchronous write). The   *)
(* failed-positions stream is append-only, so the record is durable and         *)
(* monotonic: once written it survives every later crash.                     *)
(***************************************************************************)
Record(p) ==
    /\ p \in pending
    /\ p \notin recordDur
    /\ recordDur' = recordDur \cup {p}
    /\ UNCHANGED <<fate, cursorMem, cursorDur, pending,
                   resolved, delivered, redelivered, crashes>>

(***************************************************************************)
(* Advance the volatile cursor past a failed message. Under the shipped        *)
(* protocol (RecordFirst = TRUE) this is gated on the record being durable      *)
(* first, so the cursor can never move past a failed message that was not       *)
(* recorded (a failed record write raises before the advance; a crash in the    *)
(* gap leaves the cursor behind). Under the bug (RecordFirst = FALSE) it fires  *)
(* without the record: the advance-before-record drop.                         *)
(***************************************************************************)
Advance(p) ==
    /\ p \in pending
    /\ (RecordFirst => p \in recordDur)
    /\ cursorMem' = p
    /\ pending' = pending \ {p}
    /\ UNCHANGED <<fate, cursorDur, recordDur,
                   resolved, delivered, redelivered, crashes>>

(***************************************************************************)
(* Flush the in-memory cursor to the durable checkpoint. Batched in reality    *)
(* (every position_update_interval messages); modeled as firing at any time.   *)
(***************************************************************************)
Flush ==
    /\ cursorDur < cursorMem
    /\ cursorDur' = cursorMem
    /\ UNCHANGED <<fate, cursorMem, pending, recordDur,
                   resolved, delivered, redelivered, crashes>>

(***************************************************************************)
(* The periodic recovery pass takes a recorded, unresolved position terminal.  *)
(* Model the retry as eventually terminal: either it succeeds (delivered) or    *)
(* it exhausts max_retries (terminal but not delivered). Either way the durable *)
(* Failed record stays, so the message was never dropped, and the position is   *)
(* resolved so liveness is checkable.                                          *)
(***************************************************************************)
Recover(p) ==
    /\ p \in recordDur
    /\ p \notin resolved
    /\ resolved' = resolved \cup {p}
    /\ \/ delivered' = delivered \cup {p}   \* retry succeeded
       \/ delivered' = delivered            \* exhausted after max_retries
    /\ UNCHANGED <<fate, cursorMem, cursorDur, pending, recordDur,
                   redelivered, crashes>>

(***************************************************************************)
(* A crash between the phases: the in-memory cursor and the volatile pending    *)
(* state are lost; the subscription resumes from the durable checkpoint. The    *)
(* durable Failed records, the resolved set, and delivered side effects all     *)
(* persist -- on restart _rebuild_retry_counts rebuilds the in-memory tracking  *)
(* from recordDur \ resolved. Bounded by MaxCrashes so it cannot starve         *)
(* progress.                                                                   *)
(***************************************************************************)
Crash ==
    /\ crashes < MaxCrashes
    /\ cursorMem' = cursorDur
    /\ pending' = {}
    /\ crashes' = crashes + 1
    /\ UNCHANGED <<fate, cursorDur, recordDur, resolved, delivered, redelivered>>

Next ==
    \/ \E p \in Positions : HandleOk(p)
    \/ \E p \in Positions : Fail(p)
    \/ \E p \in Positions : Record(p)
    \/ \E p \in Positions : Advance(p)
    \/ \E p \in Positions : Recover(p)
    \/ Flush
    \/ Crash

Spec == Init /\ [][Next]_vars

\* Fairness for the liveness check: every progress action must eventually fire;
\* Crash is bounded by MaxCrashes so it cannot starve progress forever.
FairSpec ==
    /\ Spec
    /\ \A p \in Positions : WF_vars(HandleOk(p))
    /\ \A p \in Positions : WF_vars(Fail(p))
    /\ \A p \in Positions : WF_vars(Record(p))
    /\ \A p \in Positions : WF_vars(Advance(p))
    /\ \A p \in Positions : WF_vars(Recover(p))
    /\ WF_vars(Flush)

(***************************************************************************)
(* Safety invariants                                                        *)
(***************************************************************************)

\* The guarantee: a failed message is never silently dropped. A failed position
\* the durable cursor has moved past is either present as a durable Failed record
\* (the recovery pass will pick it up) or already delivered. A failed position
\* with the durable cursor past it, no durable record, and not delivered, is a
\* silent drop. Holds under the shipped protocol; the advance-before-record revert
\* (RecordFirst = FALSE) violates it, and TLC's counterexample is the dropped
\* message. This is the invariant Recovery_bug.cfg must fail on.
NoDrop ==
    \A p \in Positions :
        fate[p] = "F" => (p > cursorDur \/ p \in recordDur \/ p \in delivered)

\* The durable checkpoint never leads the in-memory cursor, so a crash-resume
\* re-reads from a safe position rather than skipping past one.
DurableBehindCursor == cursorDur <= cursorMem

\* Model-trust (should hold by construction): only genuinely failed positions ever
\* get a durable record. If a successful position leaked into `recordDur` it could
\* make NoDrop pass for the wrong reason. A failure here signals a modeling bug,
\* not a protocol bug.
RecordedAreFailed == \A p \in recordDur : fate[p] = "F"

\* Model-trust: the recovery pass only ever resolves a position that has a durable
\* record; a resolved position with no record would be a resolve out of nowhere.
ResolvedImpliesRecorded == resolved \subseteq recordDur

\* Model-trust: every delivered position was actually handled -- a success on the
\* first pass, or a failed position that was recorded and then recovered. Guards
\* against a modeling bug that delivers a failed position without recording it,
\* which would make NoDrop pass vacuously through the `delivered` disjunct.
DeliveredImpliesHandled ==
    \A p \in delivered : fate[p] = "S" \/ p \in recordDur

(***************************************************************************)
(* Reachability probe (NOT a safety property)                                *)
(***************************************************************************)

\* At-least-once means a crash-resume can re-read a failed message that was
\* already recorded (the crash rewound the cursor below it before the batched
\* checkpoint flushed). Asserting "no failed message is ever re-read after a crash"
\* and letting TLC refute it yields a concrete witness that the redelivery window
\* is real and the model is not vacuously safe. Recovery_dup.cfg runs this as an
\* expected violation; every other config leaves it unchecked.
NoRedeliver == redelivered = {}

(***************************************************************************)
(* Liveness                                                                 *)
(***************************************************************************)

\* No permanent stall: every failed message is eventually retried until it
\* resolves (recovered) or is exhausted. (Once resolved it stays resolved, so `<>`
\* suffices.)
AllFailedResolved ==
    <>(\A p \in Positions : fate[p] = "F" => p \in resolved)

=============================================================================
