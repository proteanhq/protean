# Running Data Migrations with Priority Lanes

## The Problem

Every growing system eventually needs to backfill data: adding a new field to
existing records, enriching records from an external source, or recalculating
derived values after a business rule change. In a CQRS system with asynchronous
event processing, these migrations are not simple database updates. Each record
change produces domain events that flow through the same pipeline as production
traffic.

Consider this scenario: your e-commerce platform has been running for months.
You need to backfill a `loyalty_tier` field onto 500,000 existing customer
records. The migration script loads each customer, sets the tier, and saves,
producing 500,000 `LoyaltyTierAssigned` events.

Those events flood the same Redis Stream that handles real-time customer
registrations, order placements, and payment confirmations. The Engine processes
them in FIFO order, so production events are now stuck behind half a million
migration events. A customer who just placed an order waits minutes (or longer)
for their confirmation because the projector is busy processing backfill events.

```
Without priority lanes:

  Production event ──┐
  Migration event  ──┤
  Migration event  ──┤──► Single Redis Stream ──► [Processed in FIFO order]
  Production event ──┤      "identity::customer"   Migration events block
  Migration event  ──┘                              production traffic
```

You could pause the migration, wait for production to catch up, and resume in
small batches, but this is manual, error-prone, and slow. You could run the
migration at 3 AM, but that only works if your traffic has a quiet window.

The root issue is that **migration events and production events are treated
identically**, even though they have fundamentally different urgency profiles.

---

## The Pattern

Route migration events to a separate backfill lane that the Engine processes
only when production work is idle. This way, migrations run continuously at
full speed without ever delaying a production event.

Tag migration commands with a low priority, and let the infrastructure route
them accordingly.

```
With priority lanes:

  Production events ──► Outbox(priority=0)  ──► "identity::customer"           ──► [Drained first]
                                                                                     Non-blocking read
                                                                                          │
  Migration events  ──► Outbox(priority=-50) ──► "identity::customer:backfill" ──► [Drained when idle]
                                                                                     Only when primary empty
```

The migration script does not need to know about streams, consumer groups, or
the Engine's scheduling strategy. It only needs to mark its work as low
priority. The framework handles the rest.

---

## How Protean Supports It

Protean provides this pattern through three mechanisms:

### 1. Processing Priority Context

The `processing_priority()` context manager tags all commands processed within
a block with a specific priority. Events produced by those commands inherit the
priority in their outbox records:

```python
# fragment
from protean.utils.processing import processing_priority, Priority

with processing_priority(Priority.LOW):
    domain.process(SomeCommand(...))  # Events get priority=-50
```

### 2. OutboxProcessor Routing

The OutboxProcessor checks each message's priority against a configurable
threshold (default: 0). Messages below the threshold are published to the
backfill stream (here `identity::customer:backfill`) instead of the primary
stream (`identity::customer`).

### 3. StreamSubscription Draining

The Engine's StreamSubscription reads from the primary stream first (non-blocking).
Only when the primary stream is empty does it make one blocking read that waits
on both streams (capped at 1 second). Production events are never blocked by
backfill events.

No handler changes are needed. The same projector processes events identically
regardless of which lane they arrived on.

For the full configuration and priority level reference, see
[Priority Lanes](../concepts/async-processing/priority-lanes.md).

---

## Applying the Pattern

### A Complete Migration Script

The script works on this `Customer` aggregate. Priority lanes are switched on
in the domain's configuration:

```python
--8<-- "patterns/running-data-migrations-with-priority-lanes/001.py:model"
```

Here is a migration script that backfills a `loyalty_tier` field on existing
customer records. The key is wrapping all `domain.process()` calls inside a
`processing_priority(Priority.LOW)` context manager. The script reads
customers one page at a time, because a query returns at most 100 records
unless you set a limit.

```python
--8<-- "patterns/running-data-migrations-with-priority-lanes/001.py:script"
```

### Running the Script

Run a dry run first to verify the migration logic:

```bash
python migrate_loyalty_tiers.py --dry-run
```

Then run the migration while production is running:

```bash
python migrate_loyalty_tiers.py
```

### Key Points

1. **`processing_priority(Priority.LOW)`** wraps all `domain.process()` calls.
   Every event produced inside the block is tagged with `priority=-50` in the
   outbox record.

2. **The OutboxProcessor** reads these outbox records and checks
   `message.priority < threshold` (default threshold is 0). Since -50 < 0, the
   events are published to `identity::customer:backfill` instead of
   `identity::customer`.

3. **The StreamSubscription** first does a non-blocking read on
   `identity::customer` (primary). Only when the primary stream is empty does
   it read `identity::customer:backfill`, in one blocking read that waits on
   both streams. Production events are always processed first.

4. **No handler changes needed**: A projector processes events identically
   regardless of which lane they arrived on.

### Monitoring During the Migration

Watch the consumer groups on both streams to track progress:

```bash
# Primary -- lag should stay near 0 during migration
redis-cli XINFO GROUPS identity::customer

# Backfill -- lag grows during migration, then drains
redis-cli XINFO GROUPS identity::customer:backfill
```

`lag` (Redis 7 and later) is the number of entries the group has not read
yet. `pending` is the number it has read but not acknowledged. When both are
`0` for every group on the backfill stream, every event published to it has
been handled. `XLEN` does not tell you this: it counts every entry still
stored in the stream, read or not.

Zero lag does not mean the migration succeeded. Outbox records may still be
waiting to be published, and a message whose handler failed is acknowledged
once it moves to the dead-letter stream (`identity::customer:backfill:dlq`).
Treat the migration as done only when the outbox has no unpublished records
and the dead-letter stream holds no migration events.

If you are running the [Observatory](../reference/server/observability.md),
`outbox.published` traces show each migration event as it is published. Their
`stream` field is the stream category (`identity::customer`), not the backfill
stream, so use `XINFO GROUPS` above to confirm which lane the events went to.

---

## Anti-Patterns

### Running migrations directly against the database

```python
# fragment
# BAD: Bypasses the domain model entirely
db.execute("UPDATE customers SET loyalty_tier = 'gold' WHERE ...")
```

This skips domain events, projections, and any downstream side effects. The
read model will not be updated. Event-sourced aggregates will have no record
of the change. Direct database writes work for truly schema-only changes, but
any migration that changes domain state should go through `domain.process()`.

### Running migrations during a maintenance window "because it's simpler"

Taking the system offline to run a migration avoids the priority lane problem
but creates a different one: downtime. For systems that need to stay available,
priority lanes let you run migrations during normal operation. The added
complexity is minimal, a single `with processing_priority(Priority.LOW):` wrapper.

### Parallelizing migration scripts without coordination

Running multiple migration script processes simultaneously can cause contention
on the same aggregates. If two processes try to update the same customer
concurrently, one will fail with an optimistic concurrency error. Run migration
scripts sequentially, or partition the data so each process handles a disjoint
subset.

---

## When Not to Use

- **Small datasets**: If the migration processes fewer events than the Engine
  can handle in a few seconds, priority lanes add no value. run the script
  and let the events flow through the normal pipeline.

- **Schema-only migrations**: If you are adding a column, changing an index, or
  altering table structure without changing domain state, use database migration
  tools directly. Priority lanes are for domain-level data changes that produce
  events.

- **Migrations requiring strict ordering with production**: If migration events
  must be interleaved with production events in a specific order, priority lanes
  will break that ordering. The two-lane system intentionally allows production
  events to jump ahead of migration events.

---

## Summary

| Aspect | Without Priority Lanes | With Priority Lanes |
|--------|----------------------|-------------------|
| **Migration events** | Share the production stream | Routed to a separate backfill stream |
| **Production latency** | Degrades proportionally to migration volume | Unaffected |
| **Handler changes** | None | None |
| **Script changes** | None | Wrap in `processing_priority(Priority.LOW)` |
| **Monitoring** | One stream to watch | Two streams to watch |
| **Ordering** | Global FIFO | Per-lane FIFO; production events processed first |

---

!!! tip "Related reading"
    **Guide:** [Using Priority Lanes](../guides/server/using-priority-lanes.md): How to enable and configure priority lanes.

    **Concept:** [Priority Lanes](../concepts/async-processing/priority-lanes.md): How priority lanes work, configuration options, and ordering guarantees.

    **Related patterns:**

    - [Event Versioning and Evolution](event-versioning-and-evolution.md): If migration events produce events with an outdated schema, upcasters can transform them.
    - [One Aggregate Per Transaction](one-aggregate-per-transaction.md): Each migration command modifies one aggregate per transaction, consistent with this pattern.
