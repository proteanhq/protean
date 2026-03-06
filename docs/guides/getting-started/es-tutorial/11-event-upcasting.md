# Chapter 11: When Requirements Change — Event Upcasting

Six months after launch, new anti-money-laundering regulations require
that every deposit record its **source type** — whether the funds came
from cash, wire transfer, ACH, or check. The `DepositMade` event needs a
new `source_type` field.

But the event store contains hundreds of thousands of historical
`DepositMade` events that lack this field. Rewriting history is not an
option — that defeats the purpose of Event Sourcing.

The answer is **upcasting**: transparently transforming old event
payloads into the current schema during deserialization. The old events
are never rewritten — they are upgraded on the fly whenever they are
read.

## Versioning the Event

First, bump the event to v2 and add the new field:

```python
--8<-- "guides/getting-started/es-tutorial/ch11.py:deposit_made_v2"
```

The `__version__ = 2` attribute tells Protean this is the current
schema. Historical events stored as `"v1"` will need transformation.

## Writing the Upcaster

```python
--8<-- "guides/getting-started/es-tutorial/ch11.py:upcaster"
```

The upcaster is a simple class:

- **`event_type=DepositMade`** — which event this upcaster handles.
- **`from_version=1`, `to_version=2`** — the version transition.
- **`upcast(self, data: dict) -> dict`** — transforms the old payload.
  Here, we add `source_type = "unknown"` since we cannot determine the
  source for historical deposits.

## How It Works

When the event store reads a message with type
`Fidelis.DepositMade.v1`:

1. Protean looks up the upcaster chain for `DepositMade`
2. Finds `v1 → v2` upcaster
3. Calls `upcast()` to transform the data
4. Instantiates the current `DepositMade` (v2) class with the
   transformed data

The historical event in the store is untouched. The transformation
happens at read time, lazily.

## Chaining Upcasters

Later, regulations add a `currency` field. Bump to v3:

```python
@domain.event(part_of=Account)
class DepositMade:
    __version__ = 3

    account_id: Identifier(required=True)
    amount: Float(required=True)
    source_type: String(default="unknown")
    currency: String(default="USD")  # NEW in v3
    reference: String()


@domain.upcaster(event_type=DepositMade, from_version=2, to_version=3)
class UpcastDepositV2ToV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data
```

Protean automatically chains: **v1 → v2 → v3**. A historical v1 event
passes through both upcasters before reaching the handler.

## Startup Validation

During `domain.init()`, Protean validates upcaster chains:

- **No duplicate registrations** — two upcasters for the same
  `from_version → to_version` transition
- **No cycles** — v1 → v2 → v1 would loop forever
- **Convergent chains** — all paths must reach the same terminal version
  (the current `__version__`)
- **No gaps** — v1 → v3 without a v2 intermediate is invalid if v2
  exists

If any validation fails, `domain.init()` raises an error immediately.

## Performance

- **Current events (v2 reading v2)**: Zero overhead. Direct type lookup,
  no upcasting.
- **Old events (v1 reading v2)**: O(N) where N is the number of version
  hops. For v1 → v3 with two upcasters, N = 2. This is negligible.
- **Never rewrite events**: The event store is append-only. Upcasting
  respects this fundamental invariant.

## What We Built

- **Event versioning** with `__version__ = 2` on the event class.
- An **upcaster** with `@domain.upcaster()` that transforms old payloads.
- **Upcaster chains** that automatically compose (v1 → v2 → v3).
- **Startup validation** that catches broken chains at init time.
- **Lazy migration** — events are never rewritten, only transformed at
  read time.

This is the event-sourcing answer to database migrations. No downtime,
no data rewriting, no migration scripts.

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch11.py:full"
```

## Next

[Chapter 12: Snapshots for High-Volume Accounts →](12-snapshots.md)
