# ADR-0022: Pre-Persist Aggregate Enricher for Lifecycle/Audit Fields

**Status:** Accepted

> Amended July 2026 (#1255), see
[Amendment](#amendment-july-2026-unified-persist-lifecycle) below.

**Date:** July 2026

## Context

Applications routinely need cross-cutting technical fields on their aggregates:
`created_at`/`updated_at` timestamps and `created_by`/`updated_by` audit fields
that record the acting user. Protean already made timestamps *possible*, an
abstract base aggregate with `created_at: DateTime(default=utc_now)`, but the population story was incomplete:

- `created_at` was set once at construction (a callable field default), which is
  fine.
- `updated_at` had no auto-refresh. There was no `auto_now`/`onupdate`, so every
  mutating method had to set it by hand.
- `created_by`/`updated_by` had no mechanism at all. Protean has a domain
  context (`domain.domain_context(current_user=...)` lands values on `g`) and
  event/command enrichers, but those enrichers write to *event metadata*
  (`metadata.extensions`), not to aggregate columns. There was no hook that runs
  in the persistence path with access to the acting user.

We wanted a low-magic way to stamp these fields, consistent with patterns
already in the framework, without turning it into a general "mutate the
aggregate however you like before save" escape hatch.

## Decision

We add two complementary mechanisms.

**1. Declarative timestamps.** `DateTime` and `Date` fields gain Django-parity
`auto_now_add` (stamp on the create save) and `auto_now` (stamp on every save)
flags. The flags are carried as `FieldSpec` metadata and read back on the
resolved field; the persistence layer stamps them. The two are mutually
exclusive, are rejected on non-temporal or required fields at declaration time,
and only apply to the `Repository.add` → `save` write path (see Consequences).

**2. A registered pre-persist aggregate enricher.** Domains gain
`register_aggregate_enricher(fn)` and the `@domain.aggregate_enricher`
decorator, symmetric with the existing `register_event_enricher` /
`register_command_enricher`. Both new mechanisms fire in `BaseDAO.save`. The
write path that `Repository.add` funnels through, and the same spot where the
optimistic-concurrency version is advanced. Before the entity is frozen into a
model (`from_entity`), on both the create and update paths.

The aggregate enricher differs from the event/command enrichers in one important
way: an event/command enricher **returns a dict** that the framework merges into
`metadata.extensions`, whereas an aggregate enricher **mutates the aggregate in
place** (its return value is ignored) so it can stamp real columns. It receives
just the aggregate, runs inside an active domain context (so it can read
`g.current_user`), and executes in registration order (FIFO). If it raises, the
exception propagates and the save is aborted; on an update the version advance
is rolled back (a failed create is simply never persisted).

The enricher is scoped to aggregates (child entities persisted through the same
path are not handed to it) and is documented as being for cross-cutting
lifecycle/audit metadata only. The framework supplies the hook and the stamping
mechanism; the audit *user* model stays app-defined.

## Consequences

- `updated_at` refreshes automatically, and `created_by`/`updated_by` have a
  single, central place to be stamped instead of being re-implemented in every
  mutator.
- The mechanism is symmetric with the enrichers developers already know, so
  there is little new surface to learn.
- Because the enricher mutates the aggregate through normal attribute
  assignment, invariants still run on the stamped fields. The hook does **not**
  bypass validation. It also does not touch `_events`, so event raising is
  unaffected.
- The enricher fires on every aggregate persisted through the repository, so it
  must stay fast (read from `g`, not from I/O). This is the same constraint the
  event/command enrichers already carry.
- The hook is powerful enough to be misused (an enricher *can* mutate business
  fields or raise). We rely on documentation and the narrow, opt-in framing to
  keep it in its lane rather than enforcing restrictions in code; enforcing them
  would add complexity for little practical gain.
- `auto_now`/`auto_now_add` fields are Optional and unset until the first save
  (unlike a construction-time `default=utc_now`). Apps that need the value
  populated in memory before persistence should keep using a field default.
- Both mechanisms fire on the `Repository.add` → `save` path, alongside version
  management. **They also fire on the DAO `update()` / `QuerySet.update()` paths,
  which persist through `save` (unified in #1255, see
  [Amendment](#amendment-july-2026-unified-persist-lifecycle)).** A raw write
  can opt out of the hooks with `apply_hooks=False`; version management still applies. An
  event-sourced aggregate persists through the event store rather than a DAO,
  so it carries audit data in its events instead. The audit recipe remains a
  DDD/CQRS pattern, not an ES one.

## Alternatives Considered

**An overridable `_before_save()` method on the aggregate.** Simpler and
per-aggregate, but less composable than a registered enricher (you cannot layer
several concerns), and it invites exactly the "general mutation hook" abuse we
want to discourage. A method on the aggregate reads as part of the aggregate's
own behavior. A registered, domain-level enricher keeps the cross-cutting
concern visibly separate from domain logic.

**Leaving it entirely to the application.** Works, but every mutator
re-implements `updated_at` and audit stamping, and there is no central place to
read the acting user. That is the gap this ADR closes.

**Reusing the event/command enricher return-a-dict contract.** Rejected because
those enrichers target `metadata.extensions`, not aggregate columns. Forcing the
aggregate enricher into the same shape (return a dict of field→value that the
framework applies) added indirection without benefit; direct in-place mutation
is clearer for stamping fields.

## Amendment (July 2026): unified persist lifecycle

The original decision scoped the lifecycle hooks (and version management) to the
`Repository.add` → `save` path only, excluding the DAO `update()` /
`QuerySet.update()` paths as "escape hatches", by analogy to Django (`auto_now`
fires on `Model.save()` but not the set-based `QuerySet.update()`).

That analogy did not hold for Protean. Protean's `QuerySet.update()` is **not**
set-based. It loads each matched row and updates it individually ("to fire
callback methods and ensure validations are run"). So it already ran per-row
Python (uniqueness validation) while skipping *only* the version guard,
timestamp stamping, and enrichers. That partial exclusion was arbitrary, and
its most serious symptom was a silent lost update: an update through `update()`
bypassed the optimistic-concurrency version check (#1255).

**Amended decision:** `update()` and `QuerySet.update()` persist through `save`,
so they run the full lifecycle (version management, `auto_now` stamping, and
enrichers) by default. Two qualifications:

- **Optimistic concurrency is always on**: It is a correctness guard against lost
  updates, not a cosmetic hook, and cannot be switched off by the flag below.
- **The cosmetic hooks are opt-out**: `save(..., apply_hooks=False)` /
  `update(..., apply_hooks=False)` / `QuerySet.update(..., apply_hooks=False)`
  skip `auto_now` stamping and enrichers for a raw write (e.g. a bulk migration
  that must not touch audit fields), turning the old *implicit* omission into an
  *explicit* choice.

Event-sourced aggregates are unchanged: they persist through the event store and
carry audit data in their events, so the DAO lifecycle does not apply.
