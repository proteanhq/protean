# Snapshots

<span class="pathway-tag pathway-tag-es">ES</span>

As event-sourced aggregates accumulate events, loading them requires
replaying every event from the beginning. Snapshots periodically
store the aggregate's full state, so loading only needs to replay
events since the last snapshot.

---

## How snapshots work

1. When loading an aggregate, Protean checks for a snapshot in the
   snapshot stream (`{category}:snapshot-{id}`)
2. If a snapshot exists, the aggregate is initialized from the snapshot
   and only post-snapshot events are replayed
3. After loading, if the number of new events exceeds the **snapshot
   threshold**, a fresh snapshot is automatically created

Snapshots are an optimization -- they are never the source of truth.
The event stream is authoritative. You can delete all snapshots and
rebuild them at any time.

---

## Configuration

Set the snapshot threshold globally in `domain.toml`:

```toml
snapshot_threshold = 50
```

The default threshold is **10 events**. When the number of events
since the last snapshot meets or exceeds this value, a new snapshot is
auto-created on the next load.

---

## Manual snapshot creation

### Programmatic API

```python
with domain.domain_context():
    # Snapshot a single aggregate instance
    domain.create_snapshot(Account, "acc-001")

    # Snapshot all instances of an aggregate
    count = domain.create_snapshots(Account)
    print(f"Created {count} snapshots")

    # Snapshot all event-sourced aggregates
    results = domain.create_all_snapshots()
    for name, count in results.items():
        print(f"{name}: {count} snapshots")
```

### CLI

```bash
# Single aggregate instance
protean snapshot create --domain=myapp --aggregate=Account --identifier=acc-001

# All instances of one aggregate
protean snapshot create --domain=myapp --aggregate=Account

# All event-sourced aggregates in the domain
protean snapshot create --domain=myapp
```

---

## Interaction with temporal queries

- **`at_version=N`**: Uses the snapshot if the snapshot version is
  <= N, then applies remaining events up to version N.
- **`as_of=datetime`**: Ignores snapshots entirely and filters events
  by timestamp, since snapshots don't carry per-event timestamps.

No new snapshots are created during temporal queries.

---

## When to snapshot

| Event volume | Strategy |
|-------------|----------|
| < 100 events/aggregate | Default threshold (10) is fine |
| 100-10,000 events | Set threshold to 50-100 |
| > 10,000 events | Set threshold to 100-500; run periodic CLI snapshots |

For high-volume aggregates, schedule periodic snapshot creation as a
cron job:

```bash
# Nightly snapshot refresh
0 2 * * * protean snapshot create --domain=myapp
```

---

!!! tip "See also"
    - [Snapshot CLI Reference](../../reference/cli/data/snapshot.md)
      -- Full CLI command documentation.
    - [Event Store Setup](./event-store-setup.md)
      -- Configuring the event store provider.
    - [Temporal Queries](./temporal-queries.md)
      -- Time-travel queries for event-sourced aggregates.
