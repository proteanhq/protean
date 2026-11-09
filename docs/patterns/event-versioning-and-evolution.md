# Event Versioning and Evolution

## The Problem

Six months after launch, the business asks for a change: orders should now
track a `discount_code` field. The developer adds the field to the `Order`
aggregate and to the `OrderPlaced` event:

```python
--8<-- "patterns/event-versioning-and-evolution/001.py:problem"
```

The change works for new orders. But in an event-sourced system, the event
store contains thousands of old `OrderPlaced` events that were written
*without* `discount_code`. When the system replays these events to rebuild
an aggregate, the old events don't match the new class definition. If
`discount_code` were marked `required=True`, every historical event would
fail validation.

Even in non-event-sourced systems, event handlers and projectors process
events from a stream. When a consumer catches up on historical events after
a deployment, it encounters old events with the old schema. If the consumer
expects the new field, it breaks.

The fundamental tension: **events are immutable facts stored forever, but the
domain model evolves continuously**.

This tension produces specific failure modes:

- **Deserialization failures**: Old events lack new required fields. The
  deserializer raises an error, halting event replay or subscription processing.

- **Consumer breakage**: A projector expects `event.discount_code` but
  encounters an old event without it. The projector crashes or produces
  incorrect projections.

- **Silent data corruption**: An old event has a field with different semantics
  than the current definition. The consumer processes it with current-version
  logic, producing subtly wrong results.

- **Deployment coupling**: If all consumers must be updated simultaneously when
  an event schema changes, you lose the ability to deploy services independently.

---

## The Pattern

Evolve event schemas **backward-compatibly** by default. When backward
compatibility is impossible, use explicit versioning and transformation
strategies to bridge old and new schemas.

The golden rules:

1. **New fields get defaults where possible**: A default keeps old payloads
   readable. When no sensible default exists, use an upcaster or a new event
   type (rule 4).
2. **Old fields stay by default**: Keep and deprecate an unused field so old
   payloads stay deserializable. To remove one, enable lenient mode, which
   drops the field on read and discards its data
   (see [ADR-0040](../adr/0040-schema-evolution-ladder.md)).
3. **Semantics never change**: A field's meaning is permanent. If the meaning
   changes, create a new field or a new event type.
4. **Structural changes are versioned**: When weak schema cannot express a
   change (a type change, a newly required field), you bump the version and add
   an upcaster. When no transformation can convert the old payload, you retire
   the old event type and create a new one.

---

## Backward-Compatible Changes

These changes keep old events readable without an upcaster. One exception
applies to events: an added or renamed field that changes the sorted order of
field names moves Protobuf field numbers, and that needs a version bump (see
below).

### Adding Optional Fields with Defaults

The most common evolution. Add a new field with a default value that preserves
the behavior of events written before the field existed:

```python
--8<-- "patterns/event-versioning-and-evolution/002.py:before"
--8<-- "patterns/event-versioning-and-evolution/003.py:after"
```

Old events deserialize successfully: `discount_code` is `None`, `channel` is
`"web"`. Consumers that don't know about the new fields ignore them. Consumers
that do know about them treat `None` / `"web"` as the legacy case.

Protean numbers an event's Protobuf fields in sorted name order. `channel` and
`discount_code` sort before `order_id`, so this change moves the numbers of the
fields after them, and `protean ir diff` reports it as breaking
(`field_number_changed`) while `__version__` stays the same. To ship this change,
bump `__version__` and register an upcaster for the old version, which may return
the payload unchanged. A new field whose name sorts after every existing field
moves no number and needs no bump.

**Rules for adding fields:**

- Never mark new fields as `required=True` on an existing event type
- Choose defaults that preserve pre-change behavior
- Document when the field was added (useful for consumers that reason about
  event history)

### Adding New Event Types

When a new business operation is introduced, create a new event type:

```python
--8<-- "patterns/event-versioning-and-evolution/003.py:new_type"
```

Existing consumers keep working when you add a new event type. Consumers that
don't handle `OrderGiftWrapped` ignore it.

### Widening Field Types

Changing a field's type to accept a broader range of values is safe if the
serialization format is compatible:

```python
# fragment
# Before: status as String with limited choices
status = String(choices=["pending", "shipped"])

# After: status with more choices
status = String(choices=["pending", "shipped", "returned", "refunded"])
```

Old events still match. New events use the expanded set of choices. Consumers
should already process unknown values without failing.

### Renaming a Field

Renaming a field is normally a breaking change: the old key disappears and a
new one takes its place, so stored payloads no longer match. Declare the old
name with `renamed_from` to make the rename backward-compatible instead:

```python
--8<-- "patterns/event-versioning-and-evolution/004.py:before"
--8<-- "patterns/event-versioning-and-evolution/005.py:after"
```

A stored payload written with the old `name` key now deserializes into
`customer_name` without an upcaster. `renamed_from` also accepts a list of
aliases (`renamed_from=["name", "full_name"]`) when a field has been renamed
more than once. The compatibility checker reads the declared rename and reports
a safe `field_renamed` change rather than a breaking remove + add, with the
exceptions below. Keep the `renamed_from` declaration for as long as payloads
written under the old name may still be read.

A rename only stays safe when the field type is unchanged: renaming *and*
changing the type (say `String` to `Integer`) is still breaking, because an
old payload's value cannot satisfy the new type. The checker reports that as a
`field_type_changed` change. Write an upcaster to convert the old value to the
new type. A `Decimal` field renamed with a lower or newly added `precision`, or
a different `scale`, is breaking the same way. So is a `Dict` or `List` field
renamed with a value type that was added, changed or removed.

A rename on an event also needs a version bump when it moves a Protobuf field
number. Protean numbers an event's Protobuf fields in sorted name order, so a
rename that changes where a field sorts moves the numbers of the fields that
sort between its old and new name. Within one `__version__` the checker reports
that as a breaking `field_number_changed` change. Bump `__version__` and
register an upcaster for the old version, which may return the payload
unchanged.

---

## Strategies for Breaking Changes

When backward-compatible evolution isn't possible, use one of these strategies:

### Strategy 1: New Event Type

The cleanest approach for significant schema changes. Create a new event type
and keep the old one for historical events:

```python
--8<-- "patterns/event-versioning-and-evolution/006.py:event_types"
```

The aggregate now raises `OrderPlacedV2`. Consumers must handle both types:

```python
--8<-- "patterns/event-versioning-and-evolution/006.py:handler"
```

**When to use:** Significant structural changes, changed semantics, new required
fields whose value cannot be computed from historical data, or a rename bundled
with one of those. A pure rename uses `renamed_from` and needs no new event type.
When you can compute a required field's value from the old payload, use an
upcaster (Rung 2 of the schema-evolution ladder).

#### Marking the old event deprecated

Once the aggregate raises the new event, mark the old one deprecated and point
`superseded_by` at its replacement:

```python
--8<-- "patterns/event-versioning-and-evolution/007.py:domain"
--8<-- "patterns/event-versioning-and-evolution/007.py:deprecated"
```

The old class stays registered so historical events keep deserializing, but
Protean now flags its continued use in two ways:

- **Raising it warns**: If code still calls `raise_(OrderPlaced(...))`, Protean
  emits a `ProteanDeprecationWarning` naming the successor. The warning fires
  **once per event type** and not once per instance, so code that raises the
  event often gets one warning and does not fill the logs with repeats.
- **`protean check` reports it**: The `DEPRECATED_ELEMENT` diagnostic names the
  successor (`superseded by \`OrderPlacedV2\``). `protean ir diff` treats
  removing the old event before its `removal` version as a premature
  (breaking) removal.

`superseded_by` is documentation-only. It accepts an Event class or a name
string, and Protean never resolves it to a link, so you can point it at an
event in another bounded context.

### Strategy 2: Upcasting on Read

Transform old events to the new schema when they're read from the event store,
before they reach the handler. This keeps handlers simple. They only see the
latest schema.

Protean provides built-in upcasting via the `@domain.upcaster` decorator. Each
upcaster transforms raw event data from one version to the next. The framework
chains upcasters automatically so that a v1 event passes through v1→v2 and
v2→v3 before reaching handlers.

```python
--8<-- "patterns/event-versioning-and-evolution/008.py:import"
--8<-- "patterns/event-versioning-and-evolution/008.py:upcasters"
```

Upcasting happens transparently during deserialization, between reading the raw
message from the event store and constructing the typed event object. All
handlers (`@apply`, `@handle`, projectors) always receive the current schema, regardless
of which version was originally stored.

**When to use:** Type changes, field splits or merges, or calculated new fields
where a reasonable transformation exists. Useful when you don't want handlers to
know about historical schemas. A pure rename uses `renamed_from` and needs no
upcaster, unless it moves a Protobuf field number.

**Trade-off:** Upcasting adds a processing layer and must be maintained as
schemas evolve further. Each version needs an upcaster to the next.

See the [Event Upcasting guide](../guides/consume-state/event-upcasting.md) for a complete
walkthrough with real-world examples.

### Strategy 3: Tolerant Reader

Design consumers to be tolerant of fields an event may not carry:

```python
--8<-- "patterns/event-versioning-and-evolution/009.py:handler"
```

The consumer reads whatever fields are present and provides sensible defaults
for missing ones. This is pragmatic but can lead to scattered
default-handling logic.

**When to use:** Consumers that don't require strict schemas (analytics,
logging, monitoring). Not suitable for consumers that need precise data
(financial calculations, projections).

### Lenient Deserialization (read-path escape hatch)

When you must read genuinely legacy payloads that still carry fields the
current event no longer declares, opt into **lenient deserialization**. Set
`lenient_deserialization = true` in `domain.toml` (or override per event with
`@domain.event(lenient=True)`); the deserializer then drops unknown fields
(recording their names in the message metadata) instead of raising
`DeserializationError`. It is **opt-in**: the default is strict, so a typo or
genuine schema drift still fails loudly. Use lenient deserialization only on
the read path for legacy data; for *structural* evolution, an upcaster is the
precise tool.

**When to use:** Reading old payloads that carry since-removed fields, where no
upcaster exists. Not a substitute for upcasting when a value needs transforming.

---

## Fact Events and Schema Evolution

Protean's `fact_events=True` auto-generates events from the aggregate's
current schema. When the aggregate changes, fact events automatically reflect
the new schema.

This simplifies some evolution scenarios but creates others:

```python
--8<-- "patterns/event-versioning-and-evolution/010.py:fact_events"
```

**Benefits:**

- Each fact event matches the aggregate's schema at the time Protean raises it
- No manual event class maintenance
- Projections that mirror the aggregate get updates automatically

**Risks:**

- Historical fact events in the store have the old schema (no `currency`)
- Consumers that process historical fact events must handle missing fields
- Adding a new required field to the aggregate changes the fact event schema

**Mitigation:**

- Treat fact events as eventually-consistent snapshots, not as precise
  historical records
- Use delta events for precise historical semantics
- When you use fact events, give every new aggregate field a default

---

## Naming Conventions for Versioned Events

When creating new event versions, use clear naming:

| Approach | Example | When to Use |
|----------|---------|-------------|
| Suffix version | `OrderPlacedV2` | Clear versioning, easy to search |
| Descriptive name | `OrderPlacedWithCurrency` | When the change has business meaning |
| Namespace | `v2.OrderPlaced` | When many events change together |

The suffix approach (`V2`, `V3`) is the most common because it's simple and
unambiguous. Avoid descriptive names for minor changes. They become unwieldy
(`OrderPlacedWithCurrencyAndDiscount`).

---

## Event Store Considerations

### Never Modify Stored Events

Events in the store are immutable historical records. Never update, delete, or
"fix" stored events. If an event was written incorrectly, handle it through
upcasting or compensating events. Rewriting a whole stream during a deliberate
operator migration (see [Migration Strategies](#migration-strategies)) is the one
exception to this rule; a single stored event is never edited in place.

```python
--8<-- "patterns/event-versioning-and-evolution/011.py:correcting_event"
```

### Stream Position After Schema Changes

When you deploy a schema change, existing events in the stream remain
unchanged. New events use the new schema. The stream contains a mix of old
and new schemas. Consumers must handle both. A mixed stream is the normal
result of a deployment. A deliberate operator migration (see
[Migration Strategies](#migration-strategies)) is the one thing that rewrites
existing events.

### Snapshots and Schema Changes

Snapshots do not go through the upcaster path. A snapshot holds aggregate
state, so a change to an event's schema does not invalidate it on its own. When
the aggregate's own fields change and the stored snapshot no longer constructs,
Protean discards it on load and rebuilds the aggregate by replaying its event
stream. See [Snapshots and schema
changes](../guides/change-state/snapshots.md#snapshots-and-schema-changes) for
the full mechanism.

### Replaying from the Beginning

If you replay an event-sourced aggregate from the beginning of its stream,
it will encounter every historical event version.

**With upcasting (recommended):** Register upcasters and keep a single
`@apply` handler per event type. The framework transforms old events before
they reach the handler:

```python
--8<-- "patterns/event-versioning-and-evolution/012.py:aggregate"
```

**Without upcasting:** The `@apply` handlers must handle all versions
manually, either with separate handlers for each version or tolerant-reader
patterns:

```python
--8<-- "patterns/event-versioning-and-evolution/013.py:aggregate"
```

---

## Migration Strategies

An upcaster chain can grow long enough that maintaining it costs more than it
saves. At that point, rewrite the stored events once, so no upcaster runs on
every read. A one-time rewrite is the top rung of the
[schema-evolution ladder](../adr/0040-schema-evolution-ladder.md), the ordered
list of evolution strategies. The copy-transform pattern and in-place
transformation both rewrite the contents of an event store. That is migration
work, so Protean leaves both to operators and does not build them into core.

### The Copy-Transform Pattern

For large schema changes, create a new stream with transformed events:

1. Read events from the old stream
2. Transform each event to the new schema
3. Write to a new stream
4. Switch consumers to the new stream
5. Keep the old stream for audit purposes

Copy-transform copies and transforms every event in the stream, so it is
costly, but the new stream holds no events in historical schemas.

### In-Place Transformation

In-place transformation rewrites the events in the existing stream to the
current schema. It also retags them with the current type and version, so a
rewritten event no longer goes through upcasting on read. It keeps the stream
name and skips the consumer cutover that copy-transform needs. But it loses the
original payloads unless you archive them first. When the old schema has no
audit value and the stream name must stay stable, use in-place transformation.

### The Dual-Write Transition

During a migration period, produce both old and new event types:

```python
# fragment
def place(self):
    # Raise both old and new events during transition.
    # For ES aggregates, each raise_() invokes its @apply handler —
    # ensure only one handler performs the actual state mutation.
    self.raise_(OrderPlaced(
        order_id=self.order_id,
        customer_id=self.customer_id,
        items=[item.to_dict() for item in self.items],
        total=self.total,
    ))

    self.raise_(OrderPlacedV2(
        order_id=self.order_id,
        customer_id=self.customer_id,
        line_items=[item.to_dict() for item in self.items],
        subtotal=self.total - self.tax,
        tax=self.tax,
        total=self.total,
        currency=self.currency,
    ))

@apply
def on_order_placed(self, event: OrderPlaced):
    """V1 handler — performs the actual state mutation."""
    self.status = "placed"
    self.customer_id = event.customer_id
    self.total = event.total

@apply
def on_order_placed_v2(self, event: OrderPlacedV2):
    """V2 handler — no-op during dual-write, since V1 already set state."""
    pass
```

Consumers migrate from `OrderPlaced` to `OrderPlacedV2` at their own pace.
Once all consumers have migrated, stop raising the old event and move the
state mutation logic into `on_order_placed_v2`.

**Trade-off:** The aggregate raises two events for every operation during
the transition period. Events in the store contain duplicated information.
Keep the transition period short.

---

## Anti-Patterns

### Changing Field Semantics

```python
# fragment
# Version 1: total includes tax
class OrderPlaced(BaseEvent):
    total: Float()  # Includes tax

# Version 2: total excludes tax (BREAKING CHANGE)
class OrderPlaced(BaseEvent):
    total: Float()  # Now excludes tax
```

The field name is the same, but the meaning changed. Every consumer that
processes historical events will compute wrong values. Create a new field
instead: `subtotal` for the tax-exclusive amount.

### Removing Fields

```python
# fragment
# Version 1
class OrderPlaced(BaseEvent):
    customer_name: String()

# Version 2: removed customer_name (BREAKING CHANGE)
class OrderPlaced(BaseEvent):
    pass  # customer_name removed
```

Consumers that expect `customer_name` will crash. Even if no current consumer
needs it, historical events in the store still carry the field. Keep the field
and deprecate it in documentation.

### Required Fields on Existing Events

```python
# fragment
# NEVER add a required field to an existing event
class OrderPlaced(BaseEvent):
    order_id: Identifier(required=True)
    currency: String(required=True)  # BREAKS all historical events
```

Historical events don't have `currency`, so deserialization fails. Give a new
field a default, or supply the value with an upcaster when it can be computed, or
create a new event type. The Decision Guide below lists the routes.

---

## Decision Guide

This diagram shows the schema-evolution ladder:

--8<-- "diagrams/schema-evolution-ladder.md"

| Change Type | Safe? | Strategy |
|-------------|-------|----------|
| Add optional field with default | Yes | add it (bump the version and add an upcaster if the new field moves a Protobuf field number) |
| Add new event type | Yes | Add handler methods |
| Add more choices to a field | Yes | Consumers handle unknowns |
| Rename a field | Yes | `renamed_from` (same type, no version bump unless the rename moves a Protobuf field number) |
| Remove a field | With lenient mode | Deprecate, or read old payloads leniently (drops its data) |
| Change field type | No | Version bump + upcaster, or a new field / event type |
| Change field semantics | No | New field name |
| Add required field without default | No | Give it a default, an upcaster to supply a computable value, or a new event type |
| Split event into multiple events | No | New event types + transition period |

---

## Summary

| Aspect | Approach |
|--------|----------|
| Adding data | Optional fields with defaults |
| New operations | New event types |
| Renamed fields | `renamed_from` (weak schema) |
| Changed semantics | New field name or new event type |
| Consumer compatibility | Tolerant reader pattern |
| Historical replay | Upcasters normalize old events so @apply handlers see the current schema; without upcasters, handle each version in the handler |
| Large migrations | In-place transformation, copy-transform, or dual-write transition |
| Stored events | Appended to in normal operation; rewritten only by an operator migration |

Events are permanent contracts. Evolve them the way you evolve APIs. Additive
changes are safe, unless they move a Protobuf field number, which needs a version
bump. Structural changes are versioned or replaced. New fields get defaults. Old fields stay unless you opt into lenient reads, which drop them.
Semantics never change. When in doubt, create a new event type.

---

!!! tip "Related reading"
    **Concepts:**

    - [Events](../concepts/building-blocks/events.md): Event fundamentals, versioning, and immutability.

    **Guides:**

    - [Evolving Events Over Time](../guides/evolving-events.md): The how-to guide for this page, which follows one running example through the end-to-end evolution workflow.
    - [Event Upcasting](../guides/consume-state/event-upcasting.md): The upcaster mechanism in depth.
    - [Events](../guides/domain-definition/events.md): Event structure, metadata, and versioning reference.

    **Tooling:**

    - [`protean events catalog`](../reference/cli/data/events.md): List every event with its version, deprecation/supersession, and upcaster chain.
    - [`protean schema generate --format`](../reference/cli/schema.md): Emit JSON Schema, Avro, or Protobuf contracts.
    - [`protean ir diff`](../reference/cli/ir.md): Avro-style `BACKWARD`/`FORWARD`/`FULL`/`NONE` compatibility verdict for a change.
