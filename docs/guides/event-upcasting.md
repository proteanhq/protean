# Event Upcasting

## The Problem

In an event-sourced system, the event store is the source of truth. Events are
immutable facts stored forever. But the domain model evolves: fields get renamed,
new required fields are added, semantics change. When the system replays old
events to reconstruct an aggregate, those events must match the current event
class definition -- or deserialization fails.

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
from protean.core.upcaster import BaseUpcaster

@domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v2")
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data
```

### Decorator Options

| Option | Type | Description |
|--------|------|-------------|
| `event_type` | Event class | The event this upcaster targets (always the *current* class). |
| `from_version` | `str` | The source version this upcaster transforms from (e.g. `"v1"`). |
| `to_version` | `str` | The target version this upcaster transforms to (e.g. `"v2"`). |

### The `upcast` Method

- Receives the raw event payload as a Python `dict`.
- Must return the transformed `dict`.
- Operates on raw data **before** the typed event object is constructed, so
  field types are their serialized form (strings, numbers, lists, dicts).
- Should be **fast and side-effect-free** -- no database queries, no I/O.
  Upcasting runs on every deserialization.
- May mutate the input dict in place or return a new dict.

---

## Real-World Scenarios

### Scenario 1: Adding a New Required Field

Your `OrderPlaced` event originally had no `currency` field. Now you need to
track currency, and it's required for correct calculations.

**Before (v1):**
```python
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    order_id = Identifier(required=True)
    amount = Float(required=True)
```

**After (v2):**
```python
@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    __version__ = "v2"
    order_id = Identifier(required=True)
    amount = Float(required=True)
    currency = String(required=True)
```

**Upcaster:**
```python
@domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v2")
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        # All orders before v2 were in USD
        data["currency"] = "USD"
        return data
```

### Scenario 2: Renaming a Field

The field `customer_name` was split into `first_name` and `last_name`.

**Upcaster:**
```python
@domain.upcaster(event_type=CustomerRegistered, from_version="v1", to_version="v2")
class UpcastCustomerRegisteredV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        full_name = data.pop("customer_name", "")
        parts = full_name.split(" ", 1)
        data["first_name"] = parts[0]
        data["last_name"] = parts[1] if len(parts) > 1 else ""
        return data
```

### Scenario 3: Changing Data Structure

An address was stored as flat fields and is now a nested dict (to match a
new `Address` value object).

**Upcaster:**
```python
@domain.upcaster(event_type=CustomerRegistered, from_version="v2", to_version="v3")
class UpcastCustomerRegisteredV2ToV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["address"] = {
            "street": data.pop("street", ""),
            "city": data.pop("city", ""),
            "state": data.pop("state", ""),
            "zip_code": data.pop("zip_code", ""),
        }
        return data
```

### Scenario 4: Multi-Step Chain

When events evolve through multiple versions, each step gets its own upcaster.
The framework chains them automatically.

```python
# v1: original schema
# v2: added currency
# v3: renamed amount → total_amount

@domain.event(part_of=Order)
class OrderPlaced(BaseEvent):
    __version__ = "v3"
    order_id = Identifier(required=True)
    total_amount = Float(required=True)
    currency = String(required=True)


@domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v2")
class UpcastV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data


@domain.upcaster(event_type=OrderPlaced, from_version="v2", to_version="v3")
class UpcastV2ToV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["total_amount"] = data.pop("amount")
        return data
```

A stored v1 event automatically passes through both upcasters: v1→v2→v3.
A stored v2 event passes through only v2→v3.
A stored v3 event skips upcasting entirely (zero overhead).

### Scenario 5: Removing an Obsolete Field

The `legacy_code` field was never used by any handler but was stored in v1
events. In v2, the event schema no longer includes it. The upcaster strips
it out so the current constructor doesn't receive unknown fields:

```python
@domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v2")
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data.pop("legacy_code", None)
        return data
```

### Scenario 6: Computing a Derived Field

The v2 schema adds a `line_item_count` field that can be computed from existing
data:

```python
@domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v2")
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["line_item_count"] = len(data.get("items", []))
        return data
```

---

## Upcasters and Event-Sourced Aggregates

Upcasting is especially important for event-sourced aggregates because every
aggregate reconstruction replays every event from the stream (or from the last
snapshot). Without upcasting, `@apply` handlers must accommodate every
historical schema variant.

**With upcasting**, `@apply` handlers are clean and only handle the current
schema:

```python
@domain.aggregate(is_event_sourced=True)
class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    total_amount = Float()
    currency = String()

    @apply
    def on_placed(self, event: OrderPlaced) -> None:
        # Always receives current v3 schema
        self.order_id = event.order_id
        self.total_amount = event.total_amount
        self.currency = event.currency
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

## Upcasters and Event Handlers / Projectors

Upcasting also applies to asynchronous event processing. When an event handler
or projector reads events from a subscription, old events are upcast before
reaching the `@handle` method:

```python
@domain.event_handler(part_of=Analytics)
class AnalyticsHandler(BaseEventHandler):
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # Always receives current schema, even for historical replays
        record_revenue(event.total_amount, event.currency)
```

This means you can rebuild projections from scratch (replaying all events) and
old events are automatically transformed to the current schema.

---

## Validation at Startup

During `domain.init()`, the framework validates all registered upcaster chains.
The following errors are caught at startup (not at runtime):

### Duplicate upcasters

```python
# ERROR: Two upcasters for the same (event_type, from_version)
@domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v2")
class UpcasterA(BaseUpcaster): ...

@domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v2")
class UpcasterB(BaseUpcaster): ...
# → ConfigurationError: Duplicate upcaster for OrderPlaced from version v1
```

### Version cycles

```python
# ERROR: v1→v2 and v2→v1 creates a cycle
@domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v2")
class Forward(BaseUpcaster): ...

@domain.upcaster(event_type=OrderPlaced, from_version="v2", to_version="v1")
class Backward(BaseUpcaster): ...
# → ConfigurationError: Upcaster chain does not converge
```

### Non-convergent chains

```python
# ERROR: v1→v2 and v1a→v3 — two terminal versions
@domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v2")
class BranchA(BaseUpcaster): ...

@domain.upcaster(event_type=OrderPlaced, from_version="v1a", to_version="v3")
class BranchB(BaseUpcaster): ...
# → ConfigurationError: does not converge to a single current version
```

### Missing event class for terminal version

```python
# ERROR: Chain ends at v99, but OrderPlaced.__version__ is "v2"
@domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v99")
class WrongTarget(BaseUpcaster): ...
# → ConfigurationError: no event is registered with type string ...v99
```

---

## Guidelines

### Do

- **One upcaster per version step.** Keep transformations small and focused.
  v1→v2 does one thing, v2→v3 does another.
- **Keep upcasters pure.** No I/O, no database queries, no external API calls.
  Upcasting runs on every deserialization and must be fast.
- **Test upcasters independently.** They are simple dict→dict functions and
  easy to unit test.
- **Place upcasters near the event they transform.** In the same module or a
  dedicated `upcasters.py` module within the same domain concept.
- **Bump `__version__`** on the event class whenever you register a new upcaster
  targeting it.

### Don't

- **Don't skip versions in the chain.** If the current version is v3, you need
  both v1→v2 and v2→v3 upcasters. A direct v1→v3 upcaster is valid only if
  there was no v2 in production.
- **Don't modify the stored event.** Upcasting transforms data in memory during
  deserialization. The event store is never modified.
- **Don't use upcasting for semantic changes.** If the *meaning* of an event
  changes (not just its structure), create a new event type instead.
- **Don't perform expensive operations.** Upcasting happens synchronously during
  every read. A slow upcaster degrades aggregate loading and subscription
  processing.

---

## When to Use Upcasting vs. New Event Type

| Situation | Approach |
|-----------|----------|
| Add optional field with default | No upcaster needed -- just add `default=` |
| Add required field with computable default | Upcaster |
| Rename a field | Upcaster |
| Change field type (e.g. string→int) | Upcaster |
| Change data structure (flat→nested) | Upcaster |
| Remove an unused field | Upcaster (strip from old data) |
| Change the meaning of a field | **New event type** |
| Fundamentally different business operation | **New event type** |
| Event applies to a different aggregate | **New event type** |

---

## Limitations

- **No event type renaming.** If you rename an event class (e.g. `OrderCreated`
  → `OrderPlaced`), the type strings differ and upcasting can't bridge them.
  Use the "new event type" strategy instead.

- **No multi-event transformations.** An upcaster transforms one event at a
  time. Splitting one event into two or merging two events into one is not
  supported. Use compensating events or the copy-transform migration pattern.

- **No eager/batch migration.** Upcasting is lazy (on-read). If you need to
  rewrite the event store in a new format, use the copy-transform pattern
  documented in the [Event Versioning](../patterns/event-versioning-and-evolution.md)
  pattern.
