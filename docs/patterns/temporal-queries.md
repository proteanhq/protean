# Temporal Queries for Audit, Debugging, and Compliance

## The Problem

Event-sourced systems store the complete history of every aggregate as an
ordered sequence of events. This history is one of the key selling points of
event sourcing. In theory, you can answer questions like "what was this
account's balance when the fraudulent transaction occurred?" or "what did this
customer's profile look like when we approved the loan?"

In practice, teams rarely operationalize this capability. When an incident
investigation, compliance audit, or customer support case requires
reconstructing past state, engineers fall back to ad-hoc approaches:

```python
# fragment
# Ad-hoc approach: manually read and replay events
from protean.utils.globals import current_domain


def investigate_account_state(account_id: str, target_version: int):
    """Quick-and-dirty reconstruction for an incident investigation."""
    store = current_domain.event_store.store
    raw_events = store._read(f"account-{account_id}")

    state = {}
    for i, raw_event in enumerate(raw_events):
        if i > target_version:
            break
        state.update(raw_event["data"])

    return state
```

This approach has several problems:

- **Bypasses the domain model**: The reconstruction logic does not use the
  aggregate's `@apply` handlers, so it misses computed fields, derived
  state, and business rules.

- **Duplicates reconstruction logic**: Every investigation requires writing
  new replay code that is subtly different and never tested.

- **Produces mutable objects**: Nothing prevents accidentally persisting
  changes to a historical snapshot, corrupting the event stream.

- **Cannot be exposed safely**: Customer support and compliance teams need
  self-service access, but ad-hoc scripts require engineering time.

The underlying problem: **the event store contains complete history, but
the application has no API for querying it.**

---

## The Pattern

Use the event-sourced repository's `at_version` and `as_of` parameters as
**ordinary query operations**. These are not debugging utilities; they
are API parameters that reconstruct aggregate state at a
specific point in history.

Two temporal dimensions are supported:

- **`at_version=N`** reconstructs the aggregate after the Nth event
  (0-indexed). Version 0 is the state after the first event. This is
  useful when you know the exact event position, for example, "show me the
  account state before the suspicious transaction at version 47."

- **`as_of=datetime`** reconstructs the aggregate as of a point in time.
  Only events written on or before the timestamp are applied. This is
  useful for calendar-based queries, for example, "show me the account state as
  of the end-of-quarter reporting date."

The returned aggregate is **read-only**. Protean marks it with
`_is_temporal=True`, and any attempt to call `raise_()` on it raises
`IncorrectUsageError`. This makes temporal aggregates safe to expose
through API endpoints, customer support tools, and compliance dashboards
without risk of accidental mutation.

Key behaviors:

1. **Identity map bypass**: Temporal queries always bypass the Unit of
   Work's identity map. Loading the same aggregate at version 5 and
   version 10 in the same transaction returns two distinct objects.

2. **Snapshot awareness**: `at_version` uses existing snapshots when
   the snapshot version is at or below the requested version. `as_of`
   skips snapshots entirely and replays from position 0.

3. **Mutual exclusivity**: You cannot specify both `at_version` and
   `as_of` in the same call. They represent different dimensions of
   history and combining them would be ambiguous.

Design temporal query endpoints for three categories of consumers:

- **Compliance audits**: "Show me this customer's KYC status as of the
  date we approved the transaction."
- **Customer support**: "What was this order's state when the customer
  called to complain?"
- **Incident investigation**: "Reconstruct this account at version 47 to
  determine what changed between versions 46 and 48."

---

## Applying the Pattern

### The event-sourced aggregate

A financial compliance domain with an `Account` aggregate that tracks
identity verification and transaction limits:

```python
--8<-- "patterns/temporal-queries/001.py:aggregate"
```

### Basic temporal query with `at_version`

Reconstruct the account after a specific number of events. Version 0 is
the state after the first event. Version 1 adds the second event, etc.

The examples on this page read an account with five events. This function
writes them, in three saves:

```python
--8<-- "patterns/temporal-queries/001.py:history"
```

Read the account back at its current version and at version 1:

```python
--8<-- "patterns/temporal-queries/001.py:at_version"
```

### Point-in-time query with `as_of`

Reconstruct the account as it existed at a specific timestamp. Only events
written on or before that moment are applied.

```python
--8<-- "patterns/temporal-queries/001.py:as_of"
```

!!! note "`as_of` and timezone handling"
    Protean normalizes timezone-naive and timezone-aware timestamps before
    comparison. Pass your `as_of` timestamp in UTC for consistent results.

### Application service exposing temporal queries

Wrap temporal queries in an application service that provides a clean API
for compliance and support teams:

```python
--8<-- "patterns/temporal-queries/001.py:audit_service"
```

### API endpoint for audit trail

Expose temporal queries through a REST API so compliance and support teams
can self-serve:

```python
--8<-- "patterns/temporal-queries/001.py:api"
```

### Read-only safety

Protean sets `_is_temporal=True` on every aggregate returned by a temporal
query. The `raise_()` method checks this flag before accepting new events:

```python
--8<-- "patterns/temporal-queries/001.py:read_only"
```

You can safely pass temporal aggregates to serializers, API layers, and
reporting tools without defensive wrappers.

!!! warning "Read-only at the domain level, not the Python level"
    The `_is_temporal` flag prevents `raise_()` from accepting new events.
    It does **not** make the Python object immutable. You can still set
    attributes. However, those changes will never be persisted because no
    events are raised.

### Identity map bypass

Within a Unit of Work, once you pass an aggregate to `repo.add()`, later
`get()` calls return that same instance from the identity map. Temporal
queries **bypass** this cache:

```python
--8<-- "patterns/temporal-queries/001.py:identity_map"
```

---

## Anti-Patterns

### Building custom replay logic

```python
# fragment
# Anti-pattern: hand-rolled event replay
def get_account_at_version(account_id: str, version: int) -> dict:
    store = current_domain.event_store.store
    events = store._read(f"account-{account_id}")

    state = {}
    for i, event in enumerate(events):
        if i > version:
            break
        state.update(event["data"])

    return state
```

This bypasses the aggregate's `@apply` handlers, ignores snapshots, skips
validation, and returns a mutable dictionary instead of a proper domain
object. Use the repository's `at_version` parameter instead:

```python
# fragment
account = repo.get(account_id, at_version=version)
```

### Querying the event store directly for point-in-time state

```python
# fragment
# Anti-pattern: reading raw events and filtering by timestamp
def get_account_as_of(account_id: str, cutoff: datetime) -> dict:
    store = current_domain.event_store.store
    events = store._read(f"account-{account_id}")

    state = {}
    for event in events:
        if datetime.fromisoformat(event.get("time", "")) > cutoff:
            break
        state.update(event["data"])

    return state
```

This duplicates timestamp parsing, timezone normalization, and event
filtering that the event store handles internally. It also fails across
adapters (PostgreSQL returns `datetime` objects; memory returns ISO
strings). Use the repository instead:

```python
# fragment
account = repo.get(account_id, as_of=cutoff)
```

### Using temporal data for writes

```python
# fragment
# Anti-pattern: loading a historical version and trying to modify it
def rollback_account(account_id: str, version: int) -> None:
    repo = current_domain.repository_for(Account)
    old_account = repo.get(account_id, at_version=version)
    repo.add(old_account)  # Saves nothing: the old state has no new events
```

Temporal aggregates are read-only. If you need to "undo" a change, model
the reversal as an explicit domain operation on the **current** aggregate:

```python
--8<-- "patterns/temporal-queries/001.py:restore"
```

---

## Summary

| Capability | API | Description |
|-----------|-----|-------------|
| Version-based reconstruction | `repo.get(id, at_version=N)` | State after the Nth event (0-indexed) |
| Time-based reconstruction | `repo.get(id, as_of=datetime)` | State as of a specific timestamp |
| Read-only guarantee | `_is_temporal=True` | `raise_()` raises `IncorrectUsageError` |
| Identity map bypass | Automatic | Temporal queries never return cached objects |
| Snapshot awareness | `at_version` only | Uses snapshots when version <= requested |
| Mutual exclusivity | Enforced | Cannot combine `at_version` and `as_of` |

| Use case | Recommended parameter | Example |
|----------|----------------------|---------|
| Investigate a specific event | `at_version` | "Show state before event 47" |
| Regulatory reporting | `as_of` | "Account state at quarter end" |
| Customer support | `as_of` | "State when customer called at 3:14 PM" |
| Version comparison | Two `at_version` calls | "What changed between versions 5 and 8?" |
| Incident forensics | `at_version` or `as_of` | "Reconstruct the timeline of changes" |

| Principle | Practice |
|-----------|----------|
| Temporal queries are ordinary operations | Use repository parameters, not custom replay |
| Historical aggregates are read-only | Never persist or mutate temporal objects |
| Model reversals as new events | Load old state for reference, apply changes to current |
| Expose temporal queries to consumers | Build API endpoints for audit, support, compliance |
| Use the right temporal dimension | `at_version` for event positions, `as_of` for calendar time |

---

!!! tip "Related reading"
    **Concepts:**

    - [Event Sourcing](../concepts/architecture/event-sourcing.md): Deriving state from event replay.

    **Guides:**

    - [Temporal Queries](../guides/change-state/temporal-queries.md): How to use at_version and as_of.
    - [`protean events`](../reference/cli/data/events.md): Inspect event streams and aggregate history.
