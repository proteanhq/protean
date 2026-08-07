------------------------------ MODULE Outbox ------------------------------
(***************************************************************************)
(* The transactional-outbox two-phase publish.                              *)
(*                                                                          *)
(* When a Unit of Work commits, published messages are written to the        *)
(* outbox table in the same transaction. An outbox processor then, per        *)
(* message: (1) CLAIMS it atomically, marking it PROCESSING under a           *)
(* time-boxed lock (SELECT ... FOR UPDATE SKIP LOCKED on PostgreSQL, a        *)
(* guarded read-then-update elsewhere), so no two workers claim the same      *)
(* row; (2) PUBLISHES it to the broker; (3) MARKS the row PUBLISHED (or        *)
(* FAILED/ABANDONED). The order of (2) and (3) is the whole game: the broker  *)
(* publish happens BEFORE the row is marked, so a crash after the publish but  *)
(* before the mark re-delivers (at-least-once with possible duplicates)        *)
(* rather than dropping the message.                                         *)
(*                                                                          *)
(* This spec model-checks that protocol exhaustively over every             *)
(* interleaving of concurrent workers, lock expiry, redelivery, publish       *)
(* success/failure, and crash points between the phases.                     *)
(*                                                                          *)
(* Guarantees modeled (docs/reference/guarantees.md, "Outbox"):             *)
(*                                                                          *)
(*   Delivery         "At-least-once to the broker: a crash after            *)
(*                     broker.publish but before the row is marked            *)
(*                     published re-delivers."                               *)
(*   Terminal         "After max_retries ... marked abandoned, permanently    *)
(*                     not delivered, retained."                             *)
(*   No-double-claim   the claim contract (ADR-0013).                        *)
(*                                                                          *)
(* Two constants toggle a bug so TLC's counterexample IS the bug (built-in    *)
(* revert tests): `AckBeforePublish` flips the publish/mark ordering, and     *)
(* `ClaimSafe` relaxes the claim guard so two workers can grab one row.       *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
    Messages,          \* set of outbox message ids (each already committed)
    Workers,           \* set of outbox-processor worker ids
    MaxRetries,        \* publish-failure retries before a message is ABANDONED
    MaxCrashes,        \* bound on worker crashes (keeps liveness checkable)
    AckBeforePublish,  \* FALSE = publish then mark (shipped); TRUE = mark then
                       \* publish (the bug that drops a message on a crash)
    ClaimSafe          \* TRUE = the claim excludes other workers (shipped);
                       \* FALSE = an unguarded claim that fails to exclude

ASSUME MaxRetries \in Nat /\ MaxRetries >= 1
ASSUME MaxCrashes \in Nat
ASSUME AckBeforePublish \in BOOLEAN
ASSUME ClaimSafe \in BOOLEAN
ASSUME 0 \notin Messages   \* 0 is reserved as the "no message" marker below

NoMsg == 0   \* the "not holding a message" marker for a worker (not a real id)

VARIABLES
    status,      \* [Messages -> {PENDING, PROCESSING, PUBLISHED, FAILED, ABANDONED}]
    retry,       \* [Messages -> 0..MaxRetries]: publish attempts that have failed
    lockLive,    \* [Messages -> BOOLEAN]: the claim lock is within its window
    published,   \* messages the broker has received at least once
    duplicated,  \* messages the broker has received more than once
    busy,        \* [Workers -> Messages \cup {NoMsg}]: the message a worker holds
    phase,       \* [Workers -> {idle, claimed, pubok, pubfail, marked}]
    crashes      \* number of worker crashes so far

vars == <<status, retry, lockLive, published, duplicated, busy, phase, crashes>>

Status == {"PENDING", "PROCESSING", "PUBLISHED", "FAILED", "ABANDONED"}
Phases == {"idle", "claimed", "pubok", "pubfail", "marked"}

TypeOK ==
    /\ status \in [Messages -> Status]
    /\ retry \in [Messages -> 0..MaxRetries]
    /\ lockLive \in [Messages -> BOOLEAN]
    /\ published \subseteq Messages
    /\ duplicated \subseteq Messages
    /\ busy \in [Workers -> Messages \cup {NoMsg}]
    /\ phase \in [Workers -> Phases]
    /\ crashes \in 0..MaxCrashes

Init ==
    /\ status = [m \in Messages |-> "PENDING"]
    /\ retry = [m \in Messages |-> 0]
    /\ lockLive = [m \in Messages |-> FALSE]
    /\ published = {}
    /\ duplicated = {}
    /\ busy = [w \in Workers |-> NoMsg]
    /\ phase = [w \in Workers |-> "idle"]
    /\ crashes = 0

\* A row is claimable when it is PENDING, a retry-due FAILED row, or a PROCESSING
\* row whose lock has expired (a crashed claim, now reclaimable), it still has
\* retries left, and no live worker holds it. Retry-backoff timing is abstracted:
\* a FAILED row is simply eligible. When ClaimSafe is FALSE the lock and the
\* holder guards are dropped, modeling a claim that fails to exclude.
Claimable(m) ==
    /\ \/ status[m] \in {"PENDING", "FAILED"}
       \/ (status[m] = "PROCESSING" /\ (~ClaimSafe \/ ~lockLive[m]))
    /\ retry[m] < MaxRetries
    /\ (ClaimSafe => \A w \in Workers : busy[w] # m)

\* The broker receives m. A receipt that repeats an earlier one is a duplicate
\* (at-least-once, which handlers must tolerate). Used by both publish steps.
BrokerReceives(m) ==
    /\ published' = published \cup {m}
    /\ duplicated' = IF m \in published THEN duplicated \cup {m} ELSE duplicated

(***************************************************************************)
(* (1) Claim: atomically mark PROCESSING and take the lock. With ClaimSafe,   *)
(* a claimed row is PROCESSING under a live lock and no second worker's Claim  *)
(* is enabled on it, so no-double-claim holds by construction.                *)
(***************************************************************************)
Claim(w, m) ==
    /\ phase[w] = "idle"
    /\ Claimable(m)
    /\ status' = [status EXCEPT ![m] = "PROCESSING"]
    /\ lockLive' = [lockLive EXCEPT ![m] = TRUE]
    /\ busy' = [busy EXCEPT ![w] = m]
    /\ phase' = [phase EXCEPT ![w] = "claimed"]
    /\ UNCHANGED <<retry, published, duplicated, crashes>>

(***************************************************************************)
(* (2) Publish to the broker, shipped ordering (before the mark). The         *)
(* attempt may succeed or fail. A success that repeats an earlier publish is   *)
(* a duplicate (at-least-once, which handlers must tolerate).                 *)
(***************************************************************************)
Publish(w, m) ==
    /\ AckBeforePublish = FALSE
    /\ busy[w] = m
    /\ phase[w] = "claimed"
    /\ \/ /\ BrokerReceives(m)
          /\ phase' = [phase EXCEPT ![w] = "pubok"]
       \/ /\ phase' = [phase EXCEPT ![w] = "pubfail"]
          /\ UNCHANGED <<published, duplicated>>
    /\ UNCHANGED <<status, retry, lockLive, busy, crashes>>

(***************************************************************************)
(* (3) Mark PUBLISHED after a successful publish, shipped ordering. Safe       *)
(* because `published` already contains m.                                   *)
(***************************************************************************)
MarkPublished(w, m) ==
    /\ busy[w] = m
    /\ phase[w] = "pubok"
    /\ status' = [status EXCEPT ![m] = "PUBLISHED"]
    /\ lockLive' = [lockLive EXCEPT ![m] = FALSE]
    /\ busy' = [busy EXCEPT ![w] = NoMsg]
    /\ phase' = [phase EXCEPT ![w] = "idle"]
    /\ UNCHANGED <<retry, published, duplicated, crashes>>

(***************************************************************************)
(* (3') Mark FAILED after a failed publish; ABANDONED once retries run out     *)
(* (matches mark_failed: increment, then FAILED if retry < max else            *)
(* ABANDONED). ABANDONED is terminal, permanently not delivered, retained.     *)
(***************************************************************************)
MarkFailed(w, m) ==
    LET attempts == retry[m] + 1   \* failed attempts including this one
    IN  /\ busy[w] = m
        /\ phase[w] = "pubfail"
        /\ retry' = [retry EXCEPT ![m] = attempts]
        /\ status' = [status EXCEPT
                        ![m] = IF attempts < MaxRetries THEN "FAILED"
                                                        ELSE "ABANDONED"]
        /\ lockLive' = [lockLive EXCEPT ![m] = FALSE]
        /\ busy' = [busy EXCEPT ![w] = NoMsg]
        /\ phase' = [phase EXCEPT ![w] = "idle"]
        /\ UNCHANGED <<published, duplicated, crashes>>

(***************************************************************************)
(* The bug (AckBeforePublish = TRUE): mark the row PUBLISHED durably BEFORE     *)
(* the broker publish, so the durable state claims a delivery that never        *)
(* happened; a crash here loses the message permanently.                       *)
(***************************************************************************)
MarkFirst(w, m) ==
    /\ AckBeforePublish = TRUE
    /\ busy[w] = m
    /\ phase[w] = "claimed"
    /\ status' = [status EXCEPT ![m] = "PUBLISHED"]
    /\ lockLive' = [lockLive EXCEPT ![m] = FALSE]
    /\ phase' = [phase EXCEPT ![w] = "marked"]
    /\ UNCHANGED <<retry, published, duplicated, busy, crashes>>

PublishAfter(w, m) ==
    /\ AckBeforePublish = TRUE
    /\ busy[w] = m
    /\ phase[w] = "marked"
    /\ BrokerReceives(m)
    /\ busy' = [busy EXCEPT ![w] = NoMsg]
    /\ phase' = [phase EXCEPT ![w] = "idle"]
    /\ UNCHANGED <<status, retry, lockLive, crashes>>

(***************************************************************************)
(* A worker crashes mid-flight: it drops the message without marking it. The   *)
(* row keeps its status and its lock; the lock will later expire, making the   *)
(* row reclaimable. Nothing the broker already received is undone.            *)
(***************************************************************************)
Crash(w) ==
    /\ crashes < MaxCrashes
    /\ phase[w] # "idle"
    /\ busy' = [busy EXCEPT ![w] = NoMsg]
    /\ phase' = [phase EXCEPT ![w] = "idle"]
    /\ crashes' = crashes + 1
    /\ UNCHANGED <<status, retry, lockLive, published, duplicated>>

(***************************************************************************)
(* The lock on a PROCESSING row expires once no live worker holds it (its      *)
(* holder crashed). This returns a claimed-but-unfinished row to the           *)
(* claimable pool. Modeling the expiry only after the holder is gone keeps     *)
(* the spec off the pathological "lock expired while the owner still runs"     *)
(* path, which the 5-minute lock plus the re-fetch in the mark step guard      *)
(* against in the real processor.                                            *)
(***************************************************************************)
LockExpire(m) ==
    /\ status[m] = "PROCESSING"
    /\ lockLive[m]
    /\ \A w \in Workers : busy[w] # m
    /\ lockLive' = [lockLive EXCEPT ![m] = FALSE]
    /\ UNCHANGED <<status, retry, published, duplicated, busy, phase, crashes>>

Next ==
    \/ \E w \in Workers, m \in Messages : Claim(w, m)
    \/ \E w \in Workers, m \in Messages : Publish(w, m)
    \/ \E w \in Workers, m \in Messages : MarkPublished(w, m)
    \/ \E w \in Workers, m \in Messages : MarkFailed(w, m)
    \/ \E w \in Workers, m \in Messages : MarkFirst(w, m)
    \/ \E w \in Workers, m \in Messages : PublishAfter(w, m)
    \/ \E w \in Workers : Crash(w)
    \/ \E m \in Messages : LockExpire(m)

Spec == Init /\ [][Next]_vars

\* Fairness for liveness: every progress action must eventually fire; Crash is
\* bounded by MaxCrashes and is deliberately NOT forced.
FairSpec ==
    /\ Spec
    /\ \A w \in Workers, m \in Messages : WF_vars(Claim(w, m))
    /\ \A w \in Workers, m \in Messages : WF_vars(Publish(w, m))
    /\ \A w \in Workers, m \in Messages : WF_vars(MarkPublished(w, m))
    /\ \A w \in Workers, m \in Messages : WF_vars(MarkFailed(w, m))
    /\ \A w \in Workers, m \in Messages : WF_vars(MarkFirst(w, m))
    /\ \A w \in Workers, m \in Messages : WF_vars(PublishAfter(w, m))
    /\ \A m \in Messages : WF_vars(LockExpire(m))

(***************************************************************************)
(* Safety invariants                                                        *)
(***************************************************************************)

\* No lost / phantom delivery: a row is never marked PUBLISHED unless the
\* broker actually received it. The shipped ordering (publish then mark) holds
\* it; the ack-before-publish bug violates it, which is the revert test.
PublishedImpliesDelivered ==
    \A m \in Messages : status[m] = "PUBLISHED" => m \in published

\* No double-claim: at most one worker actively holds any message at a time.
\* Holds under ClaimSafe; the ClaimSafe = FALSE revert test violates it.
NoDoubleActiveClaim ==
    \A m \in Messages :
        Cardinality({w \in Workers : busy[w] = m}) <= 1

\* Terminal state is earned: a message is ABANDONED only after its retries are
\* exhausted (permanently not delivered, retained for observability).
AbandonedAfterRetries ==
    \A m \in Messages : status[m] = "ABANDONED" => retry[m] >= MaxRetries

\* Sanity: a live lock exists only on a row that is being processed.
LockImpliesProcessing ==
    \A m \in Messages : lockLive[m] => status[m] = "PROCESSING"

\* Model-trust invariant (should hold by construction): a worker is idle exactly
\* when it holds no message. `phase` and `busy` are two variables that every
\* action must move together; a failure here means a modeling bug where one leg
\* drifted from the other.
WorkerStateAgree ==
    \A w \in Workers : (phase[w] = "idle") <=> (busy[w] = NoMsg)

\* Model-trust invariant: a duplicate is by definition a repeat receipt, so the
\* duplicate set can never exceed the published set.
DuplicatedArePublished == duplicated \subseteq published

(***************************************************************************)
(* Reachability probe (NOT a safety property)                                *)
(***************************************************************************)

\* At-least-once means a message can be delivered more than once, and handlers
\* must tolerate it. Asserting "no duplicate ever" and letting TLC refute it
\* yields a concrete witness that the duplicate window is real, not assumed.
\* Outbox_dup.cfg runs this as an expected violation; every other config leaves
\* it unchecked.
NoDuplicateDelivery == duplicated = {}

(***************************************************************************)
(* Liveness                                                                 *)
(***************************************************************************)

\* No permanent stall: every message eventually reaches a terminal state.
EventuallyResolved ==
    <>[](\A m \in Messages : status[m] \in {"PUBLISHED", "ABANDONED"})

=============================================================================
