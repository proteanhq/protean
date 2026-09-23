# Upcaster Chain

## Overview

The `UpcasterChain` manages registration, validation, and application of upcasters for all event types. It is built once during `domain.init()` and provides O(1) runtime lookup for applying transformations.

**Source**: `protean/src/protean/utils/upcasting.py`

## How Chain Building Works

### 1. Edge Registration

During `domain.init()`, each registered upcaster is recorded as a directed edge:

```
(from_version) → (to_version)
```

Edges are grouped by **event_base_type** — the type string prefix without the version (e.g., `"MyDomain.OrderPlaced"`).

### 2. Adjacency Map

For each event_base_type, edges are organized into an adjacency map:

```python
adjacency = {from_version: (to_version, upcaster_cls)}
```

Each `from_version` maps to exactly one target. Duplicates (two upcasters with the same `from_version` for the same event type) raise `ConfigurationError`.

### 3. Terminal Version Detection

The terminal version is any version that appears as a `to_version` but never as a `from_version`. There must be exactly one terminal version — this is the current event version.

```python
terminal_versions = all_to_versions - all_from_versions
# Must be exactly {current_version}
```

### 4. Chain Walking

For each source version, the algorithm walks the adjacency map collecting upcaster instances until reaching the terminal:

```python
chain = []
v = start_version
while v in adjacency:
    to_v, upcaster_cls = adjacency[v]
    chain.append(upcaster_cls())  # Instantiate once, reuse
    v = to_v
```

Upcasters are instantiated once during chain building and reused for every subsequent upcast call. Since `upcast()` must be stateless, this is safe.

### 5. Storage

Pre-computed chains are stored for O(1) lookup:

```python
_chains[(event_base_type, from_version)] = [upcaster_instance, ...]
_version_map["Domain.Event.v1"] = CurrentEventClass
```

After building, the raw edges are cleared — they are no longer needed.

## Internal Data Structures

```python
class UpcasterChain:
    # Pre-build: edges collected during registration
    _edges: dict[str, list[tuple[int, int, type]]]
    # {event_base_type: [(from_version, to_version, upcaster_cls), ...]}

    # Post-build: pre-computed chains
    _chains: dict[tuple[str, int], list[Any]]
    # {(event_base_type, from_version): [upcaster_instance, ...]}

    # Post-build: old type strings → current event class
    _version_map: dict[str, type]
    # {"Domain.Event.v1": CurrentEventClass, ...}
```

## Domain Integration

Chain building happens during `domain.init()`, immediately after event type strings are registered:

```python
# In Domain.init():
self._set_and_record_event_and_command_type()  # 1. Build type string registry
self._build_upcaster_chains()                  # 2. Validate & build chains
```

This ordering is critical because chain validation needs `_events_and_commands` to verify that terminal versions match registered event classes.

## Runtime Application

When `Message.to_domain_object()` encounters an old-version type string:

1. Direct lookup in `_events_and_commands` misses
2. `_upcaster_chain.resolve_event_class(type_string)` finds the current class
3. Type string is parsed: `"Domain.OrderPlaced.v1"` → base=`"Domain.OrderPlaced"`, version=`1`
4. `_upcaster_chain.upcast(base_type, 1, data)` applies the pre-computed chain
5. Current event class is constructed with the transformed data

## Validation Errors

All validation runs at startup during `domain.init()`. The following errors are caught:

### Duplicate upcaster

Two upcasters registered for the same `(event_type, from_version)`:

```python
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcasterA(BaseUpcaster): ...

@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class UpcasterB(BaseUpcaster): ...
# → ConfigurationError: Duplicate upcaster for OrderPlaced from version v1
```

### Cycle detection

Version graph contains a loop:

```python
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class Forward(BaseUpcaster): ...

@domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=1)
class Backward(BaseUpcaster): ...
# → ConfigurationError: Upcaster chain does not converge
```

### Duplicate from_version

Two upcasters with the same `from_version` but different targets:

```python
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
class BranchA(BaseUpcaster): ...

@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=3)
class BranchB(BaseUpcaster): ...
# → ConfigurationError: Duplicate upcaster for OrderPlaced from version 1
```

### Missing event class

Chain terminal doesn't match any registered event `__version__`:

```python
# OrderPlaced.__version__ = 2
@domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=99)
class WrongTarget(BaseUpcaster): ...
# → ConfigurationError: no event is registered with type string ...v99
```

## Performance Characteristics

### Current-version events (hot path)

A single dict lookup in `_events_and_commands`. Zero overhead from upcasting.

### Old-version events (upcast path)

Two dict lookups (`_events_and_commands` miss + `_version_map` hit) + one string split + N upcaster calls (typically 1-3). Since chains are pre-computed and upcasters pre-instantiated, the only variable cost is the upcaster logic itself.
