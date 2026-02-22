# Temporal Queries

!!! abstract "Applies to: Event Sourcing"


Event sourcing preserves the complete history of every aggregate as a sequence
of domain events. Temporal queries let you reconstitute an aggregate at any
historical point -- answering "what was the state of this order yesterday?" or
"what did the account look like at version 5?" without any extra infrastructure.

## By version

Pass `at_version` to `get()` to reconstitute an aggregate at a specific event
version. Versions are 0-indexed: version 0 is the state after the first event,
version 1 after the second, and so on.

```python
repo = domain.repository_for(Order)

# State after the 6th event (version 5)
order_v5 = repo.get("order-123", at_version=5)

assert order_v5._version == 5
```

This is useful for comparing state before and after a particular event, or for
debugging unexpected state transitions.

## By timestamp

Pass `as_of` to `get()` to reconstitute an aggregate as it existed at a
particular moment in time. Only events written on or before the given
`datetime` are replayed.

```python
from datetime import datetime, UTC

repo = domain.repository_for(Order)

# What was this order's state at noon on February 20?
cutoff = datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC)
order_then = repo.get("order-123", as_of=cutoff)
```

!!! note
    The `as_of` parameter uses the event's **write timestamp** -- the moment
    the event was persisted to the event store, not any business-level
    timestamp embedded in the event payload.

## Read-only aggregates

Temporal aggregates are **read-only**. Calling `raise_()` on them raises
`IncorrectUsageError`:

```python
order_v5 = repo.get("order-123", at_version=5)
order_v5.raise_(SomeEvent(...))  # Raises IncorrectUsageError
```

You can check whether an aggregate was loaded temporally via the
`_is_temporal` attribute:

```python
assert order_v5._is_temporal is True
```

This safety guard prevents accidental writes to historical state. If you need
to modify an aggregate, load it at its current version with a plain `get()`.

## Mutual exclusivity

`at_version` and `as_of` cannot be used together. Passing both raises
`IncorrectUsageError`:

```python
# This raises IncorrectUsageError
repo.get("order-123", at_version=5, as_of=cutoff)
```

## Interaction with snapshots

Protean's snapshot mechanism optimizes aggregate loading by caching state at
periodic intervals (see
[Event Sourcing Internals](../../concepts/internals/event-sourcing.md#snapshots)).

Temporal queries handle snapshots correctly:

- **`at_version`** leverages existing snapshots when the snapshot version is
  at or before the requested version. If the snapshot is newer than the
  requested version, it is skipped and events are replayed from the beginning.
- **`as_of`** always skips snapshots and replays from the first event, because
  a snapshot's creation time does not correspond to any particular aggregate
  state timestamp.

## Identity map bypass

Temporal queries always bypass the Unit of Work's identity map. Even if the
aggregate was already loaded in the current transaction, a temporal query
replays events from the event store to ensure the historical state is accurate:

```python
with UnitOfWork():
    current = repo.get("order-123")       # Loaded into identity map
    current.place_item(...)               # Mutated in memory

    historical = repo.get("order-123", at_version=0)  # Fresh from events
    assert historical._version == 0      # Not affected by in-memory mutation
```

## Error handling

| Scenario | Exception |
|----------|-----------|
| Aggregate does not exist | `ObjectNotFoundError` |
| `at_version` higher than latest version | `ObjectNotFoundError` (message includes the latest available version) |
| `as_of` before the first event | `ObjectNotFoundError` |
| Both `at_version` and `as_of` provided | `IncorrectUsageError` |
| `raise_()` on a temporal aggregate | `IncorrectUsageError` |
