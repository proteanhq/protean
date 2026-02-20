# Event Sourcing Internals

This page documents the internal mechanics of event-sourced aggregates in
Protean — how `raise_()` triggers `@apply` handlers, how aggregates are
reconstructed from events, and how version tracking works.

## The Single Source of Truth

The central design principle: **`@apply` handlers are the only place where
event-sourced aggregate state is mutated.** Both the live path (processing
commands) and the replay path (loading from event store) converge on the
same `@apply` handlers, eliminating an entire class of bugs where live
behavior diverges from replay behavior.

```
Live path:    business_method() → raise_() → @apply handler → state mutated
Replay path:  from_events()    → _apply()  → @apply handler → state mutated
```

## `raise_()` for Event-Sourced Aggregates

When `raise_()` is called on an event-sourced aggregate, it performs these
steps in order:

1. **Validate** the event is associated with this aggregate
2. **Increment** `_version` (for non-fact events)
3. **Build metadata** — identity, stream name, sequence ID, headers, checksum
4. **Append** the enriched event to `_events`
5. **Invoke `@apply` handler** — wrapped in `atomic_change()` so invariants
   are checked before and after the handler runs

Step 5 is the key difference from non-ES aggregates, where `raise_()` only
collects events without calling handlers.

```python
# Inside raise_(), for ES aggregates:
if self.meta_.is_event_sourced:
    is_fact_event = event.__class__.__name__.endswith("FactEvent")
    if not is_fact_event:
        with atomic_change(self):
            self._apply_handler(event_with_metadata)
```

Fact events are excluded because they are auto-generated snapshots that
don't carry domain semantics — they don't have `@apply` handlers.

## `_apply_handler()` vs `_apply()`

These two methods serve different roles:

### `_apply_handler(event)`

Invokes the registered `@apply` handler(s) for an event **without**
touching `_version`. This is the shared core used by both paths:

- Called by `raise_()` during live operations (version already incremented
  by `raise_()` before the handler runs)
- Called by `_apply()` during replay (version incremented by `_apply()`
  after the handler runs)

Raises `NotImplementedError` if no handler is registered.

### `_apply(event)`

The replay-specific method. Calls `_apply_handler()` then increments
`_version`. Used exclusively during aggregate reconstitution from events:

```python
def _apply(self, event):
    self._apply_handler(event)
    self._version += 1
```

## Aggregate Construction

### `_create_for_reconstitution()`

Creates a blank aggregate instance for event replay, **bypassing all
Pydantic validation**. Uses `__new__` to skip `__init__` entirely:

1. Creates instance via `cls.__new__(cls)`
2. Initializes Pydantic internals (`__dict__`, `__pydantic_extra__`, etc.)
3. Sets private attributes with defaults (`_version=-1`, `_events=[]`, etc.)
4. **Suppresses invariant checks** (`_disable_invariant_checks=True`) —
   intermediate states during replay may violate invariants that will be
   satisfied once all events are applied
5. Initializes all model fields to `None`
6. Initializes ValueObject and Reference shadow fields to `None`
7. Sets up HasMany pseudo-methods (`add_*`, `remove_*`, etc.)
8. Discovers invariants from the MRO

This follows the same pattern as `BaseEntity.__deepcopy__`.

### `_create_new(**identity_kwargs)`

Used by factory methods to create a new ES aggregate with identity:

1. Calls `_create_for_reconstitution()` to get a blank aggregate
2. **Enables invariant checks** (`_disable_invariant_checks=False`)
3. Sets identity — from `identity_kwargs` if provided, otherwise
   auto-generates via `generate_identity()`

All state beyond identity is populated by the creation event's `@apply`
handler when the factory calls `raise_()`:

```python
@classmethod
def place(cls, customer_name):
    order = cls._create_new()
    order.raise_(OrderPlaced(
        order_id=str(order.id),
        customer_name=customer_name,
    ))
    return order
```

### `from_events(events)`

Reconstructs an aggregate from a list of stored events:

1. Calls `_create_for_reconstitution()` to get a blank aggregate
2. Applies each event via `_apply()` (handler + version increment)
3. Enables invariant checks after all events are applied

```python
@classmethod
def from_events(cls, events):
    aggregate = cls._create_for_reconstitution()
    for event in events:
        aggregate._apply(event)
    aggregate._disable_invariant_checks = False
    return aggregate
```

The first event's `@apply` handler must set **all** fields including
identity — there is no special treatment of the first event.

## Version Tracking

Version management is split between the live path and replay path to
avoid double-incrementing:

| Path | Who increments `_version` | When |
|------|---------------------------|------|
| Live (`raise_()`) | `raise_()` itself | Before calling `_apply_handler()` |
| Replay (`_apply()`) | `_apply()` | After calling `_apply_handler()` |

This ensures each event increments the version exactly once regardless of
which path processes it.

## Invariant Checking

During live operations, `raise_()` wraps the `@apply` call in
`atomic_change()`. This context manager:

1. Runs `_precheck()` before the handler (pre-invariants)
2. Suppresses per-field invariant checks during the handler
3. Runs `_postcheck()` after the handler (post-invariants)

During replay, invariant checks are disabled entirely
(`_disable_invariant_checks=True`) because intermediate states may
violate invariants that are only satisfied after all events are applied.
Checks are re-enabled when `from_events()` completes.

## Association Handling for ES Aggregates

Event-sourced aggregates don't have traditional database tables for child
entities. When a `HasMany` field's cache misses during a `__get__` call
on an ES aggregate, the framework returns an empty list instead of
attempting a database query:

```python
# In Association.__get__:
root = getattr(instance, "_root", None) or instance
if getattr(getattr(root, "meta_", None), "is_event_sourced", False):
    reference_obj = []
    self.set_cached_value(instance, reference_obj)
```

State for associated entities in ES aggregates is managed entirely through
events and `@apply` handlers using the `add_*` pseudo-methods.

## Event Upcasting

When the event store contains events from older schema versions, the upcasting
system transparently transforms them to the current schema before they reach
`@apply` handlers. This happens during `Message.to_domain_object()`, which is
called by `load_aggregate()` for every event in the stream.

See [Event Upcasting Internals](./event-upcasting.md) for the full
architecture, chain building algorithm, and integration details.
