# Snapshots and Fact Events

Two mechanisms for optimizing event-sourced aggregate performance and enabling state-based subscriptions.

## Snapshots

### Problem

Replaying hundreds of events to reconstruct an aggregate is slow. Snapshots periodically save the current state to shortcut this process.

### Configuration

Set the snapshot threshold in domain configuration:

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

After loading, if the number of events since the last snapshot exceeds the threshold, a new snapshot is automatically written.

### Snapshot Stream Naming

Snapshots are stored in a special stream:

```
{stream_category}:snapshot-{aggregate_id}
```

`stream_category` already carries the domain name prefix (`{domain_name}::{aggregate_name}`, set at registration), so
for a domain named `test` the snapshot stream for `Account` is `test::account:snapshot-ACC-001`.

Note the `:` separator (not `-`) which distinguishes snapshot streams from event streams.

### Performance Impact

| Scenario | Without Snapshots | With Snapshots (threshold=10) |
|----------|------------------|-------------------------------|
| 5 events | Replay 5 events | Replay 5 events (no snapshot yet) |
| 15 events | Replay 15 events | Load snapshot + replay 5 events |
| 100 events | Replay 100 events | Load snapshot + replay ≤10 events |

## Fact Events

### What Are Fact Events?

Fact events are auto-generated events that capture the **complete current state** of an aggregate after each persist. They complement delta events (which capture individual changes).

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

Example: `product-fact-PROD-001`

This separation allows subscribers to independently consume delta events or fact events.

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

- **External system integration**: External systems need complete state without replaying history
- **Migration path**: Transitioning from traditional to event-sourced architecture
- **Simple projections**: Building read models that just need current state
- **Cross-boundary communication**: Other bounded contexts need full entity snapshots

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

- **Snapshots** optimize internal aggregate loading (read performance)
- **Fact events** provide state snapshots for external consumers (integration)

They serve different purposes and don't interfere with each other.
