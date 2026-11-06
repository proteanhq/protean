# `protean snapshot`

The `protean snapshot` command group creates snapshots for event-sourced
aggregates. A snapshot captures aggregate state at a point in time to make
hydration faster. Instead of replaying the entire event history, Protean loads
the aggregate from the latest snapshot and replays only the events that follow
it.

Protean auto-creates snapshots when the event count exceeds the
`snapshot_threshold` (default 10). You can also create snapshots by hand for:

- **Admin maintenance**: Force snapshot creation after data migrations or bulk
  event imports
- **Performance tuning**: Pre-warm snapshots for hot aggregates before they
  are loaded
- **Threshold bypass**: Create snapshots for aggregates with fewer events than
  the threshold

All commands accept a `--domain` option to specify the domain module path
(defaults to the current directory).

## Which commands does the group offer?

| Command | Description |
|---------|-------------|
| `protean snapshot create` | Create snapshots for event-sourced aggregates |

## `protean snapshot create`

Creates snapshots for event-sourced aggregates. Supports three modes:

### Snapshot a single aggregate instance

```bash
protean snapshot create --domain=my_domain --aggregate=User --identifier=abc-123
```

Creates a snapshot for one specific aggregate instance. The snapshot is
reconstructed from the full event stream regardless of whether a snapshot
already exists (forced refresh).

### Snapshot all instances of one aggregate

```bash
protean snapshot create --domain=my_domain --aggregate=User
```

Discovers all instances of the specified aggregate and creates a snapshot
for each.

### Snapshot all event-sourced aggregates

```bash
protean snapshot create --domain=my_domain
```

Creates snapshots for every instance of every event-sourced aggregate
registered in the domain.

**Options**

| Option | Description | Default |
|--------|-------------|---------|
| `--domain` | Domain module path | `.` (current directory) |
| `--aggregate` | Aggregate class name (e.g. `User`) | All ES aggregates |
| `--identifier` | Specific aggregate identifier (requires `--aggregate`) | All instances |

## What does the command print?

```
# Single instance:
Snapshot created for User with identifier abc-123.

# All instances of one aggregate:
Created 42 snapshot(s) for User.

# All event-sourced aggregates:
  User: 42 snapshot(s)
  Order: 15 snapshot(s)
Created 57 snapshot(s) across 2 aggregate(s).
```

## What happens when the command fails?

| Condition | Behavior |
|-----------|----------|
| `--identifier` without `--aggregate` | Aborts with error message |
| Invalid domain path | Aborts with "Error loading Protean domain" |
| Aggregate not found in registry | Aborts with "not found in domain" |
| Non-event-sourced aggregate | Aborts with "not an event-sourced aggregate" |
| No events for identifier | Aborts with "does not exist" |
| No ES aggregates in domain | Prints informational message |

## How do the commands find your domain?

The `protean snapshot` commands use the same domain discovery mechanism as
`protean server`. The `--domain` option accepts:

- A Python module path: `my_package.domain`
- A file path: `src/my_domain.py`
- A module with instance name: `my_domain:custom_domain`
- `.` (default): Searches the current directory

See [Domain Discovery](../project/discovery.md) for the full resolution logic.

## Create snapshots from Python code

You can create the same snapshots from scripts or the `protean shell` with the
Domain methods `create_snapshot`, `create_snapshots` and
`create_all_snapshots`:

??? example "The domain this example uses"

    ```python
    --8<-- "reference/cli/data/snapshot/001.py:domain"
    ```

```python
--8<-- "reference/cli/data/snapshot/001.py:api"
```
