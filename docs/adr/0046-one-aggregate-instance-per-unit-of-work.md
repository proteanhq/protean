# ADR-0046: One aggregate instance per Unit of Work

**Status:** Accepted

> Amended October 2026, see "Being in the map does not make an aggregate's
> events commit" under Decision.

**Date:** October 2026

## Context

An aggregate instance carries three counters that the framework uses for
optimistic concurrency. `_version` is the version stored for it, and
`_next_version` is the version its next save writes. `_event_position` is the
position of the last event in its stream, and each event it raises expects
the stream to be at that position when the event is appended.

A state-based `repository.get()` inside a Unit of Work built a new instance on
every call. Each instance read its counters from the store. The store had not
seen the changes still pending on other copies of the same aggregate in that
transaction, so two copies disagreed about where the stream and the record
stood. Three things went wrong:

- An event raised on one copy was lost when a later read replaced that copy in
  the identity map.
- Two copies that both raised events claimed the same stream position, so the
  second append failed with `ExpectedVersionError` although no other writer
  existed.
- After a rollback, a copy could keep a version that only an earlier copy's
  uncommitted write had produced, and its next save failed.

An event-sourced `get()` already returned the tracked instance, but only once
`add()` had saved it with new events. Before that, two `get()` calls returned
two instances, with the same problems.

The identity map was also keyed by provider and id alone, so two aggregate
types that shared an id replaced each other's entry.

Related: [#1744](https://github.com/proteanhq/protean/issues/1744)

## Decision

A Unit of Work holds one instance of each aggregate for the whole transaction.

- The identity map is keyed by provider, then by aggregate class and id.
- When a `get()` or a query inside a Unit of Work loads an aggregate that the
  map already holds, the repository returns the instance in the map, with any
  changes made to it since. The query still runs against the store, so which
  aggregates match is decided by the store. Only the object returned for a
  match changes.
- An aggregate is added to the map on its first read or save in the
  transaction. This applies to state-based and event-sourced aggregates.
- Being in the map does not make an aggregate's events commit. An
  event-sourced aggregate's events are its state, and `add()` raises its fact
  event, so its events commit only once `add()` has saved it.

  *Amended (October 2026): a state-based aggregate's events also commit only
  once `add()` has saved it in the transaction. Its field changes are saved
  only through `add()`, so saving the events of an aggregate that was only
  read stored an event without the state change it records. Events raised on
  an aggregate that was only read are discarded at commit, with no warning.
  The first version of this decision kept the earlier rule, under which a
  state-based aggregate's events committed once it was read.*
- A read through a DAO set to work outside the Unit of Work (`outside_uow()`)
  and a temporal query (`at_version` or `as_of`) do not use the map.

With one instance there is one set of counters, so nothing has to reconcile
them across copies.

## Consequences

- Events raised on an aggregate in a transaction are all gathered at commit,
  however many times the aggregate was read, once `add()` has saved it.
- Version and event-position conflicts inside one transaction come only from
  another writer.
- A second `get()` of an aggregate in a Unit of Work returns the first result,
  with any changes made to it that were not saved. This is how the identity
  map in SQLAlchemy's session and in Hibernate behaves. Code that read an
  aggregate again to throw its changes away now gets them back. Saving it with
  `add()` writes those changes and the events raised with them. Without
  `add()`, neither is saved. To abandon a change, code raises an
  exception so the Unit of Work rolls back, or reads the stored state in a new
  Unit of Work. A change that breaks an invariant needs neither, because
  Protean undoes the assignment when the check fails.
- A query returns tracked instances whose in-memory fields can differ from the
  stored row that made them match. A filter on a field changed in memory but
  not yet flushed can return an instance whose field no longer meets the
  filter. SQLAlchemy's session behaves the same way.

## Alternatives Considered

- Keep a copy per read and reconcile the counters. A copy read later takes the
  higher event position of the copy it replaces, and the Unit of Work keeps
  every saved copy so it can settle their versions. Rejected: each rule
  needed another. An inherited position was wrong when the earlier copy was
  never saved, when its events included a fact event, and when the two copies
  were different aggregate types with one id.
- Keep the latest copy in the map, as before. Rejected: it loses the events of
  every earlier copy without an error.
- ADR-0027 rejected serving reads from the identity map in place of SQL, since
  `filter`, `count` and `exists` cannot see unflushed writes that way. This
  decision keeps SQL for every read and changes only which object a match
  returns, so that concern does not apply.
