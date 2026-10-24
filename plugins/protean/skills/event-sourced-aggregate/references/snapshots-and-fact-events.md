# Snapshots and Fact Events

## Snapshots

### Problem

Replaying hundreds of events to rebuild an aggregate is slow. A snapshot saves the aggregate's state so a load replays only the events after it.

### Configuration

The threshold defaults to 10. Set it in domain configuration:

```python
domain.config["snapshot_threshold"] = 10  # Snapshot after every 10 events
```

Or in `domain.toml`:

```toml
snapshot_threshold = 10
```

### How Snapshots Work

1. When loading an aggregate, the event store first checks for a snapshot
2. If a snapshot exists, it initializes the aggregate from the snapshot
3. Only events **after** the snapshot are replayed
4. If no snapshot exists, all events are replayed (normal behavior)

Snapshots are written only on load. After a load, if the events replayed since the last snapshot reach the threshold, the event store writes a new snapshot.

A snapshot that no longer constructs the aggregate (a field was renamed, removed or made required) is discarded with a WARNING log, and the load falls back to a full replay.

### Snapshot Stream Naming

```
{stream_category}:snapshot-{aggregate_id}
```

`stream_category` already carries the domain name prefix (`{domain_name}::{aggregate_name}`, set at registration), so for a domain named `test` the snapshot stream for `Account` is `test::account:snapshot-ACC-001`. The `:` before `snapshot` separates snapshot streams from event streams, which use `-`.

## Fact Events

### What Are Fact Events?

A fact event carries the complete current state of an aggregate after each persist. Delta events carry individual changes.

### Enabling Fact Events

```python
@domain.aggregate(event_sourced=True, fact_events=True)
class Product:
    name: String(required=True)
    price: Float(required=True)
    status: String(default="ACTIVE")
```

### How They Work

1. When `repo.add(aggregate)` is called, the repository:
   - Converts the aggregate's current state to a dict
   - Creates a dynamically-generated `ProductFactEvent` with that data
   - Raises it via `aggregate.raise_(fact_event)`
2. The fact event is persisted to a separate stream

### Fact Event Stream Naming

Fact events use a distinct stream:

```
{stream_category}-fact-{aggregate_id}
```

`stream_category` already carries the domain name prefix, so for a domain named `test` the fact stream for `Product` is `test::product-fact-PROD-001`.

### Delta Events vs Fact Events

| Aspect | Delta Events | Fact Events |
|--------|-------------|-------------|
| **Content** | Individual change | Complete state snapshot |
| **Size** | Small, focused | Larger, complete |
| **Naming** | `ProductPriceChanged` | `ProductFactEvent` (auto-generated) |
| **Stream** | `product-{id}` | `product-fact-{id}` |
| **Created by** | Developer (explicit) | Framework (automatic) |
| **Use case** | Event sourcing, audit | External sync, projections |

### When to Use Fact Events

The skill lists the main cases. One more: other bounded contexts need full entity snapshots.

### When NOT to Use Fact Events

- When delta events are sufficient for downstream consumers
- When event payload size is a concern (fact events are larger)
- When consumers need to know *what changed*, not just *current state*

## Combining Both

You can use both snapshots and fact events on the same aggregate:

```python
@domain.aggregate(event_sourced=True, fact_events=True)
class Order:
    ...

# Plus configuration
domain.config["snapshot_threshold"] = 10
```

Snapshots speed up loading the aggregate. Fact events give external consumers the full state. The two do not interfere with each other.
