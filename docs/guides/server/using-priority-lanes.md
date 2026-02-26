# Using Priority Lanes

This guide shows how to enable priority lanes and route specific workloads
through the backfill lane so they do not interfere with production event
processing.

For the conceptual overview — how priority lanes work, ordering guarantees, and
when to use them — see
[Priority Lanes](../../concepts/async-processing/priority-lanes.md).

---

## Enable Priority Lanes

Add the `[server.priority_lanes]` section to your domain configuration:

```toml
# domain.toml

[server]
default_subscription_type = "stream"

[server.priority_lanes]
enabled = true
threshold = 0              # Priority < 0 goes to backfill
backfill_suffix = "backfill"
```

If you use environment overlays, you can enable lanes only in production:

```toml
# Development: disabled by default
[server.priority_lanes]
enabled = false

# Production: enabled
[production.server.priority_lanes]
enabled = true
threshold = 0
```

After changing the configuration, restart the Engine so it picks up the new
settings. You should see log output confirming the backfill consumer group was
created:

```
DEBUG: Initialized priority lanes for CustomerProjector:
       primary='customer', backfill='customer:backfill'
```

---

## Route Commands to the Backfill Lane

There are two ways to tag commands with a lower priority. Both cause events
produced by those commands to be routed to the backfill stream instead of the
primary stream.

### Context Manager

Wrap a block of `domain.process()` calls in `processing_priority()`. Every
event produced inside the block is tagged with the specified priority:

```python
from protean.utils.processing import processing_priority, Priority

with processing_priority(Priority.LOW):
    for record in records_to_process:
        domain.process(UpdateCustomer(
            customer_id=record["id"],
            loyalty_tier=record["tier"],
        ))
```

Use `Priority.LOW` for most batch jobs. Use `Priority.BULK` for the lowest
priority work (mass imports, full re-projections).

### Explicit Parameter

Pass `priority` directly to a single `domain.process()` call:

```python
from protean.utils.processing import Priority

domain.process(
    ReindexProduct(product_id="SKU-001"),
    priority=Priority.BULK,
)
```

The explicit parameter takes precedence over any active context manager.

---

## Verify That Routing Works

### Check Stream Lengths

The primary stream length should stay near zero while backfill work is running.
The backfill stream will grow during the batch and drain after it completes:

```bash
# Primary -- should stay near 0
redis-cli XLEN customer

# Backfill -- grows during batch, drains after
redis-cli XLEN customer:backfill
```

### Check Outbox Records

Verify that events are tagged with the expected priority:

```sql
SELECT message_id, priority, stream_name
FROM outbox
ORDER BY created_at DESC
LIMIT 10;
```

Batch events should have a negative priority value (e.g., `-50` for
`Priority.LOW`).

---

## Troubleshooting

### Events are going to the primary stream instead of backfill

1. Verify `domain.toml` has `[server.priority_lanes] enabled = true`.
2. Verify the Engine was restarted after the config change.
3. Verify the script wraps calls in
   `with processing_priority(Priority.LOW):`.

### Backfill stream grows but never drains

1. Verify the Engine is running: `protean server --domain=src/my_domain`.
2. Check that the backfill consumer group exists:

```bash
redis-cli XINFO GROUPS customer:backfill
```

If no groups are listed, restart the Engine — it creates the backfill consumer
group during initialization.

### Deserialization errors on the backfill stream

Events may have been produced by a different version of the domain model. Check
the dead letter queue:

```bash
redis-cli XRANGE customer:backfill:dlq - + COUNT 5
```

If the events have an outdated schema, write an
[upcaster](../consume-state/event-upcasting.md) to transform them to the
current schema.

---

## Next Steps

- [Priority Lanes](../../concepts/async-processing/priority-lanes.md) — How
  priority lanes work, configuration options, and ordering guarantees.
- [Running Data Migrations with Priority Lanes](../../patterns/running-data-migrations-with-priority-lanes.md) —
  A complete worked example of migrating data without blocking production.
- [Outbox Pattern](../../concepts/async-processing/outbox.md) — How the outbox
  ensures reliable message delivery.
- [Observability](../../reference/server/observability.md) — The Observatory
  dashboard for monitoring message flow.
