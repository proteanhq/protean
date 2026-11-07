# ADR-0014: Aggregate metadata via decorator parameters, not a `Meta` class

**Status:** Accepted

**Date:** June 2026

## Context

Protean needs a place to declare aggregate-level metadata that is neither a
field nor a method. This metadata says which provider persists the aggregate,
whether it is event-sourced, whether fact events are emitted, and now which
indexes the persistence layer should create (see issue #944).

Historically, many DDD and ORM frameworks collect this metadata in an inner
`class Meta:` block. Protean used to allow `class Meta:` on aggregates but
removed it some time ago in favor of decorator parameters. The current
convention is:

```python
@domain.aggregate(part_of=..., is_event_sourced=True, fact_events=True)
class Order:
    ...
```

Adding `indexes=[...]` forced the question explicitly: should index
declarations reintroduce `class Meta:` (indexes are arguably the most
"configuration-like" of the options), or extend the decorator-parameter
convention?

Two forces are in tension. Decorator parameters keep all aggregate metadata in
one place and consistent with the options that already exist. A `Meta` block
scales better organizationally once an element accumulates many declarative
concerns, because a long decorator signature becomes hard to read.

## Decision

Aggregate-level metadata is expressed as **decorator parameters**, and
`indexes=[...]` follows that convention:

```python
from protean import Index, Q

@domain.aggregate(indexes=[
    Index("status", "priority", desc=("priority",)),
    Index("message_id", unique=True),
    Index("status", where=Q(status__in=["pending", "failed"]), name="ix_active"),
])
class Outbox:
    ...
```

We will not reintroduce `class Meta:` for this. The portable `Index` API cannot
model some storage-specific index tuning (GIN/BRIN, expression indexes). That
tuning belongs on `@domain.model` via `Index.from_sql(dialect=..., ddl=...)`,
which keeps the aggregate clean and the storage concern in the adapter layer.

We revisit the convention only if **four or more** orthogonal aggregate-level
metadata concerns accumulate (today there are a handful: `provider`,
`is_event_sourced`, `fact_events`, `indexes`, plus internal options). At that
point a `Meta` block may be worth adding. That change would migrate *all*
options to the `Meta` block at once, so metadata is never split across two
locations.

## Consequences

- **Consistency**: All aggregate metadata is declared in one place, the
  decorator. A reader does not have to look in two locations to understand how
  an aggregate is configured.
- **No split-home migration pressure**: Introducing `class Meta:` for one new
  concern would put half the metadata on the decorator and half on `Meta`, and
  create pressure to later migrate the existing options (a Tier-1 break under
  ADR-0004). Avoiding it keeps the surface stable.
- **Signature length**: The decorator signature grows as options are added.
  With many indexes the `indexes=[...]` list can be long. This is the main cost,
  and the trigger documented above for revisiting the decision.
- **Clean domain/infrastructure split**: Portable indexes live on the
  aggregate; dialect-specific DDL lives on the model. This maps cleanly to the
  ports-and-adapters architecture.

## Alternatives Considered

- **`class Meta: indexes = [...]`**: Rejected. This option puts aggregate
  metadata in two locations. It also reverses a convention the framework
  already adopted. The organizational benefit does not yet outweigh the
  inconsistency.
- **`Field(index=True)` only, no composite support**: Rejected. Single-column
  indexes cannot express the composite ordering the outbox polling path needs
  (`status, priority DESC`). Protean must support composite indexes.
- **Indexes only on `@domain.model`**: Considered. Indexes are a property of the
  persistence representation, so model-level placement is defensible. Rejected
  because the most common indexes (uniqueness on identifiers, composite query
  ordering) encode business invariants and query patterns. Those invariants and
  query patterns belong to the domain. Storage-specific indexes still belong on
  the model via `Index.from_sql`.
