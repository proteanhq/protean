# Using Priority Lanes

Here is how to enable priority lanes and route particular workloads through
the backfill lane, so they do not interfere with production event
processing.

For the conceptual overview (how priority lanes work, ordering guarantees, and
when to use them) see [Priority
Lanes](../../concepts/async-processing/priority-lanes.md).

---

## Enable Priority Lanes

Add the `[server.priority_lanes]` section to your domain configuration:

```toml
# domain.toml
command_processing = "sync"

[server]
default_subscription_type = "stream"

[server.priority_lanes]
enabled = true
threshold = 0              # Priority < 0 goes to backfill
backfill_suffix = "backfill"
```

The command handlers run in the calling process (`command_processing =
"sync"`). With `default_subscription_type = "stream"`, the engine reads
commands from a broker stream that asynchronous commands never reach, so an
asynchronous command is stored and never handled.

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
       primary='crm::customer', backfill='crm::customer:backfill'
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
--8<-- "guides/server/using-priority-lanes/001.py:import"
--8<-- "guides/server/using-priority-lanes/001.py:context_manager"
```

Use `Priority.LOW` for most batch jobs. Use `Priority.BULK` for the lowest
priority work, such as mass imports. A projection rebuild with
`domain.rebuild_projection()` reads the event store directly and does not go
through the broker, so no priority applies to it.

### Explicit Parameter

Pass `priority` directly to a single `domain.process()` call:

```python
--8<-- "guides/server/using-priority-lanes/001.py:import"
--8<-- "guides/server/using-priority-lanes/001.py:explicit"
```

The explicit parameter takes precedence over any active context manager.

---

## Verify That Routing Works

### Check Consumer Group Lag

Stream names are `<domain>::<stream category>`, so the `Customer` stream of
the `CRM` domain is `crm::customer`. Watch the consumer groups on both
streams:

```bash
# Primary -- lag should stay near 0
redis-cli XINFO GROUPS crm::customer

# Backfill -- lag grows during the batch, then drains
redis-cli XINFO GROUPS crm::customer:backfill
```

`lag` (Redis 7 and later) is the number of entries the group has not read
yet. `pending` is the number it has read but not acknowledged. When both are
`0` for every group on the backfill stream, every event published to it has
been handled. `XLEN` does not tell you this: it counts every entry still
stored in the stream, read or not.

Zero lag does not mean the batch succeeded. Outbox records may still be
waiting to be published (see below), and a message whose handler failed is
acknowledged once it moves to the dead-letter stream
(`crm::customer:backfill:dlq`). Treat the batch as done only when the outbox
has no unpublished records and the dead-letter stream holds no batch events.

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
redis-cli XINFO GROUPS crm::customer:backfill
```

If no groups are listed, restart the Engine. It creates the backfill consumer
group during initialization.

### Deserialization errors on the backfill stream

Events may have been produced by a different version of the domain model. Check
the dead letter queue:

```bash
redis-cli XRANGE crm::customer:backfill:dlq - + COUNT 5
```

If the events have an outdated schema, write an
[upcaster](../consume-state/event-upcasting.md) to transform them to the
current schema.

---

## Where to go next

- [Priority Lanes](../../concepts/async-processing/priority-lanes.md): How
  priority lanes work, configuration options, and ordering guarantees.
- [Running Data Migrations with Priority Lanes](../../patterns/running-data-migrations-with-priority-lanes.md):
  A complete worked example of migrating data without blocking production.
- [Outbox Pattern](../../concepts/async-processing/outbox.md): How the outbox
  ensures reliable message delivery.
- [Observability](../../reference/server/observability.md): The Observatory
  dashboard for monitoring message flow.
