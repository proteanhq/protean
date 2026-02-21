# `protean projection`

The `protean projection` command group manages projections -- read-optimized
views built from domain events. Currently it provides a `rebuild` command
that reconstructs projections by replaying events from the event store.

Projection rebuilding is essential when:

- **Fixing a projector bug**: A bug caused incorrect data in a projection;
  rebuild replays all events through the corrected projector.
- **Adding a new projection**: A new projection is added to an existing system
  and needs to be populated from historical events.
- **Schema changes**: The projection's schema changed (new fields, renamed
  columns) and data must be regenerated.
- **Data corruption recovery**: Projection data was corrupted or accidentally
  deleted.

All commands accept a `--domain` option to specify the domain module path
(defaults to the current directory).

!!! warning

    Stop the Protean server before rebuilding projections. Concurrent event
    processing during a rebuild can cause data inconsistencies because the
    rebuild truncates projection data before replaying events.

## Commands

| Command | Description |
|---------|-------------|
| `protean projection rebuild` | Rebuild projections by replaying events |

## `protean projection rebuild`

Rebuilds projections by truncating existing data and replaying all events
from the event store through the associated projectors. Upcasters are
applied automatically during replay.

### Rebuild a specific projection

```bash
protean projection rebuild --domain=my_domain --projection=Balances
```

Rebuilds a single projection by name. The command:

1. Finds all projectors that target the named projection
2. Truncates existing projection data (database rows or cache entries)
3. Reads all events from each projector's stream categories
4. Replays events in global order through the projector handlers

### Rebuild all projections

```bash
protean projection rebuild --domain=my_domain
```

Without `--projection`, rebuilds every projection registered in the domain.
Each projection is rebuilt independently.

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--projection` | Projection class name (e.g. `Balances`) | All projections |
| `--batch-size` | Number of events to read per batch | `500` |

## Output

```
# Single projection:
Rebuilt projection 'Balances': 42 events processed through 1 projector(s) across 2 category/categories.

# Single projection with skipped events:
Rebuilt projection 'Balances': 40 events processed through 1 projector(s) across 2 category/categories.
  (2 events skipped)

# All projections:
  Balances: 42 events processed
  UserDirectory: 18 events processed
Rebuilt 2 projection(s), 60 total events processed.
```

Events are "skipped" when they cannot be resolved to a domain object --
typically deprecated event types that have been removed from the codebase
without an upcaster chain. Skipped events are logged as warnings but do
not cause the rebuild to fail.

## Error handling

| Condition | Behavior |
|-----------|----------|
| Invalid domain path | Aborts with "Error loading Protean domain" |
| Projection not found in registry | Aborts with "Projection 'X' not found" |
| No projectors for projection | Aborts with error message |
| No projections in domain | Prints "No projections found in domain." |
| Unresolvable event type | Logs warning, skips event, continues |

## Domain discovery

The `protean projection` commands use the same domain discovery mechanism as
`protean server`. The `--domain` option accepts:

- A Python module path: `my_package.domain`
- A file path: `src/my_domain.py`
- A module with instance name: `my_domain:custom_domain`
- `.` (default): Searches the current directory

See [Domain Discovery](discovery.md) for the full resolution logic.

---

## Programmatic API

The same functionality is available as Domain methods for use in scripts or
the `protean shell`:

```python
from protean.utils.projection_rebuilder import RebuildResult

# Rebuild a single projection
result = domain.rebuild_projection(Balances)
assert result.success
print(f"{result.events_dispatched} events replayed")

# Rebuild a single projection with custom batch size
result = domain.rebuild_projection(Balances, batch_size=1000)

# Rebuild all projections
results = domain.rebuild_all_projections()
for name, result in results.items():
    print(f"{name}: {result.events_dispatched} events")
```

### `domain.rebuild_projection(projection_cls, batch_size=500)`

Rebuild a single projection. Returns a `RebuildResult`:

| Field | Type | Description |
|-------|------|-------------|
| `projection_name` | `str` | Name of the projection class |
| `projectors_processed` | `int` | Number of projectors that were run |
| `categories_processed` | `int` | Total stream categories read across all projectors |
| `events_dispatched` | `int` | Events successfully processed |
| `events_skipped` | `int` | Events that could not be resolved or failed |
| `errors` | `list[str]` | Error messages (empty on success) |
| `success` | `bool` | `True` when `errors` is empty |

### `domain.rebuild_all_projections(batch_size=500)`

Rebuild every projection in the domain. Returns a
`dict[str, RebuildResult]` mapping projection class names to their results.

---

## How it works

The rebuild process has three phases:

### 1. Discover projectors

The domain registry is queried for all projectors that target the given
projection (via `domain.projectors_for(projection_cls)`). If no projectors
are found, the rebuild fails immediately with an error.

### 2. Truncate projection data

Existing projection data is cleared:

- **Database-backed projections** (the default): All rows are deleted via
  the DAO's `_delete_all()` method.
- **Cache-backed projections**: Keys matching the projection's naming
  pattern are removed via `remove_by_key_pattern()`.

### 3. Replay events

For each projector, events are read from all of its stream categories and
merged in global position order. This ensures correct cross-aggregate
ordering -- for example, a `Registered` event from the `user` category is
always processed before a `Transacted` event from the `transaction` category
if that is the order in which they were originally stored.

Each event is dispatched through the projector's `_handle()` method, which:

- Converts the stored `Message` to a domain event object (applying
  upcasters automatically)
- Looks up the `@on` handler for the event type
- Executes the handler within a `UnitOfWork`
- Events with no matching `@on` handler are silently skipped (no error)

If an event type cannot be resolved (deprecated event without an upcaster
chain), a `ConfigurationError` is caught, a warning is logged, and the
event is skipped. Other exceptions during handler execution are also caught,
logged, and skipped -- the rebuild continues with the remaining events.

The rebuild is **idempotent**: running it again truncates and replays from
scratch. No checkpointing or partial state is maintained.
