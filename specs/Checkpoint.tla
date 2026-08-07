---------------------------- MODULE Checkpoint ----------------------------
(***************************************************************************)
(* Gap-safe checkpointing for a `$all` (cross-category) event-store          *)
(* subscription: the settle-then-process low-watermark (ADR-0025).           *)
(*                                                                          *)
(* `global_position` is a store-wide sequence. A value is *assigned* when a  *)
(* row is inserted (in order) but only becomes *visible* when its            *)
(* transaction commits, and across categories a lower value can commit       *)
(* *after* a higher one. That is the classic event-sourcing gap problem. A   *)
(* subscription that advanced its cursor to the highest position it had      *)
(* seen would step over a lower position that commits late and never read    *)
(* it again: a silent, permanent hole in a projection at zero apparent lag   *)
(* (the checkpoint gap-skip bug ADR-0025 fixes). The fix processes only the  *)
(* contiguous run from the cursor, HOLDS at the first missing position, and  *)
(* advances past a hole only after it has stayed unfilled longer than         *)
(* `gap_timeout_seconds` (a rolled-back append leaves a permanent hole).      *)
(*                                                                          *)
(* This spec model-checks that protocol exhaustively over every             *)
(* interleaving of out-of-order commits, gap timeouts, checkpoint flushes,   *)
(* and crash/resume, up to a bounded number of positions.                   *)
(*                                                                          *)
(* Guarantee modeled (docs/reference/guarantees.md, "Subscriptions &         *)
(* delivery", the "No silent skip for $all" note):                          *)
(*                                                                          *)
(*   "no committed $all event is silently skipped; a genuinely slow commit   *)
(*    (> gap_timeout_seconds) is logged and dropped."                       *)
(*                                                                          *)
(* The `GapSafe` constant toggles the fix against the bug, so TLC's          *)
(* counterexample IS the bug: a built-in revert test.                       *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
    N,            \* highest global_position modeled; positions are 1..N
    GapSafe,      \* TRUE  = hold at the first gap (the shipped fix, ADR-0025)
                  \* FALSE = advance to the highest seen (the gap-skip bug)
    AbandonScope, \* "holes" = a gap ages out only on a rolled-back position,
                  \*           i.e. gap_timeout_seconds >= commit latency.
                  \* "all"   = any unfilled gap can age out, i.e. a commit can
                  \*           be slower than the timeout: the logged-drop
                  \*           trade-off ADR-0025 documents.
    MaxCrashes    \* bound on crash/resume events (keeps liveness checkable)

ASSUME N \in Nat /\ N >= 1
ASSUME GapSafe \in BOOLEAN
ASSUME AbandonScope \in {"holes", "all"}
ASSUME MaxCrashes \in Nat

Positions == 1..N

VARIABLES
    fate,        \* [Positions -> {"C","R"}]: "C" commits, "R" rolls back (a hole)
    visible,     \* committed positions that have become visible (grows only)
    gapAged,     \* positions whose gap timer has elapsed (eligible to abandon)
    cursor,      \* in-memory read watermark (current_position); 0 = nothing read
    durable,     \* last durably-written checkpoint; a crash resumes from here
    delivered,   \* positions handled at least once (side effects have happened)
    redelivered, \* positions handled again after already being delivered
    abandoned,   \* gaps stepped over AND logged (never silent)
    crashes      \* number of crash/resume events so far

vars == <<fate, visible, gapAged, cursor, durable,
          delivered, redelivered, abandoned, crashes>>

Max(S) == CHOOSE x \in S : \A y \in S : y <= x
Min(S) == CHOOSE x \in S : \A y \in S : x <= y

TypeOK ==
    /\ fate \in [Positions -> {"C", "R"}]
    /\ visible \subseteq Positions
    /\ gapAged \subseteq Positions
    /\ cursor \in 0..N
    /\ durable \in 0..N
    /\ delivered \subseteq Positions
    /\ redelivered \subseteq Positions
    /\ abandoned \subseteq Positions
    /\ crashes \in 0..MaxCrashes

Init ==
    /\ fate \in [Positions -> {"C", "R"}]  \* explore every commit/rollback fate
    /\ visible = {}
    /\ gapAged = {}
    /\ cursor = 0
    /\ durable = 0
    /\ delivered = {}
    /\ redelivered = {}
    /\ abandoned = {}
    /\ crashes = 0

(***************************************************************************)
(* A commit-fated position becomes visible (its transaction commits).        *)
(* The order is unconstrained, which is exactly the cross-category            *)
(* out-of-order commit that produces a gap.                                  *)
(***************************************************************************)
Commit(p) ==
    /\ fate[p] = "C"
    /\ p \notin visible
    /\ visible' = visible \cup {p}
    /\ UNCHANGED <<fate, gapAged, cursor, durable,
                   delivered, redelivered, abandoned, crashes>>

(***************************************************************************)
(* A gap ahead of the cursor stays unfilled past gap_timeout_seconds.        *)
(* Under "holes" this only ever happens to a genuine hole (fate = "R"),       *)
(* modeling a timeout no shorter than commit latency. Under "all" it can      *)
(* also hit a slow commit (fate = "C"), modeling the bounded, logged drop.    *)
(***************************************************************************)
AgeGap(p) ==
    /\ p > cursor
    /\ p \notin visible
    /\ p \notin gapAged
    /\ (AbandonScope = "all" \/ fate[p] = "R")
    /\ gapAged' = gapAged \cup {p}
    /\ UNCHANGED <<fate, visible, cursor, durable,
                   delivered, redelivered, abandoned, crashes>>

\* A position may be stepped over if it is visible (deliver it) or its gap has
\* aged out (abandon it). Anything else is a gap the cursor must HOLD at.
Passable(p) == p \in visible \/ p \in gapAged

\* Highest visible position above the cursor: the frontier of this batch. The
\* real code walks only up to `highest = max(present)`, so a trailing hole with
\* nothing visible above it is never treated as a gap.
AboveVisible == {p \in Positions : p > cursor /\ p \in visible}
Frontier == IF AboveVisible = {} THEN cursor ELSE Max(AboveVisible)

\* First non-passable position above the cursor: where a gap-safe cursor holds.
Blocked == {p \in Positions : p > cursor /\ ~Passable(p)}
FirstGap == IF Blocked = {} THEN N + 1 ELSE Min(Blocked)

\* The settle-then-process watermark: the contiguous passable run from the
\* cursor, capped at the frontier (never past the highest visible position).
SafeWatermark == Min({FirstGap - 1, Frontier})

(***************************************************************************)
(* One subscription tick. Under the fix the cursor advances only to the      *)
(* gap-safe watermark; of the positions stepped over, the visible ones are    *)
(* delivered and the rest are aged holes recorded in `abandoned` (logged).    *)
(* Under the bug it jumps to the highest visible position, silently stepping  *)
(* over any lower position not yet visible.                                  *)
(***************************************************************************)
Tick ==
    LET newCursor == IF GapSafe THEN SafeWatermark ELSE Frontier
        stepped   == {p \in Positions : p > cursor /\ p <= newCursor}
        freshly   == stepped \cap visible
    IN  /\ newCursor > cursor       \* only fire when it makes progress
        /\ cursor' = newCursor
        /\ delivered' = delivered \cup freshly
        \* Delivering a position already in `delivered` is a redelivery (a crash
        \* rewound the cursor and this tick re-read it): at-least-once in action.
        /\ redelivered' = redelivered \cup (freshly \cap delivered)
        /\ abandoned' =
             IF GapSafe THEN abandoned \cup (stepped \ visible)  \* logged, not silent
                        ELSE abandoned                           \* the bug logs nothing
        /\ UNCHANGED <<fate, visible, gapAged, durable, crashes>>

\* Flush the in-memory cursor to the durable checkpoint. Batched in reality
\* (every position_update_interval messages); modeled as firing at any time.
Flush ==
    /\ durable < cursor
    /\ durable' = cursor
    /\ UNCHANGED <<fate, visible, gapAged, cursor,
                   delivered, redelivered, abandoned, crashes>>

\* A crash between the phases: the in-memory read position and the volatile gap
\* timers are lost; the subscription resumes from the durable checkpoint.
\* `delivered` persists (a handled message's side effects already committed), so
\* re-reading redelivers them (at-least-once), which never violates safety.
Crash ==
    /\ crashes < MaxCrashes
    /\ cursor' = durable
    /\ gapAged' = {}
    /\ crashes' = crashes + 1
    /\ UNCHANGED <<fate, visible, durable, delivered, redelivered, abandoned>>

Next ==
    \/ \E p \in Positions : Commit(p)
    \/ \E p \in Positions : AgeGap(p)
    \/ Tick
    \/ Flush
    \/ Crash

Spec == Init /\ [][Next]_vars

\* Fairness for the liveness check: every progress action must eventually fire;
\* Crash is bounded by MaxCrashes so it cannot starve progress forever.
FairSpec ==
    /\ Spec
    /\ \A p \in Positions : WF_vars(Commit(p))
    /\ \A p \in Positions : WF_vars(AgeGap(p))
    /\ WF_vars(Tick)
    /\ WF_vars(Flush)

(***************************************************************************)
(* Safety invariants                                                        *)
(***************************************************************************)

\* Strong gap-safety: a committed position the cursor has moved past has been
\* delivered. Holds under the fix when the timeout is not shorter than commit
\* latency (AbandonScope = "holes"). The gap-skip bug (GapSafe = FALSE) violates
\* it.
NoSkip ==
    \A p \in Positions : (fate[p] = "C" /\ p <= cursor) => p \in delivered

\* Weaker, always-true form: a committed position the cursor moved past is
\* either delivered or was explicitly abandoned (logged). Holds even when a slow
\* commit can time out (AbandonScope = "all"): the drop is never SILENT. The
\* gap-skip bug violates this too, because its skip records nothing.
NoSilentSkip ==
    \A p \in Positions :
        (fate[p] = "C" /\ p <= cursor) => (p \in delivered \/ p \in abandoned)

\* The durable checkpoint never leads the in-memory cursor, so a crash-resume
\* re-reads from a safe position rather than skipping past one.
DurableBehindCursor == durable <= cursor

\* Sanity: a position is only ever delivered after it actually became visible.
DeliveredAreVisible == delivered \subseteq visible

\* Model-trust invariant (should hold by construction): only committed positions
\* ever become visible. If a rolled-back position leaked into `visible` it could
\* flow into `delivered` while NoSkip / NoSilentSkip, which quantify over
\* fate = "C", never noticed. A failure here means a modeling bug, not a protocol
\* bug.
VisibleAreCommitted == \A p \in visible : fate[p] = "C"

(***************************************************************************)
(* Reachability probe (NOT a safety property)                                *)
(***************************************************************************)

\* At-least-once means a crash-resume can redeliver a position. Asserting "no
\* redelivery ever" and letting TLC refute it yields a concrete witness that the
\* redelivery window is real. Checkpoint_dup.cfg runs this as an expected
\* violation; every other config leaves it unchecked.
NoRedelivery == redelivered = {}

(***************************************************************************)
(* Liveness                                                                 *)
(***************************************************************************)

\* No permanent stall: under "holes" every committed position is eventually
\* delivered. (Once delivered it stays delivered, so `<>` suffices.)
AllCommittedDelivered ==
    <>(\A p \in Positions : fate[p] = "C" => p \in delivered)

=============================================================================
