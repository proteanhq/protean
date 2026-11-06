# ADR-0040: The Schema-Evolution Ladder

**Status:** Accepted

**Date:** September 2026

## Context

Once stored, an event is immutable, and only a deliberate operator migration
rewrites it. The code that reads the event keeps changing. A field gets
renamed, a new one is added, an old one is dropped. Months later a handler
still has to decode a payload written by last year's schema. Protean has three
mechanisms that let current code read a payload written under an older schema.
Until this ADR, no written rule said which mechanism to use.

- `renamed_from` on a field: Maps an old payload key onto its current field. It
  is defined in `fields/base.py` and applied on read by `Message._resolve_field_aliases`.
- Lenient deserialization: Drops payload keys the current class no longer
  declares, recording them under `_dropped_fields` in the message metadata. You
  turn it on with the per-class `lenient` meta option or the
  `lenient_deserialization` config key, which `Message._is_lenient` reads. It
  is off by default.
- Upcasters (`@domain.upcaster`): Transform a stored payload on read, in memory,
  from one version to the next. `Message.to_domain_object` walks the chain when a
  stored type string names a version older than the current class. The stored
  event is left unchanged.

Events are versioned with monotonic integers, with the version in the
`__type__` string, as decided in the event-versioning ADR (ADR-0001). It also
said compatibility semantics "are handled by the upcaster chain, not by the
version number itself." Read on its own, that line implies upcasting is the
only path. Both `renamed_from` and lenient deserialization were added later,
and no ADR covers either one. An adopter who renames a field cannot tell which
to do: declare `renamed_from`, bump `__version__` and write an upcaster, or do
both.

Protean should not collapse to one mechanism. Other event-sourcing frameworks
and a published survey keep the same split. Axon, which ADR-0001 already cites,
uses payload conversion for most versioning: added fields with defaults,
removed fields, renames via Jackson's `@JsonAlias`, and type changes via
converters. Axon reserves upcasters for the cases conversion cannot express.
Marten splits the same way. In their empirical survey of event-sourced systems,
[Overeem et
al.](https://www.sciencedirect.com/science/article/pii/S0164121221000674) name
five tactics: versioned events, weak schema, upcasting, in-place
transformation, and copy-and-transform. The survey finds that systems start
with versioned events and weak schema. Systems move to the heavier tactics once
their upcaster chains get long. Protean has the first three tactics: versioned
events, weak schema, and upcasting. Protean lacks the two heavy tactics,
in-place transformation and copy-and-transform.

## Decision

Protean's schema evolution is a ladder: an ordered set of mechanisms, from the
lightest to the heaviest. Each rung covers one class of change. You use the
lightest rung that covers your change.

--8<-- "diagrams/schema-evolution-ladder.md"

### Rung 1: use weak schema for additive and rename changes

You need no version bump when you add a field with a default or rename a field.
When you add the field with a default, Protean decodes old payloads and sets
the field to its default. When you rename a field and declare `renamed_from`,
Protean resolves the old key onto the new field on read. Protean also emits an
Avro `aliases` entry, so an external consumer resolves the old key on the wire
too. Lenient mode is the tolerant-reader half of this rung: turn it on to read
a legacy payload that still carries a since-removed field.

### Rung 2: bump the version and write an upcaster for structural changes

When weak schema cannot express a change (a newly required field, a type
change, a field split or merge), you bump the version and write an upcaster for
each hop. The upcaster transforms the payload on read, in memory, from one
version to the next, and leaves the stored event unchanged. Protean runs the
upcasters in sequence and converts a `v1` payload to the current version before
a handler sees it. This is a read-time transform, distinct from the Rung 3
migrations that rewrite the store. Weak schema cannot transform a stored value.
When a stored value has to be transformed, use this rung, with the one
exception below. An upcaster works only when it can supply the new value from
the old payload. A newly required field with no computable value has no
upcaster to write; replace the event with a new type in that case.

### Rung 3: run an operator-level migration when an upcaster chain costs more than it saves

When maintaining a long upcaster chain costs more than it saves, rewrite the
stored events. Two tactics apply.

- In-place transformation: Rewrites the events in the existing stream to the
  current schema and retags them with the current type and version, so a rewritten
  event no longer takes the upcast path on read.
- Copy-and-transform: Reads the old stream, transforms each event, and writes a
  new stream, keeping the old one for audit.

In-place transformation and copy-and-transform both rewrite the contents of an
event store, which is migration work. Protean treats migration as an adapter
and operator concern, the same stance `upgrade.py` already takes, so core does
not build these tactics. This ADR names both tactics as rung 3, and the
[event-versioning pattern](../patterns/event-versioning-and-evolution.md)
describes copy-and-transform as an operator-level migration. A port-level
rewrite contract can come later if real demand appears.

### Lenient mode

Lenient mode is a permanent, supported mode, the weak-schema rung's tolerant
reader. It stays off by default. When on, it drops any payload key the current
schema does not declare and records the dropped names under `_dropped_fields`
in the message metadata. A removed field's data is then not delivered to the
domain object, though it remains intact in the store. When you can tolerate an
old field's absence, use lenient mode. When the current schema needs a value
transformed from the old data, use an upcaster.

### What this ADR corrects in the event-versioning ADR (ADR-0001)

The versioning decision in the event-versioning ADR (ADR-0001) stands:
monotonic integers, version in the `__type__` string. This ADR corrects one
line. Protean keeps old payloads readable across a schema change with the whole
ladder this ADR defines: weak schema for additive and rename changes,
versioning plus an upcaster for structural ones. The status line of the
event-versioning ADR (ADR-0001) now links to this ADR for compatibility
semantics.

### What this means for snapshots

An event-sourced aggregate snapshot gets none of the three mechanisms:
`renamed_from`, lenient mode, and upcasters. A snapshot is written (for example
by `create_snapshot` in `port/event_store.py`) with the fixed type `SNAPSHOT`
and no metadata. An aggregate carries a `_version` (its event position, used
for optimistic concurrency), but no schema version to upcast from.
`renamed_from`, lenient mode, and upcasters are all consumed by
`Message.to_domain_object`, which a snapshot never reaches. Take an adopter who
declares `renamed_from`, enables lenient mode, and registers upcasters. After a
snapshot-breaking change (a field renamed or removed, or a required field
added), that adopter still has unloadable snapshots. (A field added with a
default still constructs, since the default fills the gap.) With the ladder
defined, the phrase "the same treatment events get" has a fixed meaning. The
snapshot fix (#1362) can then apply to a snapshot the rung that matches its
change.

### Reserve removed names on an event-sourced aggregate

Removing a field from an event-sourced aggregate is its own rung. The three
mechanisms above act on a payload as it is decoded; this one acts on the
aggregate as its stream replays. An event-sourced aggregate's authoritative
state is its event stream. During replay, a retained `@apply` handler for a
retired event can still assign a field that has since been removed. That
assignment would raise under `extra="forbid"` and stop the rebuild.

You prevent that error by declaring the removed name in `reserved` on the
aggregate. During replay only, an assignment to a reserved name is dropped
instead of raising, so the aggregate rebuilds without the removed field. The
live `raise_` path never takes this relaxation, so a write to a removed field
on a new event still raises. `reserved` works like `renamed_from`: the author
adds a declaration, and the declaration changes runtime behaviour. Like
`deprecated`, a `reserved` declaration also gets a safe rating from the
checker. The checker downgrades the change to safe only because of that
declaration, never automatically. Protean raises an error at registration when
a live field reuses a reserved name. The compatibility checker downgrades the
field removal to safe only when the aggregate declares the name.

`reserved` covers a field removal, nothing wider. A type change or a newly
required field on an event-sourced aggregate stays breaking. The replay hazards
(a moved stream category, a moved identity, a dropped handler whose event
survives) also stay their own breaking changes.

The declaration has to stay for as long as the events do. When you take a name
back out of `reserved`, you create a replay hazard in its own right, reported
as `reservation_removed`. Replay then stops dropping the assignment, and the
handler that the reservation kept working raises again.

## Consequences

An adopter facing a schema change now has one place that says which mechanism
applies. The three existing mechanisms are unchanged. The two heavy tactics are
documented as operator migrations outside core.

Each rung carries a cost. Weak schema is cheap and needs no version bump. It
cannot transform a value, so a type change or a newly required field still
forces rung 2. Lenient mode reads old payloads without raising and drops any
data the current schema does not declare. Lenient mode therefore tolerates a
missing field without recovering it. Rung 3 rewrites a store and belongs to
operators, so a long chain becomes a migration project.

This ADR does not fix the snapshot gap. The snapshot fix issue (#1362) tracks
that work.

## Alternatives Considered

**Collapse to a single mechanism.** Route every change through upcasters, or
through weak schema alone. Rejected because neither mechanism covers the
other's cases. Weak schema cannot transform a stored value. An upcaster is more
code than a rename needs, because an alias covers a rename by declaration
alone. The prior art (Axon, Marten, the Overeem survey) keeps the split for the
same reason.

**Build in-place transformation and copy-and-transform into core.** Rejected
because both tactics rewrite the contents of an event store. Rewriting an event
store is a migration and an operator concern. If core built a stream-rewrite
engine, infrastructure responsibility would move across the port boundary.
`upgrade.py` already states that migrations are an adapter and operator
concern. This ADR describes the tactics. A port-level rewrite contract can come
later, when real demand appears.
