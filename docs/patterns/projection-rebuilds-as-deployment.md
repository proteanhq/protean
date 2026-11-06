# Treat Projection Rebuilds as a Deployment Strategy

## The Problem

In an event-sourced CQRS system, projections *can* be rebuilt from scratch. The
event store holds the complete history. When a projector replays those events,
it produces a fresh, correct read model. This is an operational advantage of
event sourcing: read models are disposable.

But teams rarely plan for this operationally.

Consider this scenario. A product team has been running an e-commerce platform
for six months. The `OrderSummary` projection was originally designed with a
`total` field. Now the business wants to display subtotal, tax, and shipping
separately:

```python
--8<-- "patterns/projection-rebuilds-as-deployment/001.py:before"
```

A developer trained by years of traditional database migrations usually writes
an `ALTER TABLE` first:

```sql
ALTER TABLE order_summary ADD COLUMN subtotal FLOAT;
ALTER TABLE order_summary ADD COLUMN tax FLOAT;
ALTER TABLE order_summary ADD COLUMN shipping FLOAT;
UPDATE order_summary SET subtotal = total, tax = 0, shipping = 0;
ALTER TABLE order_summary DROP COLUMN total;
```

This works, but it loses the defining advantage of event-sourced projections.
The `OrderPlaced` events in the event store already carry subtotal, tax, and
shipping data (or those values can be derived via upcasters). A rebuild would
produce the correct projection with no manual data fixups.

Teams use `ALTER TABLE` instead of a rebuild because they have not planned
rebuilds as a deployment operation. They do not know:

- **How long a rebuild takes**: Without measurement, a rebuild feels risky.
  Will it take 10 seconds or 10 hours?

- **How to serve traffic during the transition period**: While the old
  projection serves traffic, the new one needs to build in the background.
  Without a plan, the team faces a choice between downtime and stale data.

- **Whether upcasters are correct**: If old events have a different schema, the
  rebuild exercises the entire upcaster chain. If that chain has never been
  tested end-to-end, the rebuild is the worst time to discover its bugs.

- **How to run rebuilds without hurting production**: A rebuild of 500,000
  events reads the whole event store and rewrites the projection's table. It
  runs on the same databases as production traffic.

As a result, projections become as rigid as traditional database tables and
schema changes accumulate technical debt. The team can no longer change read
models freely, and that capability is what justified event sourcing.

---

## The Pattern

Treat projection rebuilds as **standard deployment operations**, not emergency
recovery procedures. Plan for them the way you plan for code deployments:
test in staging, monitor progress, and have a rollback strategy.

The core principles:

1. **Schema changes to projections should default to rebuild, not migrate.**
   When a projection's shape changes, deploy the new projector code, then
   rebuild the projection from events. Reserve `ALTER TABLE` for cases where
   a rebuild is genuinely impractical (billions of events, hours-long replay).

2. **Test rebuilds in staging first**: A rebuild exercises every upcaster in
   the chain, every projector handler, and every event version in the event
   store. Staging catches transformation errors before production.

3. **Use blue-green deployment for zero-downtime rebuilds**: Deploy a new
   projection class with a different `schema_name`, rebuild it in the
   background, then switch traffic once the rebuild completes.

4. **Monitor rebuild progress**: Use the `RebuildResult` dataclass to track
   events dispatched, events skipped, and errors. Treat a rebuild with
   skipped events as a warning that needs investigation.

5. **Run large rebuilds in their own process**: A rebuild reads the event
   store directly and does not go through the broker, so run it apart from the
   web workers and the Engine, against a new `schema_name`.

---

## Applying the Pattern

### Rebuild a projection after a schema change

The most common scenario: you add, rename, or remove fields on a projection.
After you deploy the updated projector, rebuild the projection.

The examples use this `Order` aggregate. Its `OrderPlaced` event already
carries the subtotal, tax, and shipping:

```python
--8<-- "patterns/projection-rebuilds-as-deployment/001.py:model"
```

**Before** the change, the projection looks like this:

```python
--8<-- "patterns/projection-rebuilds-as-deployment/001.py:before"
```

**After** the change, the projection splits the total into subtotal, tax, and
shipping:

```python
--8<-- "patterns/projection-rebuilds-as-deployment/002.py:after"
```

The projector is updated to populate the new fields:

```python
--8<-- "patterns/projection-rebuilds-as-deployment/002.py:projector"
```

After you deploy the code, rebuild the projection:

```bash
# CLI: rebuild a specific projection
protean projection rebuild --domain=my_app.ordering --projection=OrderSummary
```

Or from within a script:

```python
--8<-- "patterns/projection-rebuilds-as-deployment/002.py:rebuild"
```

!!! note "Rebuild is idempotent"
    `rebuild_projection()` truncates existing data before replaying. Running it
    twice produces the same result. There is no need to "undo" a failed
    rebuild. After you fix the cause, rebuild again.

---

### Rebuild with zero downtime using blue-green deployment

You cannot truncate and rebuild a projection that serves live traffic (e.g. an
API endpoint backed by `OrderSummary`) in place without leaving it empty or
incomplete for a period. With blue-green deployment, you rebuild a second
projection while the first one keeps serving reads.

**Step 1: Deploy a new projection class with a different `schema_name`.**

Keep the old `OrderSummary` running. Deploy a new class alongside it:

```python
--8<-- "patterns/projection-rebuilds-as-deployment/003.py:blue_green"
```

**Step 2: Deploy a projector for the new projection.**

```python
--8<-- "patterns/projection-rebuilds-as-deployment/003.py:v2_projector"
```

**Step 3: Rebuild the new projection in the background.**

```python
--8<-- "patterns/projection-rebuilds-as-deployment/003.py:rebuild_v2"
```

During the rebuild, the old `OrderSummary` continues serving traffic. The new
`order_summary_v2` table fills from the event store.

A rebuild empties the projection's table, reads the events, and then replays
them. The Engine may write a row for the same projection during the rebuild,
from an event the rebuild did not read. The rebuild can then erase that row.
That is why `protean projection rebuild` asks you to stop the server first.
Stop the Engine for the rebuild, or rebuild before the Engine starts with the
new projector. Reads do not go through the Engine, so the old projection keeps
answering queries. Its updates wait until the Engine starts again.

A rebuild does not move the new projector's subscription position. On its first
run of the new projector, the Engine starts at the beginning of the event
store. It delivers again the events that the rebuild already replayed. That is
why the `OrderPlaced` handler in Step 2 skips an order whose row already
exists. A handler that inserts without that check fails on the second delivery
with a uniqueness error.

**Step 4: Switch traffic.**

Once the rebuild completes and you have verified the data, update the API or
query layer to read from `OrderSummaryV2` instead of `OrderSummary`. This can
be a feature flag, a configuration change, or a code deployment.

```python
--8<-- "patterns/projection-rebuilds-as-deployment/003.py:api_before"
--8<-- "patterns/projection-rebuilds-as-deployment/003.py:api_after"
```

**Step 5: Clean up.**

After you confirm the switch is stable, remove the old `OrderSummary` class and
its projector. Then drop the `order_summary` table. Optionally, rename
`OrderSummaryV2` to `OrderSummary`. If you do, set
`schema_name="order_summary_v2"` explicitly to preserve the table name.

!!! warning "Keep both projectors running during the transition"
    While both projections are live, both projectors must be processing events.
    Once the rebuild finishes and the Engine runs again, new events must be
    applied to both the old and new projections. The Engine applies new events
    to both projections automatically, since both projectors are registered in
    the domain.

---

### Monitoring rebuild progress with RebuildResult

The `RebuildResult` dataclass provides all the information you need to assess
a rebuild:

```python
--8<-- "patterns/projection-rebuilds-as-deployment/003.py:monitor"
```

`events_skipped` is the critical metric. A skipped event means either:

- The event type could not be resolved (a deprecated event without an upcaster
  chain). This is expected if you have retired old event types.
- A projector handler raised an exception. This usually indicates a bug in the
  projector or an upcaster.

!!! tip "Log skipped events"
    The `rebuild_projection()` function logs each skipped event at `WARNING`
    level with the event type and global position. Review these logs after
    every rebuild to ensure no important events were silently dropped.

---

### Keeping a large rebuild away from production traffic

A rebuild does not go through the broker. `rebuild_projection()` reads events
from the event store and calls the projector's handlers in the same process.
It writes no outbox rows and publishes nothing to a broker stream, so it never
sits in the queue ahead of production events. For the same reason,
`processing_priority()` and priority lanes have no effect on a rebuild.

A large rebuild adds load to the event store and to the projection's database.
To keep it away from production:

- Run the rebuild in its own process, with `protean projection rebuild` or a
  script like the one above. Do not run it in a web worker.
- Rebuild into a new `schema_name` with the blue-green steps above, so readers
  never see a half-built table.
- Use `batch_size` to set how many events each round trip to the event store
  reads: `domain.rebuild_projection(OrderSummaryV2, batch_size=200)`. It does
  not lower the total. The rebuild still reads every event in the projector's
  stream categories and holds them in memory before it replays them.

Priority lanes help when a backfill sends commands through `domain.process()`.
Those commands raise events that go through the outbox and the broker. See
[Running Data Migrations with Priority
Lanes](running-data-migrations-with-priority-lanes.md).

---

## Anti-Patterns

### ALTER TABLE on a projection instead of rebuilding

```python
# fragment
# BAD: Treating a projection like a traditional database table
# This bypasses the event-driven architecture entirely.

import sqlalchemy as sa

engine = sa.create_engine("postgresql://localhost/myapp")
with engine.connect() as conn:
    conn.execute(sa.text(
        "ALTER TABLE order_summary ADD COLUMN subtotal FLOAT"
    ))
    conn.execute(sa.text(
        "UPDATE order_summary SET subtotal = total"
    ))
```

This creates several problems:

- The `UPDATE` statement uses guesswork to backfill `subtotal`. The events in
  the event store contain the actual values. A rebuild would produce correct
  data.
- The projection's Python class and its database schema are now out of sync.
  The `OrderSummary` class defines `subtotal` as a field, but the column was
  added manually rather than through Protean's schema management.
- Future developers will not know whether the projection's data matches the
  event history. Is the `subtotal` column populated from events, from a
  one-time migration script, or from a manual `UPDATE`? A future developer
  cannot tell which source populated the column.

**Instead:** After you update the projection class and projector, rebuild the
projection:

```bash
protean projection rebuild --domain=my_app.ordering --projection=OrderSummary
```

---

### Rebuilding in production without testing in staging first

```bash
# BAD: Rebuilding directly in production without prior validation
ssh production-server
protean projection rebuild --domain=my_app.ordering --projection=OrderSummary
```

A rebuild replays every event, starting from the first one in the event store.
If you added an event four months ago but never registered an upcaster for its
old schema, the rebuild will fail (or worse, silently skip events). A projector
handler can have a bug that only old event data triggers. The rebuild then
surfaces that bug in production.

**Instead:** Always rebuild in staging first. Staging should have a
representative event store (a snapshot or anonymized copy of production).
Verify that `events_skipped == 0` and that the projection data looks correct.

```bash
# On staging
protean projection rebuild --domain=my_app.ordering --projection=OrderSummary
# Verify result, check logs for skipped events, spot-check data

# Only then, on production
protean projection rebuild --domain=my_app.ordering --projection=OrderSummary
```

---

### Rebuilding without stopping or isolating the projection

```python
# fragment
# BAD: Rebuilding a projection that is actively serving queries
# Users see empty or partial results during the rebuild.

domain.init()
with domain.domain_context():
    # This truncates the table first, then replays events.
    # For 30 seconds, the API returns no results.
    domain.rebuild_projection(OrderSummary)
```

`rebuild_projection()` truncates all existing data before replaying events.
During the replay, the projection is incomplete. Any API endpoint reading from
it will return partial or empty results.

**Instead:** Use the blue-green deployment pattern described above. Rebuild a
newly deployed projection class with a different `schema_name` in the
background. When the rebuild completes, switch traffic to the new class.

---

### Skipping the rebuild after deploying new projector logic

If you deploy a projector that populates new fields but do not rebuild, only
*future* events produce projections with the new fields. Historical records
still have the old shape. The read model is inconsistent. Some rows have
`subtotal`, `tax`, and `shipping`; others do not.

**Instead:** Always rebuild after you deploy projector changes that change the
projection's schema or how it maps event data.

---

## Summary

| Aspect | Traditional Migration | Rebuild Strategy |
|--------|-----------------------|------------------|
| **Schema change** | `ALTER TABLE` + backfill script | Update projection class + `rebuild_projection()` |
| **Data correctness** | Manual backfill logic | Derived from authoritative event history |
| **Zero-downtime** | Complex migration scripts | Blue-green with `schema_name` |
| **Upcaster validation** | Not exercised | Every upcaster is tested end-to-end |
| **Rollback** | Reverse migration script | Redeploy old projection, rebuild again |
| **Production safety** | Test migration in staging | Test rebuild in staging |
| **Background execution** | Custom batching logic | Separate process, server stopped |
| **Progress monitoring** | Custom logging | `RebuildResult` stats |
| **CLI support** | Manual scripts | `protean projection rebuild` |
| **Idempotency** | Depends on script | Always, truncate and replay |

Projections are derived data. You can reconstruct them from the events in the
event store. Treat the rebuild as a deployment operation (test it, monitor it,
automate it), and you can change a projection's schema without a traditional
schema migration.

---

!!! tip "Related reading"
    **Patterns:**

    - [Event Versioning and Evolution](event-versioning-and-evolution.md): Evolve event schemas that projections consume.

    **Concepts:**

    - [Projections](../concepts/building-blocks/projections.md): What projections are.
    - [Projectors](../concepts/building-blocks/projectors.md): How projectors maintain projections.

    **Guides:**

    - [Projections](../guides/consume-state/projections.md): Defining projections.
    - [`protean projection rebuild`](../reference/cli/data/projection.md): CLI command for projection rebuilds.
    - [Event Upcasting](../guides/consume-state/event-upcasting.md): Transforming old event schemas during replay.
