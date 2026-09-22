---
name: upcaster
description: "Define a Protean event upcaster — a class that transforms old event payloads to match the current schema version, enabling event schema evolution without breaking stored events. Upcasters extend BaseUpcaster, implement an upcast(data) method, and are registered with @domain.upcaster(event_type=EventClass, from_version='v1', to_version='v2'). The framework automatically chains individual upcasters and applies them lazily during deserialization. Use when the user asks to 'create an upcaster', 'handle event schema migration', 'evolve an event schema', 'add a field to an existing event', 'rename a field in an event', 'migrate old events', 'transform stored events', 'handle event versioning', or when they need to change an event's schema while keeping old stored events compatible."
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# Upcaster

## Basic structure

An upcaster transforms old event payloads to the current schema during deserialization. Define one by extending `BaseUpcaster` and implementing `upcast()`:

```python
from protean import Domain
from protean.core.upcaster import BaseUpcaster
from protean.fields import Float, Identifier, String

domain = Domain()

@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 2
    order_id = Identifier(required=True)
    amount = Float(required=True)
    currency = String(required=True)

@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data
```

## Key rules

1. **Extend `BaseUpcaster`** — Import from `protean.core.upcaster`
2. **Register with `@domain.upcaster(event_type=..., from_version=..., to_version=...)`** — All three options are required
3. **Implement `upcast(self, data: dict) -> dict`** — Receives the raw event payload dict, returns the transformed dict
4. **`event_type` is always the CURRENT event class** — Not the old version. The upcaster knows which event it targets by its current definition
5. **Bump `__version__` on the event class** — Set `__version__ = 2` on the event when you add an upcaster targeting v2. Default version is `1`
6. **One upcaster per version step** — Write v1→v2 and v2→v3 separately. Never skip versions that existed in production
7. **Keep upcasters pure** — No I/O, no database queries, no external API calls. Upcasting runs on every deserialization and must be fast
8. **Chains build automatically** — Register individual steps; the framework chains them into v1→v2→v3 during `domain.init()`
9. **Validated at startup** — `domain.init()` detects duplicates, cycles, non-convergent chains, and missing event classes. All errors are caught at startup, never at runtime
10. **Works everywhere transparently** — Event-sourced aggregate reconstruction (`@apply`), event handlers (`@handle`), and projectors all receive upcast events
11. **Lazy, zero-overhead for current events** — Current-version events take a fast path (direct type-string lookup). The upcaster chain is only consulted for old-version type strings

## Common transformations

### Adding a new required field

```python
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"  # All v1 orders were in USD
        return data
```

### Renaming a field

```python
@domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=3)
class UpcastV2ToV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["total_amount"] = data.pop("amount")
        return data
```

### Removing an obsolete field

```python
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data.pop("legacy_code", None)
        return data
```

### Computing a derived field

```python
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["line_item_count"] = len(data.get("items", []))
        return data
```

### Restructuring data (flat → nested)

```python
@domain.upcaster(event_type=CustomerRegistered, from_version=1, to_version=2)
class UpcastV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["address"] = {
            "street": data.pop("street", ""),
            "city": data.pop("city", ""),
            "zip_code": data.pop("zip_code", ""),
        }
        return data
```

## Multi-step chains

When an event evolves through multiple versions, register one upcaster per step. The framework chains them automatically:

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 3
    order_id = Identifier(required=True)
    total_amount = Float(required=True)
    currency = String(required=True)

# v1 → v2: add currency
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data

# v2 → v3: rename amount → total_amount
@domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=3)
class UpcastV2ToV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["total_amount"] = data.pop("amount")
        return data
```

A stored v1 event passes through both: v1→v2→v3. A stored v2 event passes through only v2→v3. A v3 event skips upcasting entirely.

## With event-sourced aggregates

Upcasting is especially valuable for ES aggregates because every reconstruction replays all events. With upcasters, `@apply` handlers only handle the current schema:

```python
@domain.aggregate(is_event_sourced=True)
class Order:
    order_id = Identifier(identifier=True)
    total_amount = Float()
    currency = String()

    @apply
    def on_placed(self, event: OrderPlaced):
        # Always receives current v3 schema — upcasters handle old versions
        self.total_amount = event.total_amount
        self.currency = event.currency
```

## With event handlers and projectors

Upcasting also applies to asynchronous event processing. Old events are upcast before reaching `@handle`:

```python
@domain.event_handler(part_of=Analytics)
class AnalyticsHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        # Always receives current schema, even for historical replays
        record_revenue(event.total_amount, event.currency)
```

## Common mistakes

### Skipping versions in chains

```python
# WRONG — if v2 existed in production, you need v1→v2 AND v2→v3
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=3)
class SkipV2(BaseUpcaster): ...

# CORRECT — one step per version
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class V1ToV2(BaseUpcaster): ...

@domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=3)
class V2ToV3(BaseUpcaster): ...
```

### Performing I/O in upcast()

```python
# WRONG — upcasting runs on every deserialization
class SlowUpcaster(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        user = db.query(User, data["user_id"])  # NO! No I/O
        data["user_name"] = user.name
        return data

# CORRECT — pure dict transformation only
class FastUpcaster(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["user_name"] = data.get("user_name", "Unknown")
        return data
```

### Pointing event_type at old class

```python
# WRONG — event_type must be the CURRENT event class
@domain.upcaster(event_type=OrderPlacedV1, from_version=1, to_version=2)

# CORRECT — always point to the current class
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
```

### Forgetting to bump __version__

```python
# WRONG — event still at default v1, but upcaster targets v2
@domain.event(part_of="Order")
class OrderPlaced:
    # __version__ not set — defaults to `1`
    ...

# CORRECT — set __version__ to match the upcaster chain's terminal version
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 2
    ...
```

See [Anti-patterns](references/anti-patterns.md) for more.

## Detailed references

### Core Concepts
- [Upcaster Chain](references/upcaster-chain.md) — How chain building, validation, and runtime application work
- [Anti-patterns](references/anti-patterns.md) — Common mistakes and how to avoid them
- [When to Upcast](references/when-to-upcast.md) — Decision guide: upcasting vs. new event type vs. no action

### Complete Examples
- [Basic Upcasters](assets/upcaster_basic.py) — Add field, rename field, remove field, compute derived field
- [Multi-Step Chain](assets/upcaster_multi_step_chain.py) — Event evolving through 4 versions with automatic chaining
- [With ES Aggregate](assets/upcaster_with_es_aggregate.py) — Clean @apply handlers with transparent upcasting
- [With Event Handler](assets/upcaster_with_event_handler.py) — Event handler and projector receiving upcast events

### Related Skills
- `event` — Event definition, `__version__`, naming conventions
- `event-sourced-aggregate` — `@apply` decorator, `from_events()`, ES repository
- `event-handler` — `@handle` decorator, event handler structure
- `projector` — `@handle`/`@on` decorator, projector structure

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
