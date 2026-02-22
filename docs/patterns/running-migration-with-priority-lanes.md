# Running Migrations Without Blocking Production

This guide walks through using priority lanes to run a data migration while
keeping production event processing fully responsive. By the end, you will have
a working migration script that routes its events to the backfill lane and
verifies that production traffic is unaffected.

---

## Prerequisites

### 1. Enable Priority Lanes in domain.toml

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

### 2. Restart the Engine

After changing the configuration, restart the Engine so it picks up the new
priority lanes settings. The Engine will create consumer groups for both the
primary and backfill streams on startup:

```bash
protean server --domain=src/my_domain
```

You should see log output confirming the backfill consumer group was created:

```
DEBUG: Initialized priority lanes for CustomerProjector:
       primary='customer', backfill='customer:backfill'
```

### 3. Verify Infrastructure

Ensure your infrastructure is running:

- PostgreSQL (outbox table and aggregate storage)
- Redis (broker for Redis Streams)
- The Engine process for your domain

---

## Writing the Migration Script

Here is a complete migration script that backfills a `loyalty_tier` field on
existing customer records. The key is wrapping all `domain.process()` calls
inside a `processing_priority(Priority.LOW)` context manager.

```python
#!/usr/bin/env python
"""migrate_loyalty_tiers.py

Backfill loyalty_tier on all existing customers based on their
total lifetime spend. Uses Priority.LOW so that events produced
by this script are routed to the backfill lane and do not block
production event processing.
"""

import logging
import sys
import time

from my_app.identity.domain import identity as domain
from my_app.identity.customer import Customer, UpdateCustomerTier
from protean.utils.processing import processing_priority, Priority

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Tier thresholds based on lifetime spend
TIER_THRESHOLDS = [
    (10000, "platinum"),
    (5000, "gold"),
    (1000, "silver"),
    (0, "bronze"),
]


def determine_tier(lifetime_spend: float) -> str:
    for threshold, tier in TIER_THRESHOLDS:
        if lifetime_spend >= threshold:
            return tier
    return "bronze"


def run_migration(batch_size: int = 100, dry_run: bool = False):
    domain.init()

    with domain.domain_context():
        # Load all customer IDs that need migration
        repo = domain.repository_for(Customer)
        customers = repo._dao.query.all()

        total = len(customers)
        logger.info(f"Found {total} customers to migrate")

        if dry_run:
            logger.info("Dry run mode -- no changes will be made")
            return

        migrated = 0
        errors = 0
        start_time = time.time()

        # Wrap the entire migration in a LOW priority context.
        # Every command processed inside this block will produce
        # events tagged with priority=-50, which the OutboxProcessor
        # will route to the "customer:backfill" stream.
        with processing_priority(Priority.LOW):
            for i, customer in enumerate(customers):
                try:
                    tier = determine_tier(customer.lifetime_spend)

                    domain.process(UpdateCustomerTier(
                        customer_id=customer.id,
                        loyalty_tier=tier,
                    ))

                    migrated += 1

                except Exception as exc:
                    logger.error(
                        f"Failed to migrate customer {customer.id}: {exc}"
                    )
                    errors += 1

                # Log progress every batch_size records
                if (i + 1) % batch_size == 0:
                    elapsed = time.time() - start_time
                    rate = (i + 1) / elapsed if elapsed > 0 else 0
                    logger.info(
                        f"Progress: {i + 1}/{total} "
                        f"({rate:.0f} records/sec, "
                        f"{migrated} migrated, {errors} errors)"
                    )

        elapsed = time.time() - start_time
        logger.info(
            f"Migration complete: {migrated}/{total} migrated, "
            f"{errors} errors, {elapsed:.1f}s elapsed"
        )


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run_migration(dry_run=dry_run)
```

### Key points in the script

1. **`processing_priority(Priority.LOW)`** wraps all `domain.process()` calls.
   Every event produced inside the block is tagged with `priority=-50` in the
   outbox record.

2. **The OutboxProcessor** reads these outbox records and checks
   `message.priority < threshold` (default threshold is 0). Since -50 < 0, the
   events are published to `customer:backfill` instead of `customer`.

3. **The StreamSubscription** for `CustomerProjector` first does a non-blocking
   read on `customer` (primary). Only when the primary stream is empty does it
   fall back to `customer:backfill`. Production events are always processed
   first.

4. **No handler changes needed.** The `CustomerProjector` processes events
   identically regardless of which lane they arrived on.

---

## Running the Migration

### Step 1: Run a Dry Run

Verify the migration logic without making any changes:

```bash
python migrate_loyalty_tiers.py --dry-run
```

```
2026-02-20 10:00:00 INFO Found 487,231 customers to migrate
2026-02-20 10:00:00 INFO Dry run mode -- no changes will be made
```

### Step 2: Run the Migration

Start the migration while production is running:

```bash
python migrate_loyalty_tiers.py
```

```
2026-02-20 10:01:00 INFO Found 487,231 customers to migrate
2026-02-20 10:01:05 INFO Progress: 100/487231 (20 records/sec, 100 migrated, 0 errors)
2026-02-20 10:01:10 INFO Progress: 200/487231 (20 records/sec, 200 migrated, 0 errors)
...
2026-02-20 16:45:30 INFO Migration complete: 487231/487231 migrated, 0 errors, 24270.0s elapsed
```

### Step 3: Verify Completion

After the migration finishes, the backfill stream will drain naturally as the
Engine processes the remaining events. You can monitor the backfill stream
length using Redis CLI:

```bash
redis-cli XLEN customer:backfill
```

When this returns `0`, all backfill events have been processed.

---

## Monitoring

### Observatory Dashboard

If you are running the [Observatory](../reference/server/observability.md), the live message
flow dashboard shows events flowing through both lanes. Look for:

- **`outbox.published` traces** with `stream=customer` (production) and
  `stream=customer:backfill` (migration). Both should appear during the
  migration.
- **`handler.completed` traces** for your projector. These should show a
  healthy mix of production and backfill processing, with production events
  completing promptly.

### Redis Stream Monitoring

Check the pending entry list (PEL) for both streams to see how much work is
queued:

```bash
# Primary stream -- should stay near zero during migration
redis-cli XLEN customer

# Backfill stream -- will grow during migration, drain after
redis-cli XLEN customer:backfill

# Check consumer group lag for primary
redis-cli XINFO GROUPS customer

# Check consumer group lag for backfill
redis-cli XINFO GROUPS customer:backfill
```

### Engine Logs

The Engine logs message processing at `INFO` level. During a migration, you
should see interleaved processing:

```
INFO: [CustomerProjector] Processing CustomerRegistered (ID: abc12345...) -- acked
INFO: [CustomerProjector] Processing CustomerUpdated (ID: mig00001...) -- acked
INFO: [CustomerProjector] Processing CustomerUpdated (ID: mig00002...) -- acked
INFO: [CustomerProjector] Processing CustomerRegistered (ID: def67890...) -- acked
INFO: [CustomerProjector] Processing CustomerUpdated (ID: mig00003...) -- acked
```

Notice how production events (`CustomerRegistered`) are interspersed with
migration events (`CustomerUpdated`). The production events are processed
promptly because the Engine drains the primary lane first.

---

## Verifying Production Traffic

To confirm that production traffic is not affected by the migration:

### 1. Check Production Event Latency

Measure the time between when a production event is created (outbox insert) and
when it is processed (handler completion). This should remain consistent during
the migration.

If you have the Observatory running, look at the `duration_ms` field in
`handler.completed` traces for production events. Compare the values during
migration with baseline values from before the migration started.

### 2. Send a Test Request

While the migration is running, send a production request and verify it is
processed promptly:

```bash
# Register a new customer while migration is in progress
curl -X POST http://localhost:8000/customers \
  -H "Content-Type: application/json" \
  -d '{"name": "Test User", "email": "test@example.com"}'

# Check that the projection is updated within seconds
curl http://localhost:8000/customers/<customer_id>
```

The new customer should appear in the read model within a few seconds, even if
the backfill stream has thousands of pending events.

### 3. Monitor Primary Stream Length

The primary stream length should remain near zero during the migration. If it
grows, it means the Engine is not keeping up with production traffic -- but this
is unlikely since migration events are on the backfill stream.

```bash
# This should stay near 0
watch -n 1 "redis-cli XLEN customer"
```

---

## Troubleshooting

### Migration events are going to the primary stream

**Symptom**: All events appear on the primary stream, backfill stream is empty.

**Cause**: Priority lanes are not enabled, or the `processing_priority()`
context manager is not wrapping the `domain.process()` calls.

**Fix**:

1. Verify `domain.toml` has `[server.priority_lanes] enabled = true`.
2. Verify the Engine was restarted after the config change.
3. Verify the migration script wraps calls in
   `with processing_priority(Priority.LOW):`.
4. Check the outbox records -- the `priority` column should be `-50` for
   migration events:

```sql
SELECT message_id, priority, stream_name
FROM outbox
ORDER BY created_at DESC
LIMIT 10;
```

### Production events are delayed during migration

**Symptom**: Production events take several seconds to process instead of
sub-second.

**Cause**: The Engine may be processing a large backfill batch when a production
event arrives. The backfill blocking timeout is capped at 1 second, so the
maximum delay is 1 second plus the time to finish processing the current
backfill message.

**Fix**:

1. Reduce `messages_per_tick` so that backfill batches are smaller and the
   Engine re-checks the primary lane more frequently.
2. Verify the backfill read timeout is capped. Check the Engine logs for
   `Initialized priority lanes` messages confirming the configuration.

### Backfill stream grows but never drains

**Symptom**: The backfill stream keeps growing even after the migration script
finishes.

**Cause**: The Engine may not be running, or the consumer group on the backfill
stream was not created.

**Fix**:

1. Verify the Engine is running: `protean server --domain=src/my_domain`.
2. Check that the backfill consumer group exists:

```bash
redis-cli XINFO GROUPS customer:backfill
```

If no groups are listed, restart the Engine -- it creates the backfill consumer
group during initialization when priority lanes are enabled.

### Events fail with deserialization errors on the backfill stream

**Symptom**: Events are moved to `customer:backfill:dlq` instead of being
processed.

**Cause**: The events on the backfill stream may have been produced by a
different version of the domain model.

**Fix**:

1. Check the dead letter queue for error details:

```bash
redis-cli XRANGE customer:backfill:dlq - + COUNT 5
```

2. If the events have an outdated schema, consider writing an
   [upcaster](../guides/consume-state/event-upcasting.md) to transform them to the current schema.

### Migration script runs slowly

**Symptom**: The migration processes fewer records per second than expected.

**Cause**: Each `domain.process()` call involves a database transaction (loading
the aggregate, saving changes, inserting the outbox record). This is
intentionally synchronous to ensure consistency.

**Fix**:

1. Use `Priority.BULK` instead of `Priority.LOW` for maximum deprioritization.
   This does not affect migration speed, but ensures migration events are
   processed last.
2. Increase the outbox `messages_per_tick` to publish more events per cycle:

```toml
[outbox]
messages_per_tick = 100
tick_interval = 0
```

3. If the migration is I/O-bound (e.g., calling an external API for each
   record), consider batching the external calls outside the migration loop.

---

## Next Steps

- [Priority Lanes](../concepts/async-processing/priority-lanes.md) -- Conceptual guide explaining how
  priority lanes work and when to use them.
- [Outbox Pattern](../concepts/async-processing/outbox.md) -- How the outbox ensures reliable
  message delivery.
- [Observability](../reference/server/observability.md) -- The Observatory dashboard and
  trace events for monitoring.
