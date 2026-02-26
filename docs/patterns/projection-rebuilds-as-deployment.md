# Treat Projection Rebuilds as a Deployment Strategy

## The Problem

In an event-sourced CQRS system, projections *can* be rebuilt from scratch --
the event store holds the complete history, and replaying those events through
a projector produces a fresh, correct read model. This is one of the great
operational advantages of event sourcing: read models are disposable.

But teams rarely plan for this operationally.

Consider this scenario. A product team has been running an e-commerce platform
for six months. The `OrderSummary` projection was originally designed with a
`total` field. Now the business wants to display subtotal, tax, and shipping
separately:

```python
@domain.projection
class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    total = Float()          # Original field
    status = String(max_length=20)
```

The developer's instinct -- trained by years of traditional database
migrations -- is to reach for `ALTER TABLE`:

```sql
ALTER TABLE order_summary ADD COLUMN subtotal FLOAT;
ALTER TABLE order_summary ADD COLUMN tax FLOAT;
ALTER TABLE order_summary ADD COLUMN shipping FLOAT;
UPDATE order_summary SET subtotal = total, tax = 0, shipping = 0;
ALTER TABLE order_summary DROP COLUMN total;
```

This works, but it throws away the defining advantage of event-sourced
projections. The `OrderPlaced` events in the event store already carry
subtotal, tax, and shipping data (or those values can be derived via
upcasters). A rebuild would produce the correct projection with no manual data
fixups.

The reason teams reach for `ALTER TABLE` instead of a rebuild is that they have
not treated rebuilds as a first-class deployment operation. They do not know:

- **How long a rebuild takes.** Without measurement, a rebuild feels risky.
  Will it take 10 seconds or 10 hours?

- **How to handle the transition period.** While the old projection serves
  traffic, the new one needs to build in the background. Without a plan, the
  team faces a choice between downtime and stale data.

- **Whether upcasters are correct.** If old events have a different schema, the
  rebuild exercises the entire upcaster chain. If that chain has never been
  tested end-to-end, the rebuild is the worst time to find out.

- **How to run rebuilds without blocking production.** A naive rebuild that
  replays 500,000 events through the same pipeline as production traffic will
  starve real-time consumers.

The result: projections become as rigid as traditional database tables, schema
changes accumulate technical debt, and the team loses the ability to freely
evolve read models -- the very capability that justified event sourcing in the
first place.

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

2. **Test rebuilds in staging first.** A rebuild exercises every upcaster in the
   chain, every projector handler, and every event version since the beginning
   of time. Staging catches transformation errors before production.

3. **Use blue-green deployment for zero-downtime rebuilds.** Deploy a new
   projection class with a different `schema_name`, rebuild it in the
   background, then switch traffic once the rebuild completes.

4. **Monitor rebuild progress.** Use the `RebuildResult` dataclass to track
   events dispatched, events skipped, and errors. Treat a rebuild with
   skipped events as a warning that needs investigation.

5. **Use priority lanes for background rebuilds.** Route rebuild work through
   the backfill lane so production event processing is not affected.

---

## Applying the Pattern

### Simple rebuild after a schema change

The most common scenario: you add, rename, or remove fields on a projection.
Deploy the updated projector, then rebuild.

**Before** -- original projection:

```python
@domain.projection
class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    total = Float()
    status = String(max_length=20)
```

**After** -- updated projection with decomposed total:

```python
@domain.projection
class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    subtotal = Float()
    tax = Float()
    shipping = Float()
    total = Float()
    status = String(max_length=20)
```

The projector is updated to populate the new fields:

```python
@domain.projector(projection_cls=OrderSummary)
class OrderSummaryProjector(BaseProjector):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderSummary)
        repo.add(OrderSummary(
            order_id=event.order_id,
            customer_name=event.customer_name,
            subtotal=event.subtotal,
            tax=event.tax,
            shipping=event.shipping,
            total=event.subtotal + event.tax + event.shipping,
            status="placed",
        ))
```

Deploy the code, then rebuild:

```bash
# CLI: rebuild a specific projection
protean projection rebuild --domain=my_app.ordering --projection=OrderSummary
```

Or from within a script:

```python
from my_app.ordering.domain import ordering as domain
from my_app.ordering.projections import OrderSummary

domain.init()
with domain.domain_context():
    result = domain.rebuild_projection(OrderSummary)

    print(f"Events dispatched: {result.events_dispatched}")
    print(f"Events skipped:    {result.events_skipped}")
    print(f"Errors:            {result.errors}")
    print(f"Success:           {result.success}")
```

!!! note "Rebuild is idempotent"
    `rebuild_projection()` truncates existing data before replaying. Running it
    twice produces the same result. There is no need to "undo" a failed rebuild
    -- just fix the issue and rebuild again.

---

### Blue-green deployment for zero-downtime rebuilds

For projections that serve live traffic (e.g. an API endpoint backed by
`OrderSummary`), you cannot truncate and rebuild in place without a period
where the projection is empty or incomplete. Blue-green deployment solves this.

**Step 1: Deploy a new projection class with a different `schema_name`.**

Keep the old `OrderSummary` running. Deploy a new class alongside it:

```python
# The existing projection -- still serving traffic
@domain.projection
class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    total = Float()
    status = String(max_length=20)


# The new projection -- different schema_name, same data
@domain.projection(schema_name="order_summary_v2")
class OrderSummaryV2(BaseProjection):
    order_id = Identifier(identifier=True)
    customer_name = String(max_length=100)
    subtotal = Float()
    tax = Float()
    shipping = Float()
    total = Float()
    status = String(max_length=20)
```

**Step 2: Deploy a projector for the new projection.**

```python
@domain.projector(projection_cls=OrderSummaryV2)
class OrderSummaryV2Projector(BaseProjector):

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(OrderSummaryV2)
        repo.add(OrderSummaryV2(
            order_id=event.order_id,
            customer_name=event.customer_name,
            subtotal=event.subtotal,
            tax=event.tax,
            shipping=event.shipping,
            total=event.subtotal + event.tax + event.shipping,
            status="placed",
        ))

    @handle(OrderShipped)
    def on_order_shipped(self, event: OrderShipped):
        repo = current_domain.repository_for(OrderSummaryV2)
        summary = repo.get(event.order_id)
        summary.status = "shipped"
        repo.add(summary)
```

**Step 3: Rebuild the new projection in the background.**

```python
domain.init()
with domain.domain_context():
    result = domain.rebuild_projection(OrderSummaryV2)

    if result.success:
        print(
            f"OrderSummaryV2 rebuilt: "
            f"{result.events_dispatched} events processed"
        )
    else:
        print(f"Rebuild failed: {result.errors}")
```

During the rebuild, the old `OrderSummary` continues serving traffic. The new
`order_summary_v2` table is being populated in the background.

**Step 4: Switch traffic.**

Once the rebuild completes and you have verified the data, update the API or
query layer to read from `OrderSummaryV2` instead of `OrderSummary`. This can
be a feature flag, a configuration change, or a code deployment.

```python
# Before: reading from the old projection
@app.get("/orders/{order_id}/summary")
async def get_order_summary(order_id: str):
    repo = domain.repository_for(OrderSummary)
    return repo.get(order_id)


# After: reading from the new projection
@app.get("/orders/{order_id}/summary")
async def get_order_summary(order_id: str):
    repo = domain.repository_for(OrderSummaryV2)
    return repo.get(order_id)
```

**Step 5: Clean up.**

After the switch is confirmed stable, remove the old `OrderSummary` class,
its projector, and drop the `order_summary` table. Optionally rename
`OrderSummaryV2` to `OrderSummary` and set `schema_name="order_summary_v2"`
explicitly to preserve the table name.

!!! warning "Keep both projectors running during the transition"
    While both projections are live, both projectors must be processing events.
    New events that arrive during the rebuild must be applied to both the old
    and new projections. The Engine handles this automatically since both
    projectors are registered in the domain.

---

### Monitoring rebuild progress with RebuildResult

The `RebuildResult` dataclass provides all the information you need to assess
a rebuild:

```python
from protean.utils.projection_rebuilder import RebuildResult

domain.init()
with domain.domain_context():
    result: RebuildResult = domain.rebuild_projection(OrderSummaryV2)

    # Basic outcome
    print(f"Projection:   {result.projection_name}")
    print(f"Success:      {result.success}")

    # Volume stats
    print(f"Dispatched:   {result.events_dispatched}")
    print(f"Skipped:      {result.events_skipped}")

    # Infrastructure stats
    print(f"Projectors:   {result.projectors_processed}")
    print(f"Categories:   {result.categories_processed}")

    # Errors (empty list on success)
    if result.errors:
        for error in result.errors:
            print(f"  ERROR: {error}")
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

### Using priority lanes for background rebuilds

For large projections, a rebuild replays thousands or millions of events. If
these events share the pipeline with production traffic, production latency
degrades. Use priority lanes to route rebuild work to the backfill stream.

Write a rebuild script that wraps `domain.process()` calls inside a low-priority
context:

```python
"""rebuild_with_priority.py

Rebuild projections using the backfill lane so production
event processing is not affected.
"""

import logging

from my_app.ordering.domain import ordering as domain
from my_app.ordering.projections import OrderSummaryV2
from protean.utils.processing import processing_priority, Priority

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def rebuild_via_backfill():
    domain.init()

    with domain.domain_context():
        # Tag all replay work as low priority.
        # Events produced during the rebuild are routed
        # to the backfill stream, not the primary stream.
        with processing_priority(Priority.LOW):
            result = domain.rebuild_projection(OrderSummaryV2)

        if result.success:
            logger.info(
                "Rebuild complete: %d events dispatched, %d skipped",
                result.events_dispatched,
                result.events_skipped,
            )
        else:
            logger.error("Rebuild failed: %s", result.errors)


if __name__ == "__main__":
    rebuild_via_backfill()
```

!!! note "Priority lanes must be enabled"
    Priority lanes require `server.priority_lanes = true` in `domain.toml`
    and a Redis broker. See
    [Priority Lanes](../concepts/async-processing/priority-lanes.md) for
    configuration details.

---

## Anti-Patterns

### ALTER TABLE on a projection instead of rebuilding

```python
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
  the event store contain the actual values -- a rebuild would produce correct
  data.
- The projection's Python class and its database schema are now out of sync.
  The `OrderSummary` class defines `subtotal` as a field, but the column was
  added manually rather than through Protean's schema management.
- Future developers will not know whether the projection's data matches the
  event history. Is the `subtotal` column populated from events, from a
  one-time migration script, or from a manual `UPDATE`? The provenance is
  lost.

**Instead:** Update the projection class and projector, then rebuild:

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

A rebuild replays every event since the beginning of time. If you added an
event four months ago but never registered an upcaster for its old schema, the
rebuild will fail (or worse, silently skip events). If a projector handler has
a bug that only manifests with old event data, the rebuild surfaces it in
production.

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

**Instead:** Use the blue-green deployment pattern described above. Deploy a
new projection class with a different `schema_name`, rebuild in the background,
then switch traffic once the rebuild completes.

---

### Skipping the rebuild after deploying new projector logic

If you deploy a projector that populates new fields but do not rebuild, only
*future* events produce projections with the new fields. Historical records
still have the old shape. The read model is inconsistent -- some rows have
`subtotal`, `tax`, and `shipping`; others do not.

**Instead:** Always rebuild after deploying projector changes that affect the
projection's schema or data mapping.

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
| **Background execution** | Custom batching logic | `processing_priority(Priority.LOW)` |
| **Progress monitoring** | Custom logging | `RebuildResult` stats |
| **CLI support** | Manual scripts | `protean projection rebuild` |
| **Idempotency** | Depends on script | Always -- truncate and replay |

The principle: **projections are derived data. They can always be reconstructed
from events. Treat the rebuild as a deployment operation -- test it, monitor
it, automate it -- and you free yourself from the constraints of traditional
schema migration.**

---

!!! tip "Related reading"
    **Patterns:**

    - [Event Versioning and Evolution](event-versioning-and-evolution.md) -- Evolve event schemas that projections consume.

    **Concepts:**

    - [Projections](../concepts/building-blocks/projections.md) -- What projections are.
    - [Projectors](../concepts/building-blocks/projectors.md) -- How projectors maintain projections.

    **Guides:**

    - [Projections](../guides/consume-state/projections.md) -- Defining projections.
    - [`protean projection rebuild`](../reference/cli/data/projection.md) -- CLI command for projection rebuilds.
    - [Event Upcasting](../guides/consume-state/event-upcasting.md) -- Transforming old event schemas during replay.
