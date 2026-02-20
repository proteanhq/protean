# Event Upcasting Internals

This page documents the internal architecture and implementation details of
Protean's event upcasting system. It covers the data structures, algorithms,
and integration points that make upcasting work transparently during
deserialization.

For usage-level documentation, see the [Event Upcasting guide](../guides/event-upcasting.md).

## Architecture Overview

Upcasting sits between two existing systems:

1. **The event store** — stores raw event dicts with a versioned type string
   (e.g. `"MyDomain.OrderPlaced.v1"`)
2. **`Message.to_domain_object()`** — deserializes a raw message into a typed
   domain event object

Upcasting intercepts the deserialization path when the stored type string
doesn't match any registered event class. It transforms the raw payload through
a chain of upcaster functions and resolves the correct (current) event class.

```
                ┌──────────────────────────────────────────────────┐
                │            Message.to_domain_object()            │
                │                                                  │
                │  1. Look up type_string in _events_and_commands  │
                │     ↓ found? → construct event (zero overhead)   │
                │     ↓ not found?                                 │
                │  2. Ask _upcaster_chain.resolve_event_class()    │
                │     ↓ not found? → raise DeserializationError    │
                │     ↓ found?                                     │
                │  3. Parse type_string → (base_type, from_version)│
                │  4. _upcaster_chain.upcast(base_type, version,   │
                │     data) → transformed data                     │
                │  5. Construct current event class with new data   │
                └──────────────────────────────────────────────────┘
```

**Key design property:** Current-version events take the fast path (step 1)
with zero overhead. The upcaster chain is only consulted when the type string
cache misses.

## Registration Model

### Why Upcasters Are Not Full Domain Elements

Upcasters are **infrastructure helpers** for schema migration, not business
domain concepts. They do not need:

- An entry in the `DomainObjects` enum
- Registration in `_DomainRegistry` (the general element registry)
- Aggregate cluster assignment
- Mypy plugin support
- Auto-discovery via module traversal

Instead, they use a lightweight registration path:

1. `@domain.upcaster(...)` calls `upcaster_factory()` for validation
2. The validated class is appended to `domain._upcasters` (a plain list)
3. During `domain.init()`, `_build_upcaster_chains()` processes the list

This follows the same spirit as `domain._events_and_commands` — a dedicated
purpose-built cache separate from the general registry.

### `BaseUpcaster`

Defined in `src/protean/core/upcaster.py`. Extends `Element` and
`OptionsMixin` (the same base classes used by all Protean elements) for
consistent meta-option handling.

**Meta options** (set via `@domain.upcaster(...)` kwargs):

| Option | Type | Description |
|--------|------|-------------|
| `event_type` | Event class | The **current** event class this upcaster targets |
| `from_version` | `str` | Source version (e.g. `"v1"`) |
| `to_version` | `str` | Target version (e.g. `"v2"`) |

**Validation** (in `upcaster_factory()`):

- `event_type` must be a `BaseEvent` subclass
- `from_version` and `to_version` must both be non-empty strings
- `from_version` must differ from `to_version`

**Abstract method:**

```python
@abstractmethod
def upcast(self, data: dict) -> dict:
    """Transform raw event data from from_version to to_version."""
```

The method receives the raw payload dict (as it was stored in the event store)
and must return the transformed dict. It operates on **serialized data**, not
typed event objects.

### `@domain.upcaster` Decorator

The decorator method on `Domain` supports both decorator-with-args and
direct-call registration:

```python
# Decorator syntax
@domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v2")
class MyUpcaster(BaseUpcaster):
    def upcast(self, data): ...

# Direct registration (e.g. in test fixtures)
domain.upcaster(MyUpcaster, event_type=OrderPlaced, from_version="v1", to_version="v2")
```

Both paths call `upcaster_factory()` for validation and append the result to
`domain._upcasters`.

## Chain Building

### Data Structures

`UpcasterChain` (defined in `src/protean/utils/upcasting.py`) maintains three
internal structures:

```python
class UpcasterChain:
    # Pre-build: edges collected during registration
    _edges: dict[str, list[tuple[str, str, type]]]
    # {event_base_type: [(from_version, to_version, upcaster_cls), ...]}

    # Post-build: pre-computed chains for O(1) lookup
    _chains: dict[tuple[str, str], list[Any]]
    # {(event_base_type, from_version): [upcaster_instance, ...]}

    # Post-build: old type strings → current event class
    _version_map: dict[str, type]
    # {"Domain.Event.v1": CurrentEventClass, ...}
```

### The `_build_upcaster_chains()` Method

Called during `domain.init()`, immediately after
`_set_and_record_event_and_command_type()` populates `_events_and_commands`.
This ordering is critical because chain validation needs the type string
registry to verify that terminal versions match registered event classes.

```python
# In Domain.init():
self._set_and_record_event_and_command_type()  # populates _events_and_commands
self._build_upcaster_chains()                  # uses _events_and_commands
self._setup_command_handlers()
```

The method:

1. Iterates `domain._upcasters`
2. Computes `event_base_type` from the event class:
   `"{domain.camel_case_name}.{event_class.__name__}"` — this matches the
   prefix of type strings (e.g. `"MyDomain.OrderPlaced"`)
3. Registers each edge in `UpcasterChain`
4. Calls `build_chains(events_and_commands)` to validate and pre-compute

### Chain Construction Algorithm

For each `event_base_type`, `build_chains()` performs:

**1. Build adjacency map**

```
adjacency = {from_version: (to_version, upcaster_cls)}
```

Each `from_version` maps to exactly one `(to_version, upcaster_cls)`.
Duplicates (two upcasters with the same `from_version`) raise
`ConfigurationError`.

**2. Find terminal version**

The terminal version is any version that appears as a `to_version` but never
as a `from_version`. This must be exactly one version — if zero or multiple
terminal versions exist, the chain is invalid.

```python
terminal_versions = all_to_versions - all_from_versions
assert len(terminal_versions) == 1  # or ConfigurationError
```

**3. Verify terminal matches registered event**

The terminal version must correspond to a registered event class. The expected
type string is `"{event_base_type}.{terminal_version}"` and must exist in
`_events_and_commands`.

**4. Walk chains from each source version**

For each `from_version` that appears as a source, walk the adjacency map
collecting upcaster instances until reaching the terminal:

```python
chain = []
v = start_version
while v in adjacency:
    if v in visited:
        raise ConfigurationError("Cycle detected")
    visited.add(v)
    to_v, upcaster_cls = adjacency[v]
    chain.append(upcaster_cls())  # instantiate once
    v = to_v

assert v == terminal_version  # or ConfigurationError (gap)
```

Upcasters are instantiated once during chain building and reused for every
subsequent upcast call. Since `upcast()` should be stateless and side-effect-
free, this is safe and avoids per-event instantiation overhead.

**5. Store results**

```python
self._chains[(event_base_type, start_version)] = chain
self._version_map[f"{event_base_type}.{start_version}"] = current_cls
```

After building, `_edges` is cleared — it is no longer needed.

### Validation Errors

All validation runs at startup during `domain.init()`. No validation happens
at runtime during deserialization. The following errors are caught:

| Error | Cause | Example |
|-------|-------|---------|
| Duplicate upcaster | Two upcasters with same `(event_type, from_version)` | Two classes both claiming `v1→v2` |
| Non-convergent chain | Multiple terminal versions | `v1→v2` and `v1a→v3` — terminals are `v2` and `v3` |
| Cycle | Version graph contains a loop | `v1→v2` and `v2→v1` |
| Gap | Chain doesn't reach terminal | `v1→v2` registered but `v2→v3` missing, terminal is `v3` |
| Missing event class | Terminal version not in `_events_and_commands` | Chain ends at `v99` but event `__version__` is `"v2"` |

## Runtime Execution

### The `to_domain_object()` Integration

The integration lives in `Message.to_domain_object()` in
`src/protean/utils/eventing.py`. The change is minimal:

```python
def to_domain_object(self):
    type_string = self.metadata.headers.type
    element_cls = current_domain._events_and_commands.get(type_string)
    data = self.data

    if element_cls is None:
        # Type string not found — try upcasting
        upcaster_chain = current_domain._upcaster_chain
        element_cls = upcaster_chain.resolve_event_class(type_string)

        if element_cls is None:
            raise ConfigurationError(
                f"Message type {type_string} is not registered"
            )

        base_type, _, from_version = type_string.rpartition(".")
        data = upcaster_chain.upcast(base_type, from_version, data)

    return element_cls(_metadata=self.metadata, **data)
```

### Type String Parsing

Type strings follow the format `"{DomainName}.{EventName}.{version}"`.
The `rpartition(".")` call splits on the **last** dot:

- `"MyDomain.OrderPlaced.v1"` → `base_type="MyDomain.OrderPlaced"`,
  `from_version="v1"`

This handles event names that contain dots correctly (though Protean event
names conventionally don't).

### Chain Application

`UpcasterChain.upcast()` is a simple loop:

```python
def upcast(self, event_base_type, from_version, data):
    chain = self._chains.get((event_base_type, from_version))
    if not chain:
        return data
    for upcaster in chain:
        data = upcaster.upcast(data)
    return data
```

Each upcaster receives the output of the previous one. The chain was
pre-computed during `build_chains()`, so lookup is O(1) and application is
O(n) where n is the number of version hops (typically 1-3).

### Metadata Handling

After upcasting, the event is constructed with the **original metadata**:

```python
return element_cls(_metadata=self.metadata, **data)
```

This means `metadata.headers.type` still contains the old type string
(e.g. `"Domain.OrderPlaced.v1"`) even though the constructed event is the
current version. However, `metadata.domain.version` contains the stored
version which accurately reflects what was originally written to the store.

The `_metadata` parameter in `BaseEvent.__init__` uses this metadata to set
internal tracking fields. The metadata is preserved for audit and debugging
purposes — it tells you which version was actually stored.

## All Deserialization Paths

Upcasting works transparently in all paths that flow through
`Message.to_domain_object()`:

| Path | How it reaches `to_domain_object()` |
|------|-------------------------------------|
| **Aggregate reconstruction** | `BaseEventStore.load_aggregate()` → reads events from store → `Message.to_domain_object()` → `aggregate._apply(event)` |
| **Repository.get()** | Delegates to event store → same as above |
| **Event handler dispatch** | `EventStoreSubscription` reads events → `Message.to_domain_object()` → `handler.handle(event)` |
| **Projector dispatch** | Same path as event handlers |
| **Manual `Message.deserialize()`** | User code calls `msg.to_domain_object()` directly |

Because all these paths converge on `to_domain_object()`, upcasting is
automatic in all of them. No path needs special handling.

## Performance Characteristics

### Current-Version Events (Hot Path)

```
_events_and_commands.get(type_string) → hit → construct event
```

A single dict lookup. Zero overhead from the upcasting system.

### Old-Version Events (Upcast Path)

```
_events_and_commands.get(type_string) → miss
→ _version_map.get(type_string) → hit → resolve class
→ type_string.rpartition(".") → parse
→ _chains.get((base_type, version)) → get chain
→ loop: upcaster.upcast(data) for each step
→ construct event
```

Two dict lookups + one string split + N upcaster calls. Since upcaster
instances are pre-allocated and chains are pre-computed, the only variable
cost is the upcaster logic itself (which should be fast dict operations).

### Memory

- One `UpcasterChain` instance per domain (attached to `domain._upcaster_chain`)
- One upcaster instance per registered step (created during `build_chains()`)
- Two dicts (`_chains` and `_version_map`) with entries proportional to the
  number of old versions across all event types
- `_edges` is cleared after building, releasing temporary registration data

## Relationship to Other Systems

### `_events_and_commands` Registry

The type string → class registry (`domain._events_and_commands`) is populated
by `_set_and_record_event_and_command_type()` during `domain.init()`. It only
contains **current-version** type strings (e.g. `"Domain.OrderPlaced.v3"`).

The upcaster chain's `_version_map` complements this by mapping **old-version**
type strings (e.g. `"Domain.OrderPlaced.v1"`, `"Domain.OrderPlaced.v2"`) to
the same current event class.

Together, they cover all possible type strings that might appear in the event
store.

### Event Store Adapters

Upcasting is **adapter-agnostic**. It operates on the `Message` layer, which
is common to all event store adapters (Memory, MessageDB, etc.). Event store
adapters read raw messages and return `Message` objects — upcasting happens
when `to_domain_object()` is called on those messages.

### Snapshots

Snapshot-based aggregate loading (`part_of(**snapshot_data)`) bypasses
`Message.to_domain_object()` and constructs the aggregate directly. If a
snapshot was taken with an old schema, the aggregate constructor handles it
(or fails). Upcasting does **not** apply to snapshots — if an old snapshot
fails to load, the system falls back to full event replay, where upcasting
does apply.

### `domain.init()` Ordering

The call order during initialization matters:

```
domain.init()
  → _set_and_record_event_and_command_type()  # 1. Build type string registry
  → _build_upcaster_chains()                  # 2. Validate & build chains
  → _setup_command_handlers()                 # 3. (unrelated)
  → ...
```

Step 2 depends on step 1 because chain validation verifies that terminal
versions have matching entries in `_events_and_commands`.

## Testing Approach

The upcasting system is tested at four levels:

1. **Unit: Registration** (`tests/upcaster/test_upcaster_registration.py`) —
   `upcaster_factory` validation, meta options, error cases
2. **Unit: Chain building** (`tests/upcaster/test_upcaster_chain.py`) —
   `UpcasterChain` construction, validation errors, chain resolution
3. **Integration: Deserialization** (`tests/upcaster/test_upcaster_deserialization.py`) —
   `Message.to_domain_object()` with old-version messages, round-trip through
   event store
4. **Integration: Event sourcing** (`tests/upcaster/test_upcaster_event_sourcing.py`) —
   Full aggregate reconstruction with mixed-version events, repository access

Tests write raw events directly to the event store (bypassing normal event
creation) to simulate historical events with old schemas. This accurately
reproduces the real-world scenario of an event store containing events from
different eras of the application.
