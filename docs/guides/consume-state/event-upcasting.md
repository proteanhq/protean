# Upcast old events to the current schema

## Why do old events fail to load?

In an event-sourced system, the event store is the source of truth. Events are
immutable facts stored forever. But the domain model evolves: fields get
renamed, new required fields are added, semantics change. When the system
replays old events to reconstruct an aggregate, those events must match the
current event class definition, or deserialization fails.

Without upcasting, developers face two unsatisfying choices:

1. **Scatter version-handling logic across `@apply` handlers** using `getattr`
   with defaults, duplicating defensive code everywhere.

2. **Maintain separate event classes for every version** (`OrderPlacedV1`,
   `OrderPlacedV2`, `OrderPlacedV3`), each with its own `@apply` handler,
   creating a growing maintenance burden.

Upcasting solves this by transforming old event payloads to the current schema
**before** they reach any handler. Handlers always see the latest version.

---

## How It Works

Protean's upcasting works at the `Message` level, between raw event store
storage and typed event construction:

```
Event Store → raw dict → Message.deserialize()
                            ↓
                   Message.to_domain_object()
                            ↓
                   ┌─ type string lookup ─┐
                   │  "Domain.Event.v1"   │
                   │  ↓ not found         │
                   │  check upcaster chain│
                   │  ↓ found             │
                   │  apply v1→v2→v3      │
                   │  ↓                   │
                   │  construct current   │
                   │  event class         │
                   └──────────────────────┘
                            ↓
                   typed Event object (current schema)
                            ↓
                   @apply / @handle / projector
```

**Key properties:**

- **Lazy**: Upcasting happens on read, not as a batch migration.
- **Zero overhead for current events**: The fast path (direct type-string
  lookup) is tried first. Upcasting only activates when the stored version
  doesn't match the current version.
- **Automatic chaining**: Register individual steps (v1→v2, v2→v3) and the
  framework chains them into v1→v2→v3 automatically.
- **Validated at startup**: During `domain.init()`, the framework validates
  that chains are complete, have no gaps or cycles, and converge to the
  current event version.

---

## Defining Upcasters

An upcaster is a class that extends `BaseUpcaster` and implements a single
method: `upcast(self, data: dict) -> dict`.

```python
--8<-- "guides/consume-state/event-upcasting/001.py:full"
```

### Which options does the decorator take?

| Option | Type | Description |
|--------|------|-------------|
| `event_type` | Event class or `str` | The event this upcaster targets (always the *current* class). A string is resolved by name, so a forward reference works. |
| `from_version` | `int` | The source version this upcaster transforms from (e.g. `1`). |
| `to_version` | `int` | The target version this upcaster transforms to (e.g. `2`). |

### The `upcast` Method

- Receives the raw event payload as a Python `dict`.
- Must return the transformed `dict`.
- Operates on raw data **before** Protean constructs the typed event object.
  Field types are therefore in their serialized form (strings, numbers, lists,
  dicts).
- Should be **fast and side-effect-free**, no database queries, no I/O.
  Upcasting runs on every deserialization.
- May mutate the input dict in place or return a new dict.

---

## Apply upcasters to common schema changes

### Scenario 1: Adding a New Required Field

Your `OrderPlaced` event originally had no `currency` field. Now you need to
track currency, and it's required for correct calculations.

**Before (v1):**
```python
--8<-- "guides/consume-state/event-upcasting/002.py:before"
```

**After (v2):**
```python
--8<-- "guides/consume-state/event-upcasting/001.py:after"
```

**Upcaster:**
```python
--8<-- "guides/consume-state/event-upcasting/001.py:upcaster"
```

### Scenario 2: Renaming a Field

The field `customer_name` was split into `first_name` and `last_name`.

**Define the current event and its upcaster:**
```python
--8<-- "guides/consume-state/event-upcasting/003.py:current"

--8<-- "guides/consume-state/event-upcasting/003.py:split-name"
```

`split(" ", 1)` splits on the first space only, so "Mary Ann Evans" becomes
`first_name="Mary"` and `last_name="Ann Evans"`. Every v1 event stored a
`customer_name`, so the upcaster reads it without a default. If a stored event
lacks `customer_name`, Protean fails to load the event and raises a
`DeserializationError` naming `customer_name`.

### Scenario 3: Changing Data Structure

An address was stored as flat fields and is now a nested dict (to match a
new `Address` value object).

**Upcaster:**
```python
--8<-- "guides/consume-state/event-upcasting/003.py:nest-address"
```

### Scenario 4: Chain upcasters across several versions

When events evolve through multiple versions, each step gets its own upcaster.
The framework chains them automatically.

```python
--8<-- "guides/consume-state/event-upcasting/004.py:chain"
```

A stored v1 event automatically passes through both upcasters: v1→v2→v3. A
stored v2 event passes through only v2→v3. A stored v3 event skips upcasting
entirely (zero overhead). The v2→v3 step reads `amount` without a default. If a
stored event lacks `amount`, Protean fails to load the event and raises a
`DeserializationError` naming `amount`.

The `amount → total_amount` step renames a field inside a version bump to show
how the chain composes. A rename on its own uses `renamed_from` and needs no
version bump. The decision table below shows which change calls for which tool.

### Scenario 5: Removing an Obsolete Field

The `legacy_code` field was never used by any handler but was stored in v1
events. In v2, the event schema no longer includes it. The upcaster removes
`legacy_code` so the current constructor doesn't receive unknown fields:

```python
--8<-- "guides/consume-state/event-upcasting/005.py:upcaster"
```

### Scenario 6: Computing a Derived Field

The v2 schema adds a `line_item_count` field that can be computed from existing
data:

```python
--8<-- "guides/consume-state/event-upcasting/006.py:upcaster"
```

---

## How do upcasters work with event-sourced aggregates?

Upcasting is especially important for event-sourced aggregates because every
aggregate reconstruction replays every event from the stream (or from the last
snapshot). Without upcasting, `@apply` handlers must accommodate every
historical schema variant. A snapshot itself does not go through this upcaster
path; see [Snapshots](../../concepts/internals/event-upcasting.md#upcasting-does-not-apply-to-snapshots)
for what happens to a snapshot taken under an old schema.

**With upcasting**, `@apply` handlers are clean and only handle the current
schema:

```python
--8<-- "guides/consume-state/event-upcasting/004.py:aggregate"
```

When the event store contains events from different eras:

```
Position 0: OrderPlaced v1  {"order_id": "1", "amount": 100}
Position 1: OrderCredited v1  {"order_id": "1", "amount": 10}
Position 2: OrderPlaced v3  {"order_id": "1", "total_amount": 50, "currency": "EUR"}
```

The framework automatically applies upcasters to position 0 (v1→v2→v3)
before passing it to the `@apply` handler. Positions 1 and 2 are already at
their current version and pass through with zero overhead.

---

## How do upcasters work with event handlers and projectors?

Upcasting also applies to asynchronous event processing. When an event handler
or projector reads events from a subscription, old events are upcast before
reaching the `@handle` method:

```python
--8<-- "guides/consume-state/event-upcasting/004.py:handler"
```

This means you can rebuild projections from scratch (replaying all events) and
old events are automatically transformed to the current schema.

---

## What does Protean check at startup?

During `domain.init()`, the framework validates all registered upcaster chains.
The following errors are caught at startup (not at runtime):

### Two upcasters share the same source version

```python
# fragment
# ERROR: Two upcasters for the same (event_type, from_version)
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcasterA(BaseUpcaster): ...

@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcasterB(BaseUpcaster): ...
# → ConfigurationError: Duplicate upcaster for OrderPlaced from version 1
```

### Upcasters form a version cycle

```python
# fragment
# ERROR: v1→v2 and v2→v1 creates a cycle
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class Forward(BaseUpcaster): ...

@domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=1)
class Backward(BaseUpcaster): ...
# → ConfigurationError: Upcaster chain does not converge
```

### The chain does not converge to one version

```python
# fragment
# ERROR: 1→2 and 3→4 leave two terminal versions
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class BranchA(BaseUpcaster): ...

@domain.upcaster(event_type=OrderPlaced, from_version=3, to_version=4)
class BranchB(BaseUpcaster): ...
# → ConfigurationError: does not converge to a single current version
```

### No event class exists for the terminal version

```python
# fragment
# ERROR: Chain ends at 99, but OrderPlaced.__version__ is 2
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=99)
class WrongTarget(BaseUpcaster): ...
# → ConfigurationError: no event is registered with type string ...v99
```

### Version gaps (`protean check`)

The errors above are *hard* failures at `domain.init()`. A subtler problem
passes startup but fails at read time: the upcasters for an event do not cover
every version below its `__version__`. Protean then cannot upcast an old stored
payload to the current version. `protean check` flags this at build time as an
`UPCASTER_GAP` **warning**. For example, an event at `__version__` 3 with only
a `2→3` upcaster leaves stored `v1` payloads unreadable. Add an upcaster
covering the missing versions. If no payloads at those versions were ever
stored, you can ignore the warning instead.

---

## How should you write upcasters?

### Follow these practices

- **One upcaster per version step**: Keep transformations small and focused.
  v1→v2 does one thing, v2→v3 does another.
- **Keep upcasters pure**: No I/O, no database queries, no external API calls.
  Upcasting runs on every deserialization and must be fast.
- **Test upcasters independently**: They are simple dict→dict functions and
  easy to unit test.
- **Place upcasters near the event they transform**: In the same module or a
  dedicated `upcasters.py` module within the same domain concept.
- Whenever you register a new upcaster targeting an event class, **bump
  `__version__`** on that class.

### Avoid these mistakes

- **Don't skip versions in the chain**: If the current version is v3, you need
  both v1→v2 and v2→v3 upcasters. A direct v1→v3 upcaster is valid only if
  there was no v2 in production.
- **Don't modify the stored event**: Upcasting transforms data in memory during
  deserialization. Protean never modifies the event store. Rewriting stored
  events is a separate, deliberate operator migration (see [Migration
  Strategies](../../patterns/event-versioning-and-evolution.md#migration-strategies)).
- **Don't use upcasting for semantic changes**: If the *meaning* of an event
  changes (not just its structure), create a new event type instead.
- **Don't perform expensive operations**: Upcasting happens synchronously during
  every read. A slow upcaster degrades aggregate loading and subscription
  processing.

---

## When to Use Upcasting vs. New Event Type

| Situation | Approach |
|-----------|----------|
| Add optional field with default | No upcaster needed, add `default=` |
| Add required field with computable default | Upcaster |
| Rename a field | `renamed_from` (an upcaster only if you are already bumping the version) |
| Change field type (e.g. string→int) | Upcaster (bump the version) |
| Change data structure (flat→nested) | Upcaster (bump the version) |
| Remove a field | Lenient mode drops it on read (an upcaster strips it only if you also bump the version) |
| Change the meaning of a field | **New event type** |
| Fundamentally different business operation | **New event type** |
| Event applies to a different aggregate | **New event type** |

---

## What can't upcasting do?

- **No event type renaming**: If you rename an event class (e.g. `OrderCreated`
  → `OrderPlaced`), the type strings differ and upcasting can't convert events
  from the old type string to the new one. Use the "new event type" strategy
  instead.

- **No multi-event transformations**: An upcaster transforms one event at a
  time. Protean does not support splitting one event into two or merging two
  events into one. Use compensating events or the copy-transform migration
  pattern.

- **No eager/batch migration**: Upcasting is lazy (on-read) and never rewrites
  the store. To rewrite the event store in a new format, use an operator
  migration, in-place transformation or copy-transform, documented under
  [Migration Strategies](../../patterns/event-versioning-and-evolution.md#migration-strategies).

---

!!! seealso "See also"
    **Patterns:** [Event Versioning and Evolution](../../patterns/event-versioning-and-evolution.md): Strategies for evolving event schemas over time.

    **Related guides:**

    - [Evolving Events Over Time](../evolving-events.md): The broader
      event-evolution workflow, which covers upcasting together with
      `renamed_from` field renames, event `deprecated`/`superseded_by`, and
      opt-in lenient deserialization.
    - [Temporal Queries](../change-state/temporal-queries.md): Load aggregate state at a specific version or point in time.
