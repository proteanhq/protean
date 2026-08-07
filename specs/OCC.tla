------------------------------ MODULE OCC ------------------------------
(***************************************************************************)
(* The aggregate optimistic-concurrency no-lost-update protocol.            *)
(*                                                                          *)
(* Two (or more) concurrent Units of Work each update the same aggregate.    *)
(* Each writer: (1) READS the aggregate, capturing the stored version as its  *)
(* expected base `b`; (2) COMMITS. The commit is the version check made        *)
(* atomic with the write: a compare-and-set that advances the stored version  *)
(* to `b + 1` only if the stored version is still `b`, and otherwise raises    *)
(* ExpectedVersionError (a conflict). One writer per base wins; the rest        *)
(* conflict. No committed update is ever silently overwritten.                *)
(*                                                                          *)
(* This single atomic compare-and-set is the faithful abstraction of both      *)
(* shipped fixes, which collapse to the same action:                          *)
(*                                                                          *)
(*   - SQL: SQLAlchemy's `version_id_col` rides the flush and emits            *)
(*     `UPDATE ... SET _version = <b+1> WHERE id = :id AND _version = :b`. Zero *)
(*     rows matched -> StaleDataError -> ExpectedVersionError at commit.        *)
(*   - Memory: `MemorySession.commit` re-checks each aggregate's version        *)
(*     against the live store under the provider lock and merges only the       *)
(*     records it changed, so a stale writer's commit is rejected.             *)
(*                                                                          *)
(* Per ADR-0013 the aggregate root is the single concurrency boundary, so one   *)
(* version cell is the right granularity, and one parameterized model covers    *)
(* both adapters. This spec model-checks the protocol exhaustively over every   *)
(* interleaving of concurrent writers.                                        *)
(*                                                                          *)
(* Guarantees modeled (docs/reference/guarantees.md, "No lost update",         *)
(* SQL and Memory adapters; ADR-0013):                                        *)
(*                                                                          *)
(*   No lost update   "The aggregate OCC check is atomic with the write, so    *)
(*                     two concurrent updates can no longer both succeed and    *)
(*                     silently drop one."                                     *)
(*                                                                          *)
(* One constant toggles the bug so TLC's counterexample IS the bug (a built-in  *)
(* revert test): `Atomic` is TRUE for the shipped compare-and-set. When FALSE,  *)
(* the commit is split into a separate compare step and a later unconditional   *)
(* write, so two writers that both read base `b` both write `b + 1` and one      *)
(* update is silently dropped, no conflict raised. That split is the            *)
(* read-compare-write race called out in ADR-0013.                            *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
    Writers,   \* set of concurrent writers (Units of Work) contending for one aggregate
    Atomic     \* TRUE = shipped atomic compare-and-set; FALSE = split compare/write,
               \* the read-compare-write race that silently drops an update

ASSUME Atomic \in BOOLEAN
ASSUME IsFiniteSet(Writers)

\* Bound: with N writers at most N commits can succeed, so the stored version and
\* any read base stay within 0..N. TLC needs a finite type for both.
MaxV == Cardinality(Writers)

VARIABLES
    version,   \* the stored aggregate _version (the compare-and-set target)
    high,      \* the highest version any successful commit has reached (aux, only ever rises)
    base,      \* [Writers -> 0..MaxV]: the version each writer read (its expected version)
    phase      \* [Writers -> {start, read, checked, committed, conflicted}]

vars == <<version, high, base, phase>>

Phases == {"start", "read", "checked", "committed", "conflicted"}

Committed  == {w \in Writers : phase[w] = "committed"}
Conflicted == {w \in Writers : phase[w] = "conflicted"}

TypeOK ==
    /\ version \in 0..MaxV
    /\ high \in 0..MaxV
    /\ base \in [Writers -> 0..MaxV]
    /\ phase \in [Writers -> Phases]

Init ==
    /\ version = 0
    /\ high = 0
    /\ base = [w \in Writers |-> 0]
    /\ phase = [w \in Writers |-> "start"]

(***************************************************************************)
(* Read: capture the current stored version as this writer's expected base.    *)
(* It only observes `version`; it does not block or advance anything, so both   *)
(* writers can sit at the same base before either commits (that shared base is   *)
(* what makes the race form -- see OCC_conflict.cfg).                          *)
(***************************************************************************)
Read(w) ==
    /\ phase[w] = "start"
    /\ base' = [base EXCEPT ![w] = version]
    /\ phase' = [phase EXCEPT ![w] = "read"]
    /\ UNCHANGED <<version, high>>

(***************************************************************************)
(* Commit, shipped protocol (Atomic = TRUE): the version check and the write    *)
(* are one indivisible compare-and-set. Advance to base + 1 only if the stored  *)
(* version is still this writer's base; otherwise conflict (ExpectedVersionError *)
(* -- a concurrent writer already moved the version past our base).             *)
(***************************************************************************)
Commit(w) ==
    /\ Atomic
    /\ phase[w] = "read"
    /\ \/ /\ version = base[w]
          /\ version' = version + 1
          /\ high' = IF version + 1 > high THEN version + 1 ELSE high
          /\ phase' = [phase EXCEPT ![w] = "committed"]
       \/ /\ version # base[w]
          /\ phase' = [phase EXCEPT ![w] = "conflicted"]
          /\ UNCHANGED <<version, high>>
    /\ UNCHANGED <<base>>

(***************************************************************************)
(* The bug (Atomic = FALSE): the commit is split into two separate actions.     *)
(* Compare observes the version against the base and decides "ok" (or           *)
(* conflicts), but does NOT write. Between it and the Write, the other writer    *)
(* can commit. Write then advances the version UNCONDITIONALLY to base + 1,      *)
(* using the stale base -- so two writers that both read base b both write       *)
(* b + 1, and one committed update is silently overwritten with no conflict.     *)
(* This is the read-compare-write race of ADR-0013.                            *)
(***************************************************************************)
Compare(w) ==
    /\ ~Atomic
    /\ phase[w] = "read"
    /\ \/ /\ version = base[w]
          /\ phase' = [phase EXCEPT ![w] = "checked"]
       \/ /\ version # base[w]
          /\ phase' = [phase EXCEPT ![w] = "conflicted"]
    /\ UNCHANGED <<version, high, base>>

Write(w) ==
    /\ ~Atomic
    /\ phase[w] = "checked"
    /\ version' = base[w] + 1
    /\ high' = IF base[w] + 1 > high THEN base[w] + 1 ELSE high
    /\ phase' = [phase EXCEPT ![w] = "committed"]
    /\ UNCHANGED <<base>>

Next ==
    \/ \E w \in Writers : Read(w)
    \/ \E w \in Writers : Commit(w)
    \/ \E w \in Writers : Compare(w)
    \/ \E w \in Writers : Write(w)

Spec == Init /\ [][Next]_vars

\* Fairness for liveness: every writer's actions must eventually fire, so no
\* writer stalls before reaching a terminal state. The bug-only actions
\* (Compare, Write) are disabled under Atomic = TRUE, where their fairness is
\* vacuous; likewise Commit is disabled under Atomic = FALSE.
FairSpec ==
    /\ Spec
    /\ \A w \in Writers : WF_vars(Read(w))
    /\ \A w \in Writers : WF_vars(Commit(w))
    /\ \A w \in Writers : WF_vars(Compare(w))
    /\ \A w \in Writers : WF_vars(Write(w))

(***************************************************************************)
(* Safety invariants                                                        *)
(***************************************************************************)

\* Guarantee -- the headline "No lost update". The stored version equals the
\* number of writers that committed successfully: every successful commit
\* advanced the version by exactly one, so no committed update was overwritten.
\* Holds under Atomic = TRUE; the split-commit revert (Atomic = FALSE) violates
\* it -- two writers commit but the version only reaches one. This is the
\* invariant OCC_bug.cfg must fail on.
NoLostUpdate == version = Cardinality(Committed)

\* Guarantee -- the "no lost update" essence restated over the base version: at
\* most one writer that read a given base commits; every other writer from that
\* base is forced to conflict. Holds under the atomic protocol; the split-commit
\* bug lets two writers from base b both commit.
AtMostOneWinnerPerBase ==
    \A b \in 0..MaxV :
        Cardinality({w \in Committed : base[w] = b}) <= 1

\* Model-trust -- the stored version never decreases: it always sits at the
\* highest version any successful commit has reached (`high` only ever rises).
\* Holds even under the split-commit bug (the split still increments by one and
\* never rolls the version back), so it cannot pre-empt NoLostUpdate in the
\* revert run. A failure here would signal a modeling bug, not a protocol bug.
VersionMonotonic == version = high

\* Model-trust -- a writer only reaches `conflicted` when the stored version has
\* already moved past its base (a genuinely stale expected version), never on a
\* fresh read. Holds under both the atomic protocol and the split-commit bug.
ConflictImpliesStale == \A w \in Conflicted : base[w] < version

(***************************************************************************)
(* Reachability probe (NOT a safety property)                                *)
(***************************************************************************)

\* The model is only meaningful if two writers can genuinely race from the same
\* base and force a conflict; a vacuously-safe model where writers never contend
\* would satisfy NoLostUpdate for the wrong reason and the revert test would
\* prove nothing. Asserting "no writer ever conflicts" and letting TLC refute it
\* yields a concrete witness that the contention is real. OCC_conflict.cfg runs
\* this as an expected violation; every other config leaves it unchecked.
NoConflict == Conflicted = {}

(***************************************************************************)
(* Liveness                                                                 *)
(***************************************************************************)

\* No permanent stall: every writer eventually reaches a terminal state, either
\* committing or conflicting.
EventuallyResolved ==
    <>[](\A w \in Writers : phase[w] \in {"committed", "conflicted"})

=============================================================================
