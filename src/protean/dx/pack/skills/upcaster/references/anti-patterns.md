# Upcaster Anti-Patterns

Common mistakes when working with event upcasters, and how to fix them.

## 1. Skipping versions in chains

**Problem**: Creating a direct v1→v3 upcaster when v2 existed in production.

```python
# WRONG — if v2 events exist in the event store, they won't be upcast
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=3)
class SkipV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        data["total_amount"] = data.pop("amount")
        return data
```

**Why it's wrong**: If any v2 events were stored in the event store, there's no chain to transform them to v3. Deserialization will fail.

**Fix**: Register one upcaster per version step.

```python
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class V1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data

@domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=3)
class V2ToV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["total_amount"] = data.pop("amount")
        return data
```

**Exception**: A direct v1→v3 is valid only if v2 was never deployed to production (i.e., no v2 events exist in any event store).

## 2. Performing I/O in upcast()

**Problem**: Making database queries, API calls, or file reads inside the upcaster.

```python
# WRONG — runs on every deserialization, can be called thousands of times
class SlowUpcaster(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        user = database.get_user(data["user_id"])
        data["user_name"] = user.name
        return data
```

**Why it's wrong**: Upcasting runs synchronously during every event deserialization. When loading an event-sourced aggregate with 1000 events, a slow upcaster is called for every old-version event. This degrades aggregate loading and subscription processing.

**Fix**: Use only data available in the event payload. If the old event doesn't have the needed data, provide a reasonable default.

```python
class PureUpcaster(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["user_name"] = data.get("user_name", "Unknown")
        return data
```

## 3. Modifying stored events

**Problem**: Attempting to update events in the event store to match the new schema.

**Why it's wrong**: Events are immutable historical records. Modifying them breaks the fundamental guarantee of event sourcing. Other systems may have already processed the original event.

**Fix**: Upcasting transforms data in memory during deserialization. The event store is never modified. Old events stay exactly as they were stored.

## 4. Using upcasting for semantic changes

**Problem**: Using an upcaster when the event's business meaning has changed.

```python
# WRONG — "total" changed from tax-inclusive to tax-exclusive
# Old events: total = 110.00 (includes $10 tax)
# New events: total = 100.00 (excludes tax)
class ChangeSemantics(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        # Can't reliably extract tax from old total
        data["total"] = data["total"]  # ???
        return data
```

**Why it's wrong**: An upcaster can transform structure (rename, add, remove fields) but can't change what a field *means*. If the business semantics changed, consumers using the upcast data will compute wrong results.

**Fix**: Create a new event type when the business meaning changes.

```python
# Old event type (kept for historical events)
@domain.event(part_of="Order")
class OrderPlaced(BaseEvent):
    total = Float()  # Includes tax

# New event type (used going forward)
@domain.event(part_of="Order")
class OrderPlacedV2(BaseEvent):
    subtotal = Float()  # Excludes tax
    tax = Float()
    total = Float()     # Includes tax
```

## 5. Pointing event_type at old version

**Problem**: Setting `event_type` to an old or versioned event class instead of the current one.

```python
# WRONG — event_type must be the current class
@domain.upcaster(event_type=OrderPlacedV1, from_version=1, to_version=2)
```

**Why it's wrong**: The `event_type` option tells the framework which current event class this upcaster targets. It's used to compute the event_base_type for chain building. Pointing to a non-current class breaks chain resolution.

**Fix**: Always use the current event class.

```python
# CORRECT
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
```

## 6. Forgetting to bump __version__

**Problem**: Adding an upcaster but leaving the event class at its default version.

```python
@domain.event(part_of="Order")
class OrderPlaced:
    # __version__ defaults to `1`
    order_id = Identifier(required=True)
    amount = Float(required=True)
    currency = String(required=True)  # New field

@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcastV1ToV2(BaseUpcaster): ...
```

**Why it's wrong**: The event is still registered as v1, but the upcaster chain's terminal version is v2. During `domain.init()`, chain validation fails because no event is registered with the type string ending in `.v2`.

**Fix**: Set `__version__` on the event class to match the terminal version.

```python
@domain.event(part_of="Order")
class OrderPlaced:
    __version__ = 2  # Must match the chain's terminal version
    ...
```

## 7. Non-deterministic transformations

**Problem**: Using runtime-dependent values in the upcaster.

```python
# WRONG — different results on different runs
from datetime import datetime

class NonDeterministic(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["migrated_at"] = datetime.now().isoformat()
        return data
```

**Why it's wrong**: Upcasting runs on every read. If the result differs each time, aggregate state depends on *when* it was loaded, not on the stored events. This breaks the deterministic replay guarantee of event sourcing.

**Fix**: Use only deterministic values derived from the event data itself.

```python
class Deterministic(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["migrated_at"] = "2024-01-01T00:00:00+00:00"  # Fixed value
        return data
```
