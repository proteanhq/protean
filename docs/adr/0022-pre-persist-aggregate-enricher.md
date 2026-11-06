# ADR-0022: Pre-Persist Aggregate Enricher for Lifecycle/Audit Fields

**Status:** Accepted

> Amended July 2026 (#1255), see
[Amendment](#amendment-july-2026-unified-persist-lifecycle) below.
> Amended October 2026 (#1663), see
[Amendment](#amendment-october-2026-hook-writes-and-invariants) below.

**Date:** July 2026

## Context

Applications routinely need cross-cutting technical fields on their aggregates:
`created_at`/`updated_at` timestamps and `created_by`/`updated_by` audit fields
that record the acting user. Protean already made timestamps *possible* with an
abstract base aggregate that declares `created_at: DateTime(default=utc_now)`.
It did not fill all of these fields, though:

- `created_at` was set once at construction (a callable field default), which is
  fine.
- `updated_at` had no auto-refresh. There was no `auto_now`/`onupdate`, so every
  mutating method had to set it by hand.
- `created_by`/`updated_by` had no mechanism at all. Protean has a domain
  context (`domain.domain_context(current_user=...)` sets values on `g`). Its
  event/command enrichers write only to *event metadata*
  (`metadata.extensions`) and never to aggregate columns. There was no hook
  that runs in the persistence path with access to the acting user.

We wanted a simple, explicit way to stamp these fields that matches patterns
already in the framework. The mechanism must not become a general hook that
lets code "mutate the aggregate however you like before save".

## Decision

We add two complementary mechanisms.

**1. Declare timestamps on the field.** `DateTime` and `Date` fields gain
Django-parity `auto_now_add` (stamp on the create save) and `auto_now` (stamp
on every save) flags. Protean carries the flags as `FieldSpec` metadata and
reads them back on the resolved field. The persistence layer then stamps the
flagged fields. The two flags are mutually exclusive, and Protean rejects them
on non-temporal or required fields at declaration time. They apply only to the
`Repository.add` → `save` write path (see Consequences).

**2. Register a pre-persist aggregate enricher.** Domains gain
`register_aggregate_enricher(fn)` and the `@domain.aggregate_enricher`
decorator, symmetric with the existing `register_event_enricher` /
`register_command_enricher`. Both new mechanisms fire in `BaseDAO.save`.
`Repository.add` writes through `BaseDAO.save`. The same method advances the
optimistic-concurrency version. Both mechanisms fire before `from_entity`
converts the entity into a model, on the create path and the update path.

An event/command enricher **returns a dict**, and the framework merges that
dict into `metadata.extensions`. An aggregate enricher instead **mutates the
aggregate in place** so it can stamp real columns, and the framework ignores
its return value. The aggregate enricher receives only the aggregate and runs
inside an active domain context, so it can read `g.current_user`. Protean runs
aggregate enrichers in registration order (FIFO). If an aggregate enricher
raises, the exception propagates and the save aborts. On an update Protean
rolls back the version advance, and on a create nothing is persisted.

The enricher receives only aggregates, never the child entities persisted
through the same path. The documentation says it is for cross-cutting
lifecycle/audit metadata only. The framework supplies the hook and the stamping
mechanism; the audit *user* model stays app-defined.

## Consequences

- `updated_at` refreshes automatically. `created_by`/`updated_by` get one
  central place for stamping, so you no longer re-implement them in every
  mutator.
- The mechanism is symmetric with the enrichers developers already know, so
  there is little new API to learn.
- On an aggregate saved on its own, the hook does **not** bypass all
  validation: the post-invariants still hold after it. Status-transition rules
  also still apply to what the hook writes. The pre-invariants do not run on
  the hook's writes (see
  [Amendment](#amendment-october-2026-hook-writes-and-invariants)). No check
  runs at save time when the save runs inside the caller's own `atomic_change`
  block. The hook does not touch `_events`, so event raising is unaffected.
- The enricher fires on every aggregate persisted through the repository, so it
  must stay fast (read from `g`, not from I/O). This is the same constraint the
  event/command enrichers already carry.
- The hook is powerful enough to be misused (an enricher *can* mutate business
  fields or raise). We rely on documentation and the narrow, opt-in framing to
  limit the hook to lifecycle/audit fields, and we do not enforce restrictions
  in code. Enforcing them would add complexity for little practical gain.
- `auto_now`/`auto_now_add` fields are Optional and unset until the first save
  (unlike a construction-time `default=utc_now`). Apps that need the value
  populated in memory before persistence should keep using a field default.
- The `auto_now`/`auto_now_add` flags and the aggregate enricher both fire on
  the `Repository.add` → `save` path, alongside version management. **They also
  fire on the DAO `update()` / `QuerySet.update()` paths, which persist through
  `save` (unified in #1255, see
  [Amendment](#amendment-july-2026-unified-persist-lifecycle)).** A raw write
  can opt out of the hooks with `apply_hooks=False`; version management still
  applies. An event-sourced aggregate persists through the event store rather
  than a DAO, so it carries audit data in its events instead. Stamping audit
  fields on save stays a pattern for DAO-persisted (DDD/CQRS) aggregates and
  does not apply to event-sourced (ES) aggregates.

## Alternatives Considered

**An overridable `_before_save()` method on the aggregate.** This method is
simpler and per-aggregate, but less composable than a registered enricher,
because you cannot layer several concerns. Developers could also use it for
exactly the "general mutation hook" abuse we want to discourage. A method on
the aggregate reads as part of the aggregate's own behavior. A registered,
domain-level enricher keeps the cross-cutting concern visibly separate from
domain logic.

**Leaving it entirely to the application.** This works, but every mutator
re-implements `updated_at` and audit stamping. The application also has no
central place to read the acting user. That is the gap this ADR closes.

**Reusing the event/command enricher return-a-dict contract.** Rejected because
those enrichers target `metadata.extensions`, not aggregate columns. Forcing the
aggregate enricher into the same shape (return a dict of field→value that the
framework applies) added indirection without benefit; direct in-place mutation
is clearer for stamping fields.

## Amendment (July 2026): unified persist lifecycle

We first limited the lifecycle hooks (and version management) to the
`Repository.add` → `save` path and left out the DAO `update()` /
`QuerySet.update()` paths as "escape hatches". We followed Django, where
`auto_now` fires on `Model.save()` but not on the set-based
`QuerySet.update()`.

That analogy did not hold for Protean. Protean's `QuerySet.update()` is **not**
set-based. It loads each matched row and updates it individually ("to fire
callback methods and ensure validations are run"). So it already ran per-row
Python (uniqueness validation) while skipping *only* the version guard,
timestamp stamping, and enrichers. That partial exclusion was arbitrary. Its
most serious result was a silent lost update, because an update through
`update()` bypassed the optimistic-concurrency version check (#1255).

**Amended decision:** `update()` and `QuerySet.update()` persist through `save`,
so they run the full lifecycle (version management, `auto_now` stamping, and
enrichers) by default. Two qualifications:

- **Optimistic concurrency is always on**: It is a correctness guard against lost
  updates, not a cosmetic hook, and cannot be switched off by the flag below.
- **The cosmetic hooks are opt-out**: `save(..., apply_hooks=False)` /
  `update(..., apply_hooks=False)` / `QuerySet.update(..., apply_hooks=False)`
  skip `auto_now` stamping and enrichers for a raw write, such as a bulk
  migration that must not touch audit fields. The flag turns the old *implicit*
  omission into an *explicit* choice.

Event-sourced aggregates are unchanged: they persist through the event store and
carry audit data in their events, so the DAO lifecycle does not apply.

## Amendment (October 2026): hook writes and invariants

Before this amendment, the `auto_now` stamping and the aggregate enricher both
assigned through `__setattr__`, so every stamped field ran the aggregate's
`@invariant.pre` checks against the new state. A common pre-invariant is "a
closed account cannot be modified". `close()` passes, because the check runs
before `status` is assigned. Then the `updated_at` stamp counted as a
modification of a closed account, and the save failed (#1663).

**Amended decision:**

- **Pre-invariants do not run on hook writes.** A pre-invariant guards a
  business change against the state before it. An `auto_now` stamp or an
  enricher's audit field is not a business change.
- **Post-invariants still run, once per hook.** `_postcheck()` runs after the
  `auto_now` stamping and after each enricher. An aggregate saved in an invalid
  state would fail every later load, because loading rebuilds it and
  initialization runs the post-invariants. Skipping the post-check would move
  the failure from the save to an unrelated read, with the bad row already
  stored.
- **Status-transition rules still apply** to a status field a hook changes,
  from its value before the hook to its value after.
- **A failure names the hook.** The `ValidationError` keeps the invariant's
  messages and codes. Its `location` names the `auto_now` stamping (with the
  stamped field names) or the enricher's qualified name. The aggregate was
  valid before the hook ran. So the error has to name the failing hook. The
  save aborts, and the version advance is rolled back, as when an enricher
  raises. The hook's writes are undone too.
- **One mechanism.** Each hook runs in a private subclass of `atomic_change`
  that skips the entry pre-check and names the hook in a failure. The hook's
  writes are checked and undone the same way as any other batched change. If
  the hook itself raises, its writes are undone and its exception propagates. A
  `ValidationError` it raises gets the hook's `location` unless it already
  carries one. When the caller saves inside its own `atomic_change` block, the
  save leaves the checks to that block. The block runs them on its exit. That
  block undoes only the in-memory state, so a write it rejects may already be
  stored. A save inside the caller's `atomic_change` block also left the checks
  to that block before this amendment, for business changes and hook writes
  alike.
