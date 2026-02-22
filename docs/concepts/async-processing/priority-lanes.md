# Priority Lanes

## The Problem

In a CQRS system with asynchronous event processing, all events share the same
pipeline: the outbox publishes them to a single Redis Stream, and the Engine's
`StreamSubscription` processes them in order. This works well under normal
conditions, but it creates a serious problem when batch operations enter the
picture.

Consider this scenario: your e-commerce platform has been running for months.
You need to backfill a new `loyalty_tier` field onto 500,000 existing customer
records. The migration script loads each customer, sets the tier, and saves --
producing 500,000 `CustomerUpdated` events.

Those events flood the same stream that handles real-time customer
registrations, order placements, and payment confirmations. The Engine processes
them in FIFO order, so your production events are now stuck behind half a
million migration events. A customer who just placed an order waits minutes
(or longer) for their confirmation email because the projector is busy
replaying backfill events.

```
Without priority lanes:

  Production event ──┐
  Migration event  ──┤
  Migration event  ──┤──► Single Redis Stream ──► [Processed in FIFO order]
  Production event ──┤      "customer"             Migration events block
  Migration event  ──┘                              production traffic
```

You could pause the migration, wait for production to catch up, and resume in
small batches -- but this is manual, error-prone, and slow. You could run the
migration at 3 AM, but that only works if your traffic has a quiet window.

Priority lanes solve this by routing production and migration events to
separate streams and always draining production first.

---

## How Priority Lanes Work

Priority lanes split a single Redis Stream into two: a **primary lane** for
production traffic, and a **backfill lane** for low-priority work like
migrations and bulk imports. The Engine always drains the primary lane first.
Backfill events are only processed when there is no production work pending.

Think of it like a highway with an HOV lane. Regular traffic (backfill) flows
normally, but high-priority vehicles (production events) always get through
first. When the HOV lane is empty, regular traffic moves freely.

The split happens at two points in the pipeline:

1. **OutboxProcessor** (publish side): When publishing a message to the broker,
   the processor checks the message's priority against a configurable threshold.
   Messages below the threshold are published to the backfill stream instead of
   the primary stream.

2. **StreamSubscription** (consume side): When reading messages, the
   subscription first does a non-blocking read on the primary stream. Only if
   the primary stream is empty does it fall back to a short blocking read on
   the backfill stream.

```
                        Outbox                     Redis Streams           Engine
                        ------                     -------------           ------

Production  ──► Outbox(priority=0)  ──► "customer"            ──► [Drained first]
                                                                    Non-blocking read
                                                                         │
Migration   ──► Outbox(priority=-50) ──► "customer:backfill"  ──► [Drained when idle]
                                                                    Blocking read (1s cap)
                                                                    Only when primary empty
```

This design has several important properties:

- **Zero configuration on handlers.** Event handlers and projectors do not need
  to know about priority lanes. They process events the same way regardless of
  which lane the event arrived on.

- **No message loss.** Both lanes use the same consumer group and acknowledgment
  mechanism. Failed messages are retried and eventually moved to a dead letter
  queue, just like standard processing.

- **Responsive re-checking.** The backfill blocking read is capped at 1 second.
  If a production event arrives while the Engine is waiting on backfill, it will
  be picked up within 1 second.

---

## Priority Levels

Protean provides a `Priority` enum with five levels. The numeric values are
`IntEnum` members, so they can be compared and used as integers.

| Level | Value | Use Case |
|-------|------:|----------|
| `BULK` | -100 | Mass data imports, re-indexing, full re-projections. Lowest priority -- processed only when nothing else is pending. |
| `LOW` | -50 | Data migrations, background backfills, non-urgent batch jobs. Routed to the backfill lane. |
| `NORMAL` | 0 | All production traffic. The default for every command unless explicitly overridden. |
| `HIGH` | 50 | Time-sensitive operations like payment processing. Processed via the primary lane with higher outbox priority ordering. |
| `CRITICAL` | 100 | System-critical operations such as security events or compliance-related actions. Highest outbox fetch priority. |

The **threshold** (configurable, default `0`) determines which messages go to
the backfill lane. Messages with `priority < threshold` are routed to backfill;
messages with `priority >= threshold` stay on the primary lane.

With the default threshold of `0`:

- `BULK` (-100) and `LOW` (-50) go to the backfill lane.
- `NORMAL` (0), `HIGH` (50), and `CRITICAL` (100) stay on the primary lane.

Within each lane, messages are processed in FIFO order. Within the outbox,
messages are fetched in descending priority order, so `CRITICAL` messages are
published before `HIGH` messages, which are published before `NORMAL` messages.

---

## Setting Priority

There are two ways to set the priority for events produced by a command.

### Context Manager

Use `processing_priority()` to set the priority for all commands processed
within a block. This is the recommended approach for migration scripts and
batch jobs:

```python
from protean.utils.processing import processing_priority, Priority

# All events produced within this block get LOW priority
with processing_priority(Priority.LOW):
    for record in migration_data:
        domain.process(UpdateCustomer(
            customer_id=record["id"],
            loyalty_tier=record["tier"],
        ))
```

Contexts can be nested. The innermost context wins:

```python
with processing_priority(Priority.LOW):
    domain.process(cmd1)  # LOW

    with processing_priority(Priority.CRITICAL):
        domain.process(cmd2)  # CRITICAL

    domain.process(cmd3)  # LOW again
```

Priority is always restored when the context exits, even if an exception is
raised.

### Explicit Parameter

Pass `priority` directly to `domain.process()` for one-off overrides:

```python
from protean.utils.processing import Priority

# This specific command gets BULK priority
domain.process(
    ReindexProduct(product_id="SKU-001"),
    priority=Priority.BULK,
)
```

The explicit parameter takes precedence over any active context manager:

```python
with processing_priority(Priority.LOW):
    # This command uses CRITICAL despite the LOW context
    domain.process(cmd, priority=Priority.CRITICAL)
```

### Priority Resolution Order

When `domain.process()` is called, the priority is resolved as:

1. **Explicit `priority` parameter** on the `domain.process()` call, if provided.
2. **Active `processing_priority()` context**, if one is set.
3. **`Priority.NORMAL` (0)**, the default.

### How Priority Propagates

The resolved priority is stored in two places:

1. **Command metadata** (`DomainMeta.priority`): Embedded in the command when
   it is written to the event store. This ensures the priority survives across
   process boundaries — when the Engine picks up a command asynchronously, it
   reads the priority from the metadata and reconstructs the
   `processing_priority()` context before running the handler.

2. **Outbox records** (`Outbox.priority`): Written by `UoW.commit()` when
   events are persisted to the outbox table. The OutboxProcessor reads this
   value to decide which Redis Stream (primary or backfill) to publish to.

This means priority lanes work correctly regardless of whether commands are
processed synchronously or asynchronously.

---

## Configuration

Enable priority lanes in your `domain.toml`:

```toml
[server.priority_lanes]
enabled = true          # Enable the two-lane system (default: false)
threshold = 0           # Priority values below this go to backfill (default: 0)
backfill_suffix = "backfill"  # Suffix for the backfill stream name (default: "backfill")
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `false` | Whether to activate priority lanes. When `false`, all messages use a single stream regardless of priority. |
| `threshold` | int | `0` | Priority values strictly below this threshold are routed to the backfill lane. Values at or above the threshold stay on the primary lane. |
| `backfill_suffix` | string | `"backfill"` | Suffix appended to the stream category to form the backfill stream name. For example, with `stream_category="customer"` and `backfill_suffix="backfill"`, the backfill stream is `customer:backfill`. |

### Environment-Specific Configuration

You can enable priority lanes only in production while keeping them disabled in
development:

```toml
# Development: lanes disabled (the default)
[server.priority_lanes]
enabled = false

# Production: lanes enabled
[production.server.priority_lanes]
enabled = true
threshold = 0
```

### Custom Threshold

If you want `LOW` (-50) events to go to backfill but want a finer-grained
split, adjust the threshold:

```toml
[server.priority_lanes]
enabled = true
threshold = -25  # Only BULK (-100) and LOW (-50) go to backfill
                 # A custom priority of -10 would stay on primary
```

### Custom Suffix

You can customize the backfill stream name suffix:

```toml
[server.priority_lanes]
enabled = true
backfill_suffix = "migration"  # Streams become "customer:migration" etc.
```

---

## Ordering Guarantees

Priority lanes provide the following ordering guarantees:

### Intra-lane FIFO

Within each lane (primary or backfill), messages are processed in strict FIFO
order. If events A and B are both on the primary lane and A was published first,
A will be processed before B. The same holds for the backfill lane.

### Cross-lane ordering is not guaranteed

If event A is on the primary lane and event B is on the backfill lane, their
relative processing order depends on when each lane is drained. The primary
lane is always drained first, so in practice primary events are processed
before backfill events. However, if a backfill batch is already in progress
when a new primary event arrives, the primary event will be picked up after the
current backfill batch completes (within 1 second at most).

### Outbox priority ordering

Within the outbox table itself, messages are fetched in descending priority
order. This means `CRITICAL` (100) messages are published to the broker before
`HIGH` (50) messages, which are published before `NORMAL` (0) messages. This
ordering applies within a single outbox polling cycle.

### What this means in practice

For most use cases, the key guarantee is simple: **production events are never
blocked by migration events.** The Engine always checks the primary stream
before falling back to backfill, and the backfill blocking timeout is capped at
1 second to ensure responsive re-checking.

---

## When to Use

Priority lanes are designed for scenarios where bulk or background work could
starve production traffic:

- **Data migrations**: Backfilling a new field across thousands of existing
  records. Wrap the migration loop in `processing_priority(Priority.LOW)`.

- **Bulk imports**: Importing customer data from a CSV or external system.
  Use `Priority.BULK` to ensure import events do not delay real-time
  operations.

- **Re-indexing / re-projection**: Rebuilding a projection from scratch by
  replaying historical events. Tag the replay commands with `Priority.LOW`.

- **Backfill jobs**: Enriching existing records with data from an external
  API. These jobs can run for hours without affecting production throughput.

- **Scheduled batch processing**: End-of-day reconciliation, report generation,
  or periodic cleanup tasks that produce a burst of events.

---

## When NOT to Use

Priority lanes are not appropriate in every situation:

- **Events requiring strict global ordering.** If your domain requires that
  event A is always processed before event B regardless of their priority,
  do not use priority lanes. The two-lane system intentionally allows primary
  events to "jump ahead" of backfill events.

- **Event-sourced aggregate reconstruction.** Priority lanes only affect the
  outbox-to-broker pipeline (stream subscriptions). Event-sourced aggregates
  that reconstruct state from the event store are not affected by priority
  lanes, since they read directly from the event store, not from Redis Streams.

- **Low-volume systems.** If your system processes a small number of events and
  migrations complete in seconds, priority lanes add unnecessary complexity.
  The feature is designed for systems where batch operations produce enough
  events to create visible latency in production processing.

- **Single-stream idempotency assumptions.** If your event handlers rely on
  processing all events for a stream category in a single FIFO order (for
  example, to detect duplicates by position or to use Redis stream message IDs
  for ordering), splitting into two streams will break that assumption. Message
  IDs are no longer globally ordered across the primary and backfill streams.

---

## Next Steps

- [Running Migrations Without Blocking Production](../../patterns/running-migration-with-priority-lanes.md) --
  A practical walkthrough of using priority lanes for a data migration.
- [Outbox Pattern](./outbox.md) -- How the outbox ensures reliable
  message delivery.
- [Subscription Types](../../reference/server/subscription-types.md) -- How `StreamSubscription`
  consumes messages from Redis Streams.
- [Configuration](../../reference/server/configuration.md) -- Full configuration reference for
  subscriptions and the server.
