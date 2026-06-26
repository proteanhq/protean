# Using the Outbox

The outbox pattern guarantees that domain events are published to your
message broker if — and only if — the transaction that produced them
committed. Without it, a broker outage after a successful database
commit would silently drop the event; with it, the event stays in the
outbox table until the broker can accept it.

This guide walks through enabling the outbox, verifying it's working,
and tuning its retry and cleanup behavior. For the end-to-end sequence,
lifecycle states, and rationale, see
[Outbox Pattern](../../concepts/async-processing/outbox.md).

## Enable the outbox

The outbox is activated by setting the default subscription type to
`stream`. The `OutboxProcessor` then starts automatically inside the
Engine:

```toml
# domain.toml
[server]
default_subscription_type = "stream"

[outbox]
broker = "default"          # Which configured broker to publish to
messages_per_tick = 10      # Batch size per cycle
tick_interval = 1           # Seconds between cycles

[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"
```

You also need a database provider that can hold the outbox table — any
relational provider works (PostgreSQL, SQLite, MSSQL). The outbox is not
compatible with the `memory` provider for production use.

!!! note "Event store subscriptions don't use the outbox"
    The outbox pattern is for `stream` subscriptions. If your server
    runs on `event_store` subscriptions, events flow through the event
    store's own durable log instead. Setting
    `default_subscription_type = "event_store"` with `enable_outbox = true`
    is a configuration error and fails fast at startup.

---

## Create the outbox table

Before the server starts, create the outbox table alongside your other
tables:

```bash
# Creates all tables (aggregates, entities, projections, outbox)
$ protean db setup --domain=my_domain
```

If you're adding the outbox to an existing application, create only the
outbox table without touching the rest of the schema:

```bash
$ protean db setup-outbox --domain=my_domain
```

Multiple database providers produce one outbox per provider — each
provider owns its own outbox table and its own `OutboxProcessor`.

The outbox table ships with the indexes the processor needs, created
automatically by the commands above: a partial index on the active set
(`status`, `priority`) for the polling query, a unique index on `message_id`
for idempotency, and an index on `correlation_id`. These are declared as
[index declarations](../domain-definition/indexes.md) on the framework's
`Outbox` aggregate, so on a large, long-running outbox the polling and
cleanup paths stay fast without any manual tuning.

---

## Verify the outbox is running

Start the server:

```bash
$ protean server --domain=my_domain
```

Look for the processor boot line in the logs:

```
DEBUG: Creating outbox processor: outbox-processor-default-to-default
```

Then raise an event through your normal domain flow. You'll see
messages move through the outbox lifecycle:

```
DEBUG: Found 1 messages to process
DEBUG: Published to myapp::order: msg-abc-123
DEBUG: Outbox batch: 1/1 processed
```

If no batch processing logs appear, check that:

- The outbox table exists (run `protean db setup-outbox` again — it's
  idempotent).
- A broker is configured and reachable.
- The aggregate that raised the event was persisted through a
  repository (the outbox row is written in the same transaction as the
  aggregate).

---

## Configure retries

Failed publish attempts retry with exponential backoff and jitter.
Tune the defaults when a broker is slower to recover than the default
schedule, or when some messages are important enough to justify more
attempts:

```toml
[outbox.retry]
max_attempts = 3           # Give up after this many failed publishes
base_delay_seconds = 60    # First retry after 60s
max_backoff_seconds = 3600 # Cap exponential backoff at 1 hour
backoff_multiplier = 2     # Double the delay each retry
jitter = true              # Randomize each delay
jitter_factor = 0.25       # By ±25%
```

With defaults (3 attempts, 60s base, 2× multiplier), a failed message
is retried at roughly 60s, 120s, and 240s before being marked as
`ABANDONED`.

Keep `jitter = true` in production — it prevents a broker recovery
from triggering a thundering herd of simultaneous retries across
workers.

---

## Configure cleanup

The outbox table grows forever unless you enable cleanup. The processor
removes successfully published and abandoned messages on a schedule:

```toml
[outbox.cleanup]
published_retention_hours = 168   # Keep published messages 7 days
abandoned_retention_hours = 720   # Keep abandoned messages 30 days
cleanup_interval_ticks = 86400    # Run cleanup roughly daily
```

Tune these with two trade-offs in mind:

- **Shorter `published_retention_hours`** = less storage, less audit
  trail. 24 hours is fine if you don't need cross-system replay.
- **Longer `abandoned_retention_hours`** = more time to investigate
  chronic failures before the evidence disappears. 30+ days is
  reasonable while a system is stabilizing.

---

## Reduce idle polling

By default the processor polls every `tick_interval` seconds whether or not
there is work, which keeps a quiet outbox under constant low-level load. Set
`max_tick_interval` to let an idle processor back off:

```toml
[outbox]
tick_interval = 1          # Base interval between polls
max_tick_interval = 30     # Back off to at most 30s when idle
```

Each empty poll doubles the wait (1s, 2s, 4s, and so on up to 30s); the first
non-empty batch resets it to the base `tick_interval`. This trims wasted
queries on a mostly idle deployment without adding latency under load, since a
pending message snaps polling back to full speed on the next tick.

Backoff is disabled by default: omit `max_tick_interval` (or set it to a value
at or below `tick_interval`) and the processor polls at a constant
`tick_interval`. Set it above `tick_interval` to enable the backoff.

---

## Investigate abandoned messages

Messages that exhaust `max_attempts` move to the `ABANDONED` state and
stop retrying. They do **not** route to a DLQ — the outbox table itself
is durable storage.

There is no dedicated CLI for inspecting abandoned outbox rows today.
Use the runtime options available:

**Observatory** — the `/api/outbox` endpoint reports per-domain outbox
status including counts by state. See
[Observatory Dashboard](../../reference/cli/runtime/observatory.md#endpoints).

**A shell session** — query the outbox repository directly:

```python
from protean.globals import current_domain
from protean.utils.outbox import OutboxStatus

with domain.domain_context():
    repo = current_domain.repository_for("Outbox")
    abandoned = repo.query.filter(status=OutboxStatus.ABANDONED.value).all()
    for msg in abandoned.items:
        print(msg.id, msg.stream_name, msg.last_error)
```

**The database** — abandoned rows can be inspected, re-queued, or
deleted with regular SQL. Re-queue a row by setting its status back to
`pending` and clearing `retry_count`:

```sql
UPDATE outbox
SET status = 'pending', retry_count = 0, locked_by = NULL, locked_until = NULL
WHERE id = '<message_id>';
```

The next `OutboxProcessor` tick picks it up.

---

## Run with multiple workers

When the server runs with `--workers N`, every worker runs its own
`OutboxProcessor`. They don't collide — messages are claimed atomically
by an `UPDATE ... WHERE status='pending'` that only one worker can win
per row. If a worker crashes mid-publish, its lock expires after 5
minutes and the message becomes eligible again.

Scale the outbox throughput by increasing `messages_per_tick` or the
worker count, not by lowering `tick_interval` — smaller ticks just
increase database load without increasing throughput.

See [Multi-Worker Mode](../../reference/server/supervisor.md) for the
supervisor configuration and
[Outbox Pattern: Multi-Worker Support](../../concepts/async-processing/outbox.md#multi-worker-support)
for the locking details.

---

## Dispatch to external brokers

When events marked `published=True` need to reach partner systems or
other bounded contexts, configure additional brokers in
`[outbox].external_brokers`. Each published event creates one outbox
row per broker, and each row is processed independently.

The full workflow — including envelope stripping for external
consumers — is covered in
[Dispatching Published Events to External Brokers](./external-event-dispatch.md).

---

## Common errors

| Condition | Behavior |
|---|---|
| `ConfigurationError` at startup: "`enable_outbox` is True but subscription type is `event_store`" | You have the legacy `enable_outbox = true` flag set, but `default_subscription_type` is `event_store`. The outbox publishes to brokers; event-store subscriptions never read from brokers. Remove `enable_outbox` or switch the subscription type to `stream`. |
| No rows appear in the outbox after raising events | The aggregate was likely not persisted through a repository. The outbox write happens in the same transaction as the aggregate `add()` — direct model writes bypass it. |
| Messages stuck in `PROCESSING` long after worker restart | A worker crashed while holding the lock. The default 5-minute `locked_until` expiry releases the row; no manual cleanup is required. |
| `ABANDONED` rows accumulating | A handler or broker endpoint is failing persistently. Inspect `last_error` on the row — the common causes are schema drift, missing broker streams, or downstream authentication failures. |

---

## See also

- [Outbox Pattern](../../concepts/async-processing/outbox.md) — Sequence diagram, lifecycle states, retry mechanics, locking details.
- [Dispatching Published Events to External Brokers](./external-event-dispatch.md) — Routing events to partner systems.
- [Publishing Events to External Brokers](../../patterns/publishing-events-to-external-brokers.md) — When and why to use external dispatch.
- [Subscription Types Reference](../../reference/server/subscription-types.md) — How StreamSubscription consumes outbox-published messages.
- [Dead Letter Queues](./dead-letter-queues.md) — Recovery for consumer-side failures (outbox is publisher-side).
- [`protean db setup-outbox` Reference](../../reference/cli/data/database.md#protean-db-setup-outbox) — CLI details.
