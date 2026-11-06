# Keep production events ahead of bulk work with priority lanes

## The Problem

In a CQRS system with asynchronous event processing, all events share the same
pipeline: the outbox publishes them to a single Redis Stream, and the Engine's
`StreamSubscription` processes them in order. This single pipeline works well
under normal load. It causes a serious problem once batch operations start
producing events.

Consider this scenario: your e-commerce platform has been running for months.
You need to backfill a new `loyalty_tier` field onto 500,000 existing customer
records. The migration script loads each customer, sets the tier, and saves,
producing 500,000 `CustomerUpdated` events.

Those events go to the same stream that carries real-time customer
registrations, order placements, and payment confirmations. The Engine
processes them in FIFO order, so your production events are now stuck behind
half a million migration events. A customer who just placed an order waits
minutes (or longer) for their confirmation email. The projector is busy
replaying backfill events first.

```
Without priority lanes:

  Production event ──┐
  Migration event  ──┤
  Migration event  ──┤──► Single Redis Stream ──► [Processed in FIFO order]
  Production event ──┤      "customer"             Migration events block
  Migration event  ──┘                              production traffic
```

You could pause the migration, wait for production to catch up, and resume in
small batches. That approach is manual, error-prone, and slow. You could run
the migration at 3 AM, but that only works if your traffic has a quiet window.

Priority lanes stop migration events from delaying production events. They
route production and migration events to separate streams and always drain
production first.

---

## How Priority Lanes Work

Priority lanes split a single Redis Stream into two: a **primary lane** for
production traffic, and a **backfill lane** for low-priority work like
migrations and bulk imports. The Engine always drains the primary lane first.
Backfill events are only processed when there is no production work pending.

The split happens at two points in the pipeline:

1. **OutboxProcessor** (publish side): When publishing a message to the broker,
   the processor checks the message's priority against a configurable threshold.
   Messages below the threshold are published to the backfill stream instead of
   the primary stream.

2. **StreamSubscription** (consume side): When reading messages, the
   subscription first does a non-blocking read on the primary stream. Only when
   the primary stream is empty does the subscription make one short blocking
   read on both the primary and the backfill stream.

```
                        Outbox                     Redis Streams           Engine
                        ------                     -------------           ------

Production  ──► Outbox(priority=0)  ──► "customer"            ──► [Drained first]
                                                                    Non-blocking read
                                                                         │
Migration   ──► Outbox(priority=-50) ──► "customer:backfill"  ──► [Drained when idle]
                                                                    Blocking read on both
                                                                    streams (1s cap)
                                                                    Only when primary empty
```

This design has several important properties:

- **Handlers need no configuration**: Event handlers and projectors do not need
  to know about priority lanes. They process events the same way regardless of
  which lane the event arrived on.

- **No message is lost**: Both lanes use the same consumer group and
  acknowledgment mechanism. Failed messages are retried and eventually moved to
  a dead letter queue, just like standard processing.

- **An idle Engine picks up production events at once**: On the Redis broker,
  the blocking read waits on both streams at once. If a production event
  arrives at an idle Engine, the read returns with it. When one read returns
  entries on both streams, the primary entries are processed first.

---

## What priority levels does Protean provide?

Protean provides a `Priority` enum with five levels. The numeric values are
`IntEnum` members, so they can be compared and used as integers.

| Level | Value | Use Case |
|-------|------:|----------|
| `BULK` | -100 | Mass data imports and re-indexing by commands. Lowest priority, processed only when nothing else is pending. `domain.rebuild_projection()` does not go through the broker, so no priority applies to it. |
| `LOW` | -50 | Data migrations, background backfills, non-urgent batch jobs. Routed to the backfill lane. |
| `NORMAL` | 0 | All production traffic. The default for every command unless explicitly overridden. |
| `HIGH` | 50 | Time-sensitive operations like payment processing. Processed via the primary lane with higher outbox priority ordering. |
| `CRITICAL` | 100 | System-critical operations such as security events or compliance-related actions. Highest outbox fetch priority. |

The **threshold** (configurable, default `0`) determines which messages go to
the backfill lane. Messages with `priority < threshold` are routed to backfill.
Messages with `priority >= threshold` stay on the primary lane.

With the default threshold of `0`:

- `BULK` (-100) and `LOW` (-50) go to the backfill lane.
- `NORMAL` (0), `HIGH` (50), and `CRITICAL` (100) stay on the primary lane.

Within each lane, messages are processed in FIFO order. The outbox fetches
messages in descending priority order. It publishes `CRITICAL` messages before
`HIGH` messages, and `HIGH` messages before `NORMAL` messages.

---

## Setting Priority

There are two ways to set the priority for events produced by a command.

### Set the priority for a block with a context manager

Use `processing_priority()` to set the priority for all commands processed
within a block. This is the recommended approach for migration scripts and
batch jobs:

```python
--8<-- "concepts/async-processing/priority-lanes/001.py:customer"
--8<-- "concepts/async-processing/priority-lanes/001.py:context_manager"
```

Contexts can be nested. When contexts are nested, the innermost context sets
the priority:

```python
--8<-- "concepts/async-processing/priority-lanes/001.py:nested"
```

Protean always restores the priority when the context exits. It restores the
priority even if an exception is raised.

### Pass the priority to `domain.process()`

Pass `priority` directly to `domain.process()` for one-off overrides:

```python
--8<-- "concepts/async-processing/priority-lanes/001.py:product"
--8<-- "concepts/async-processing/priority-lanes/001.py:explicit"
```

The explicit parameter takes precedence over any active context manager:

```python
--8<-- "concepts/async-processing/priority-lanes/001.py:override"
```

### How does Protean resolve the priority?

When `domain.process()` is called, the priority is resolved as:

1. **Explicit `priority` parameter** on the `domain.process()` call, if provided.
2. **Active `processing_priority()` context**, if one is set.
3. **`Priority.NORMAL` (0)**, the default.

### How Priority Propagates

The resolved priority is stored in two places:

1. **Command metadata** (`DomainMeta.priority`): Embedded in the command when
   it is written to the event store. The command carries the priority across
   process boundaries. When the Engine picks up a command asynchronously, it
   reads the priority from the metadata. It then reconstructs the
   `processing_priority()` context before running the handler.

2. **Outbox records** (`Outbox.priority`): Written by `UoW.commit()` when
   events are persisted to the outbox table. The OutboxProcessor reads this
   value to decide which Redis Stream (primary or backfill) to publish to.

With the priority stored in both places, priority lanes work correctly whether
commands are processed synchronously or asynchronously.

---

## Configure priority lanes

Enable priority lanes in your `domain.toml`:

```toml
[server.priority_lanes]
enabled = true          # Enable the two-lane system (default: false)
threshold = 0           # Priority values below this go to backfill (default: 0)
backfill_suffix = "backfill"  # Suffix for the backfill stream name (default: "backfill")
```

### Which options can you set?

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `false` | Whether to activate priority lanes. When `false`, all messages use a single stream regardless of priority. |
| `threshold` | int | `0` | Priority values strictly below this threshold are routed to the backfill lane. Values at or above the threshold stay on the primary lane. |
| `backfill_suffix` | string | `"backfill"` | Suffix appended to the stream category to form the backfill stream name. For example, with `stream_category="customer"` and `backfill_suffix="backfill"`, the backfill stream is `customer:backfill`. |

### Enable priority lanes only in production

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

### Set a custom threshold

If you want `LOW` (-50) events to go to backfill but want a finer-grained
split, adjust the threshold:

```toml
[server.priority_lanes]
enabled = true
threshold = -25  # Only BULK (-100) and LOW (-50) go to backfill
                 # A custom priority of -10 would stay on primary
```

### Set a custom suffix

You can customize the backfill stream name suffix:

```toml
[server.priority_lanes]
enabled = true
backfill_suffix = "migration"  # Streams become "customer:migration" etc.
```

---

## What ordering does Protean guarantee?

Priority lanes provide the following ordering guarantees:

### Each lane keeps FIFO order

Within each lane (primary or backfill), messages are processed in strict FIFO
order. If events A and B are both on the primary lane and A was published first,
A will be processed before B. The same holds for the backfill lane.

### Cross-lane ordering is not guaranteed

Suppose event A is on the primary lane and event B is on the backfill lane.
Their relative processing order depends on when each lane is drained. The
primary lane is always drained first, so in practice primary events are
processed before backfill events. A backfill batch may already be in progress
when a new primary event arrives. In that case, the Engine reads the primary
event after the current backfill batch completes.

### The outbox publishes messages by priority

Within the outbox table itself, messages are fetched in descending priority
order. This means `CRITICAL` (100) messages are published to the broker before
`HIGH` (50) messages, which are published before `NORMAL` (0) messages. Within
one priority, the outbox fetches messages in the order their rows were written.
One aggregate's events therefore come in commit order. Within one commit, each
aggregate's events come in the order that aggregate raised them, one aggregate
after another. This ordering applies within a single outbox polling cycle.

A retried row, a second worker, or host clocks that disagree can still publish
events out of that order. For example, a worker may crash while holding rows 1
to 5. Another worker can claim those rows only after their lock expires, and
meanwhile rows 6 to 10 are published first. See [Outbox
ordering](../../reference/guarantees.md#outbox-ordering) for the full list.

A category partitioned with
[`sequential_by`](../../reference/server/sequential-by.md#how-the-outbox-keeps-a-key-in-order)
is the exception. The outbox holds a key's later rows until its earlier rows in
the same lane publish. Retries and extra workers therefore do not reorder a key
within a lane. A key's primary and backfill rows are held separately, and
neither lane waits for the other.

### What this means in practice

For most use cases, the key guarantee is simple: **production events are never
blocked by migration events.** The Engine always checks the primary stream
before it reads backfill. On the Redis broker, an idle Engine waits on both
streams at once, so a production event never waits behind an empty backfill
read.

---

## When should you use priority lanes?

Priority lanes are designed for scenarios where bulk or background work could
starve production traffic:

- **Data migrations**: Backfilling a new field across thousands of existing
  records. Wrap the migration loop in `processing_priority(Priority.LOW)`.

- **Bulk imports**: Importing customer data from a CSV or external system.
  Use `Priority.BULK` to ensure import events do not delay real-time
  operations.

- **Re-indexing by commands**: Re-sending commands for historical records so
  their handlers rebuild derived state. Tag those commands with
  `Priority.LOW`. `domain.rebuild_projection()` reads the event store directly
  and does not go through the broker, so priority lanes do not apply to it.

- **Backfill jobs**: Enriching existing records with data from an external
  API. These jobs can run for hours without lowering production throughput.

- **Scheduled batch processing**: End-of-day reconciliation, report generation,
  or periodic cleanup tasks that produce a burst of events.

---

## When NOT to Use

Priority lanes are not appropriate in every situation:

- **Events requiring strict global ordering**: Your domain may require that
  event A is always processed before event B regardless of their priority. In
  that case, do not use priority lanes. Priority lanes intentionally process
  primary events before backfill events that arrived first.

- **Event-sourced aggregate reconstruction**: Priority lanes apply only to the
  outbox-to-broker pipeline (stream subscriptions). Event-sourced aggregates
  reconstruct state by reading directly from the event store. They do not read
  from Redis Streams, so priority lanes do not apply to them.

- **Low-volume systems**: If your system processes a small number of events and
  migrations complete in seconds, priority lanes add unnecessary complexity.
  The feature is designed for systems where batch operations produce enough
  events to create visible latency in production processing.

- **Single-stream idempotency assumptions**: Your event handlers may rely on
  processing all events for a stream category in a single FIFO order (for
  example, to detect duplicates by position or to use Redis stream message IDs
  for ordering). Splitting into two streams will break that assumption. Message
  IDs are no longer globally ordered across the primary and backfill streams.

---

## Where to go next

- [Using Priority Lanes](../../guides/server/using-priority-lanes.md):
  How to enable and configure priority lanes.
- [Running Data Migrations with Priority Lanes](../../patterns/running-data-migrations-with-priority-lanes.md):
  Pattern for running data migrations without blocking production.
- [Outbox Pattern](./outbox.md): How the outbox ensures reliable
  message delivery.
- [Subscription Types](../../reference/server/subscription-types.md): How `StreamSubscription`
  consumes messages from Redis Streams.
- [Configuration](../../reference/server/configuration.md): Full configuration reference for
  subscriptions and the server.
