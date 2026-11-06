# Snapshots

<span class="pathway-tag pathway-tag-es">ES</span>

As event-sourced aggregates accumulate events, Protean has to replay every
event from the beginning each time it loads one. Snapshots periodically store
the aggregate's full state, so loading only needs to replay events since the
last snapshot.

---

## How snapshots work

1. When loading an aggregate, Protean checks for a snapshot in the
   snapshot stream (`{category}:snapshot-{id}`)
2. If a snapshot exists, the aggregate is initialized from the snapshot
   and only post-snapshot events are replayed
3. After loading, if the number of new events exceeds the **snapshot
   threshold**, a fresh snapshot is automatically created

Snapshots are an optimization. They are never the source of truth. The event
stream is authoritative. You can delete all snapshots and rebuild them at any
time.

---

## Snapshots and schema changes

When you change an event-sourced aggregate's fields, a snapshot written before
the change may no longer match the class. When you rename a field, remove one,
or add a required one, the stored snapshot no longer matches the current
schema. Protean can then no longer construct the aggregate from that snapshot.

Protean checks the snapshot each time it loads the aggregate. Protean reads the
snapshot first. When the snapshot no longer constructs the aggregate, Protean
discards the snapshot and rebuilds the aggregate from the event stream, the
authoritative record. Once the replayed event count reaches the threshold,
Protean writes a fresh snapshot in the current schema in place of the stale
one. Later loads are then fast again.

In two cases, Protean discards and logs a stale snapshot again on each load
without writing a fresh one. The first is an `at_version` query whose requested
version is at or above the snapshot version. The second is an aggregate holding
fewer events than the threshold. Rebuild with `protean snapshot create` or
`domain.create_snapshots(YourAggregate)` to stop the repeat. An `as_of` query
never reads snapshots, so it neither uses nor discards them.

Each discard is logged as a WARNING on the
[`protean.snapshot`](../../reference/logging.md#proteansnapshot) channel, with
the aggregate name, its identifier, and the reason the snapshot was rejected.

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

The examples below use this event-sourced `Account`, with one account
`acc-001` that has three events:

```python
--8<-- "guides/change-state/snapshots/001.py:aggregate"
```

### Programmatic API

```python
--8<-- "guides/change-state/snapshots/001.py:manual"
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

!!! seealso "See also"
    - [Snapshot CLI Reference](../../reference/cli/data/snapshot.md):
      Full CLI command documentation.
    - [Event Store Setup](./event-store-setup.md):
      Configuring the event store provider.
    - [Temporal Queries](./temporal-queries.md):
      Time-travel queries for event-sourced aggregates.
