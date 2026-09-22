# ADR-0040: The Schema-Evolution Ladder

**Status:** Accepted

**Date:** September 2026

## Context

An event is immutable once stored (only a deliberate operator migration rewrites
it), but the code that reads it keeps changing. A field gets renamed, a new one
is added, an old one is dropped. Months later a
handler still has to decode a payload written by last year's schema. Protean has
three mechanisms for surviving that drift, and until now no written rule for
which one to reach for.

- `renamed_from` on a field: Maps an old payload key onto its current field. It
  is defined in `fields/base.py` and applied on read by `Message._resolve_field_aliases`.
- Lenient deserialization: Drops payload keys the current class no longer
  declares, recording them under `_dropped_fields` in the message metadata. It
  is the per-class `lenient` meta option or the `lenient_deserialization` config
  key, read by `Message._is_lenient`, and it is off by default.
- Upcasters (`@domain.upcaster`): Transform a stored payload on read, in memory,
  from one version to the next. `Message.to_domain_object` walks the chain when a
  stored type string names a version older than the current class. The stored
  event is left unchanged.

ADR-0001 settled how events are versioned: monotonic integers, with the version
in the `__type__` string. It also said compatibility semantics "are handled by
the upcaster chain, not by the version number itself." Read on its own, that
line implies upcasting is the only path. Both `renamed_from` and lenient mode
were added afterwards and neither is covered by an ADR, so an adopter renaming a
field cannot tell whether to declare `renamed_from`, bump `__version__` and write
an upcaster, or do both.

Collapsing to one mechanism is the wrong instinct, and prior art confirms it.
Axon, which ADR-0001 already cites, uses payload conversion (added fields with
defaults, removed fields, renames via Jackson's `@JsonAlias`, type changes via
converters) for most versioning and reserves upcasters for the cases conversion
cannot express. Marten splits the same way. The empirical survey of
event-sourced systems by [Overeem et al.](https://www.sciencedirect.com/science/article/pii/S0164121221000674)
names five tactics: versioned events, weak schema, upcasting, in-place
transformation, and copy-and-transform. It finds that systems start with
versioned events and weak schema and grow into the heavier tactics as chains get
long. Protean has the first three. It lacks the two heavy ones.

## Decision

Protean's schema evolution is a ladder. Each rung handles a class of change, and
you climb only as far as the change forces you to.

--8<-- "diagrams/schema-evolution-ladder.md"

### Rung 1: weak schema, for additive and rename changes

A field added with a default, or a field renamed, needs no version bump. Add the
field with a default and old payloads decode with the default filling the gap.
Rename a field by declaring `renamed_from` and Protean resolves the old key onto
the new field on read, and emits an Avro `aliases` entry so an external consumer
resolves it on the wire too. Lenient mode is the tolerant-reader half of this
rung: turn it on to read a legacy payload that still carries a since-removed
field.

### Rung 2: versioning plus an upcaster, for structural changes

A change weak schema cannot express (a newly required field, a type change, a
field split or merge) needs the version bumped and an upcaster for each hop. The
upcaster transforms the payload on read, in memory, from one version to the next,
leaving the stored event unchanged; Protean chains them so a `v1` payload is
walked up to the current version before a handler sees it. This is a read-time
transform, distinct from the Rung 3 migrations that rewrite the store. Use this
rung whenever a stored value has to be transformed, which weak schema cannot do.
An upcaster works only when it can supply the new value from the old payload. A
newly required field with no computable value has no upcaster to write; replace
the event with a new type in that case.

### Rung 3: an operator-level migration, for a chain grown past usefulness

When an upcaster chain has grown long enough that maintaining it costs more than
it saves, the answer is to rewrite the stored events. Two tactics apply.

- In-place transformation: Rewrites the events in the existing stream to the
  current schema and retags them with the current type and version, so a rewritten
  event no longer takes the upcast path on read.
- Copy-and-transform: Reads the old stream, transforms each event, and writes a
  new stream, keeping the old one for audit.

Both rewrite the contents of an event store, which is migration work. Protean
treats migration as an adapter and operator concern, the same stance `upgrade.py`
already takes, so core does not build these tactics. The ladder names them and
documents copy-and-transform as an operator-level migration in the
[event-versioning pattern](../patterns/event-versioning-and-evolution.md). A
port-level rewrite contract can come later if real demand appears.

### Lenient mode

Lenient mode is a permanent, supported mode, the weak-schema rung's tolerant
reader. It stays off by default. When on, it drops any payload key the current
schema does not declare and records the dropped names under `_dropped_fields` in
the message metadata. A removed field's data is then not delivered to the domain
object, though it remains intact in the store. Use lenient mode when you can
tolerate an old field's absence; use an upcaster when the old data has to be
transformed into a value the current schema needs.

### The correction to ADR-0001

ADR-0001's versioning decision stands: monotonic integers, version in the
`__type__` string. This ADR corrects one line. Compatibility across a schema
change is handled by the whole ladder: weak schema for additive and rename
changes, versioning plus an upcaster for structural ones. ADR-0001's status line
now points here for compatibility semantics.

### What this means for snapshots

An event-sourced aggregate snapshot gets none of these three mechanisms. A
snapshot is written (for example by `create_snapshot` in `port/event_store.py`)
with the fixed type `SNAPSHOT` and no metadata. An aggregate carries a `_version`
(its event position, used for optimistic concurrency), but no schema version to
upcast from, and `renamed_from`, lenient mode, and upcasters are all consumed by
`Message.to_domain_object`, which a snapshot never reaches. So an adopter who declares `renamed_from`, enables
lenient mode, and registers upcasters still has unloadable snapshots after a
snapshot-breaking change: a field renamed or removed, or a required field added.
(A field added with a default still constructs, since the default fills the gap.) The ladder settles what "the same treatment events get" means, so
the snapshot fix (#1362) can align a snapshot with the rung that matches its
change.

### Reserved names on an event-sourced aggregate

Removing a field from an event-sourced aggregate is its own rung. The three
mechanisms above act on a payload as it is decoded; this one acts on the
aggregate as its stream replays. An event-sourced aggregate's authoritative
state is its event stream, and a retained `@apply` handler for a retired event
can still assign a field that has since been removed. That assignment would raise
under `extra="forbid"` and stop the rebuild.

Declaring the removed name in `reserved` on the aggregate settles it. During
replay only, an assignment to a reserved name is dropped instead of raising, so
the aggregate rebuilds without the removed field. The live `raise_` path never
takes this relaxation, so a write to a removed field on a new event still raises.
This is the same shape as `renamed_from` and `deprecated`: a declaration that
does the migration work. The downgrade is earned by that declaration, never
applied automatically. Reusing a reserved name for a live field raises at
registration, and the compatibility checker downgrades the field removal to safe
only when the aggregate declares the name.

`reserved` covers a field removal, nothing wider. A type change or a newly
required field on an event-sourced aggregate stays breaking, and the replay
hazards (a moved stream category, a moved identity, a dropped handler whose event
survives) stay their own breaking changes.

## Consequences

An adopter facing a schema change now has one place that says which mechanism
applies. The three existing mechanisms are unchanged, and the two heavy tactics
are documented as operator migrations outside core.

Each rung carries a cost. Weak schema is cheap and needs no version bump. It
cannot transform a value, so a type change or a newly required field still forces
rung 2. Lenient mode reads old payloads without raising, and it drops any data
the current schema does not declare, so it tolerates a missing field without
recovering it. Rung 3 rewrites a store and belongs to operators, so a long chain
becomes a migration project.

The snapshot gap is not fixed here. #1362 tracks that work.

## Alternatives Considered

**Collapse to a single mechanism.** Route every change through upcasters, or
through weak schema alone. Rejected because neither covers the other's cases:
weak schema cannot transform a stored value, and an upcaster is heavy machinery
for a rename that an alias handles declaratively. The prior art (Axon, Marten,
the Overeem survey) keeps the split for the same reason.

**Build in-place transformation and copy-and-transform into core.** Rejected
because both rewrite the contents of an event store, which is a migration and an
operator concern. Building a stream-rewrite engine into core would move
infrastructure responsibility across the port boundary, and `upgrade.py` already
states that migrations are an adapter and operator concern. The ADR documents the
tactics and leaves a port-level rewrite contract for later, gated on real demand.
