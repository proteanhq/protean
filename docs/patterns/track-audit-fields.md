# Track Audit and Lifecycle Fields

<span class="pathway-tag pathway-tag-cqrs">CQRS</span>

## The Problem

Almost every persisted aggregate wants four cross-cutting fields:

- `created_at` / `updated_at`. When the row was first written and last
  changed.
- `created_by` / `updated_by`, which user made those changes.

These have nothing to do with the aggregate's business rules, but if you leave
them to each aggregate you end up re-implementing the same thing everywhere:
setting `updated_at = now()` at the top of every mutating method, and threading
the current user down into the domain by hand. Miss one method and the audit
trail is quietly wrong.

The two halves of the problem are different in nature. Timestamps are a pure
function of *when* the save happens. Audit users are a function of *who* is
acting. Context the aggregate should not have to know about. Protean solves
each with the mechanism that fits it.

## The Pattern

Put the cross-cutting fields on an **abstract base aggregate** and inherit it.
Let the framework fill them in on save:

- Timestamps are **declarative**, `auto_now_add` / `auto_now` flags on the `DateTime` fields.
- Audit users come from a **pre-persist enricher** that reads the acting user
  from the domain context and stamps them just before the save.

The aggregate stays focused on its business behavior; the base and the enricher
carry the bookkeeping.

## How Protean Supports This

### An abstract audit base

```python
--8<-- "patterns/track-audit-fields/001.py:base"
```

`auto_now_add` and `auto_now` are Django-parity flags on `DateTime` (and
`Date`). They are stamped in the persistence path, so an `auto_now*` field is
`None` until the first save. The two are mutually exclusive.

### A pre-persist enricher for the acting user

Register a callback that stamps the audit users just before an aggregate is
saved. It **mutates the aggregate in place** (unlike event/command enrichers,
which return metadata), and it runs on both create and update:

```python
--8<-- "patterns/track-audit-fields/001.py:enricher"
```

Setting `created_by` only when the aggregate is new keeps it stable across
later updates, even when the create ran with no user. `updated_by` refreshes
every time. The enricher runs each time a repository saves an aggregate to a
database. Event-sourced aggregates are stored as events, so the enricher never
runs for them. The enricher also runs for the
records Protean itself saves through repositories, such as outbox rows and the
message records of the in-memory event store. The `hasattr` check skips any
aggregate without audit fields.

### Supplying the acting user

The enricher reads `current_user` off the domain context, so put it there at the
edge of your application (an HTTP middleware, a CLI entry point, a worker):

```python
--8<-- "patterns/track-audit-fields/001.py:supply"
```

## Applying the Pattern

Create and update, end to end:

```python
--8<-- "patterns/track-audit-fields/001.py:round_trip"
```

## Where it applies

The stamping and the enricher run on the `repository.add()` → save path (the
same place Protean manages aggregate versions) and, because they persist
through the same path, on `update()` and `QuerySet.update()` as well. Two
notes:

- **Bulk / raw updates**: `QuerySet.update(...)` updates each matched row
  individually, so it stamps and enriches like a save. When you need a raw write
  that must *not* touch audit fields (e.g. a data backfill), pass
  `apply_hooks=False` to `save()` / `update()` / `QuerySet.update()`. It skips
  the stamping and enrichers (optimistic-concurrency version management still
  applies). See [ADR-0022](../adr/0022-pre-persist-aggregate-enricher.md).
- **Event-sourced aggregates**: These persist as a stream of events, not rows in
  a table, so there are no columns to stamp. Record who and when *in the events*
  themselves (see [Message Enrichment](../guides/domain-behavior/message-enrichment.md)
  for event-level metadata). This recipe is for state-based (DDD/CQRS) aggregates.

## Anti-Patterns

### Stamping in every mutator

Setting `updated_at = utc_now()` at the top of each business method works but
drifts: the one method that forgets it leaves a stale timestamp, and there is no
single place to audit. `auto_now` removes the need entirely.

### Overloading the enricher with business logic

The pre-persist enricher is powerful, it *can* mutate any field or raise an
exception. Keep it to cross-cutting lifecycle/audit metadata. Business state
changes belong in the aggregate's own named methods, where they can raise
events and be tested in isolation. The enricher is a bookkeeping hook, not an
escape hatch.

### Modeling the acting user inside the domain

The framework supplies the *hook* and the *stamping mechanism*, not a user
model. `created_by`/`updated_by` are whatever your application puts on the
context: a user id, a username, a service name. Keep the identity concern in
your application layer.

---

!!! tip "See also"
    - [Simple Fields, Auto-populated
      timestamps](../reference/fields/simple-fields.md#auto-populated-timestamps):
      The `auto_now`/`auto_now_add` reference
    - [Message Enrichment](../guides/domain-behavior/message-enrichment.md#aggregate-pre-persist-enrichers): The aggregate enricher alongside event/command enrichers
    - [Multi-Tenancy](multi-tenancy.md): The same context-propagation approach applied to tenant isolation
