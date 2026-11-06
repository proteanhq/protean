# Sequential Processing by Partition Key (`sequential_by`)

`sequential_by` gives a handler a per-key ordering guarantee: two *different*
events that share a partition key are never processed at the same time. Their
effects are committed in publish order. Events with different keys still run in
parallel. `sequential_by` covers the one case that the built-in concurrency
primitives (optimistic concurrency, process managers, idempotent handlers) do
not cover. In that case, a single high-throughput handler must serialize events
by an entity key without sending every key to one worker.

The decision record on partition-per-key sequential processing
([ADR-0028](../../adr/0028-partition-per-key-sequential-processing.md)) sets
out the full design and its guarantees. Before you use `sequential_by`, read
[Designing for Concurrent Event
Processing](../../patterns/designing-for-concurrent-event-processing.md): most
concurrency problems have a simpler structural fix.

!!! note "Events on the Redis broker; command handlers still inert"
    The Redis broker advertises `STREAM_PARTITIONING`, so `sequential_by` is
    fully active there for **event handlers**, **projectors** and **process
    managers**: the
    publisher routes each event to its partition stream, and the consumer
    described under [How the consumer enforces ordering](#how-the-consumer-enforces-ordering)
    owns and serially drains each partition across engine instances.

    Commands do not currently go through the outbox. A command handler
    dispatches synchronously and never produces an outbox row, so it has no
    `stream_category` and nothing to partition. You can declare `sequential_by`
    on a **command handler**, and registration checks it (field existence, one
    key per category). That check has no runtime effect until command
    publishing exists.

    The **inline** broker does not advertise `STREAM_PARTITIONING`. There
    `sequential_by` is an accepted no-op (inline already processes messages in
    submission order), so handlers keep an ordinary subscription. On any broker
    that neither advertises the capability nor is the inline broker,
    `domain.init()` rejects a `sequential_by` handler with an
    `IncorrectUsageError`.

## Declaring the key

On an **event handler**, **projector** or **command handler**, `sequential_by`
is the name of a direct field on the event or command payload. The event-handler
and projector cases have a runtime effect today. The command-handler case does
not, see the note above.

```python
--8<-- "reference/server/sequential-by/001.py:order_model"
--8<-- "reference/server/sequential-by/001.py:event_handler"
```

On a projector, every event the projector handles must carry the field. Protean
partitions the category that each handled event is published to by that field:

```python
--8<-- "reference/server/sequential-by/001.py:product_model"
--8<-- "reference/server/sequential-by/001.py:projector"
```

A projector on a stream subscription (`subscription_type` set to `"stream"`)
does not need its own `sequential_by` to be ordered. Protean stores the key per
stream category. Every stream-subscribed handler on a partitioned category
consumes that category partition by partition. So when an event handler or
process manager already partitions a category, a projector on that category
gets the same ordering. Declaring `sequential_by` on the projector matters when
no other handler partitions its categories.

The ordering applies only to stream subscriptions. The event-store subscription
is the domain default and the `PROJECTION` profile's choice. A projector on an
event-store subscription reads the event store directly, and `sequential_by`
does not change those reads.

Ordering is per stream category. When a projector covers several aggregates,
such as `aggregates=[Customer, Order]` with `sequential_by="customer_id"`, it
gets one partitioned subscription per category. A `Customer` event and an
`Order` event for the same customer can still be processed at the same time.

On a **process manager**, `sequential_by` is a boolean opt-in. A process
manager already declares its serialization domain through its `correlate`
specs. So `sequential_by=True` partitions each subscribed category by the field
that category's `correlate` maps to the correlation value. Here the `payment`
category is partitioned by `order_id`:

```python
--8<-- "reference/server/sequential-by/001.py:payment_model"
--8<-- "reference/server/sequential-by/001.py:process_manager"
```

Nested paths and computed keys are out of scope: the key is a single named field.

## What is validated at registration

`domain.init()` raises an error at startup if any of these rules do not hold,
so you find these problems before runtime:

- **Each handled type must declare the field**: Every event or command type the
  handler handles must declare the named field. For a process manager, every
  handled event must carry the field its `correlate` spec resolves for that
  event.
- **One key per category**: A partition key is a property of the stream
  *category*, not of one handler. Two handlers on the same category that ask for
  different keys are rejected. All handlers on a category must agree on one key
  or not partition it at all. For example, the `client_id` event handler above
  cannot share a domain with a process manager that correlates `OrderPlaced` by
  `order_id`: both partition the `order` category.
- **The broker must support partitioning**: Apart from the inline broker, the
  target broker must advertise the `STREAM_PARTITIONING` capability. On the
  inline broker, `sequential_by` is an accepted no-op. Registration rejects any
  other broker without the capability.

## Key values that are rejected

The partition key becomes the `{stream_category}:{key}` stream-name segment, so
a value that would collide with reserved stream names is rejected. For an
event, Protean extracts and validates the value **synchronously in the caller's
transaction** as it creates the outbox record. A bad value fails the caller's
operation immediately and never enters the outbox. A key is rejected when it
is:

- null or empty,
- contains a colon (`:`),
- equals a reserved lane/DLQ token (`dlq`, or the configured
  `[server.priority_lanes]` `backfill_suffix`, default `backfill`), or
- matches the reserved `__name__` sentinel form (double-underscore delimited,
  e.g. `__partitions__`).

Real partition keys are entity identifiers (a `client_id`, an `order_id`, a
UUID), and these rules never reject them. Protean rejects a bad key on purpose
and does not route it to a default partition: a default partition would
silently merge unrelated keys and break ordering for all of them.

## How a partitioned event is routed

For a partitioned category the outbox stores the validated key on the row's
`partition_key` field. When the target broker advertises `STREAM_PARTITIONING`,
the outbox processor routes the row to `{stream_category}:{key}`. For a
low-priority row that also uses the backfill lane, the processor adds the
priority-lane suffix:

- partition stream: `{stream_category}:{key}` (for example `order:client-123`)
- partition backfill lane: `{stream_category}:{key}:{backfill_suffix}`

Under a broker without the capability the key is carried on the row but not
applied, so routing falls back to the base category. As a safety check, the
outbox processor marks a row `ABANDONED` at once, with no retry, when the row
somehow reaches publishing with an invalid key. The row keeps its key, so it
halts that key's later rows (see the next section). Rows for other keys keep
publishing.

## How the outbox keeps a key in order

The outbox processor publishes a key's rows in commit order. It groups
partitioned rows by target broker, stream category, partition key and priority
lane. A row is claimed only when every earlier row of its group has been
published or discarded, or is claimed in the same batch. Within a batch, the processor
publishes each group's rows in commit order.

The outbox processor holds the later rows of a group while an earlier row of
that group is pending, in flight, failed or abandoned:

- A **failed** row holds its key until its retry is due and it publishes.
- An **abandoned** row halts its key. The key's later rows stay in the outbox
  until an operator retries or discards the row with `protean outbox retry` or
  `protean outbox discard`. Both commands are described in [the outbox
  guide](../../guides/server/outbox.md#a-partitioned-key-can-halt). `protean
  outbox halted` lists the halted keys. Cleanup does not delete abandoned rows
  that have a partition key.
- When a row fails mid-batch, the processor puts the later rows of its group
  (same key, stream and lane) from that batch back to `pending` without
  publishing them. The processor does not change their retry counts.

The halt is scoped to one group. Other keys, the other priority lane, rows
without a partition key, and other target brokers keep publishing. The outbox
applies the halt before routing. So the halt holds on every broker, including
one that does not advertise `STREAM_PARTITIONING`.

The hold-back follows the order in which rows were written. For one aggregate
instance, that order matches commit order. Several aggregate instances can
carry the same key field (many orders with one `client_id`). Nothing orders the
commits of those instances against each other. A row written earlier can commit
later, after a later row of the same key has already published. Rows written
before 0.19 have no stream category and are never held unless you fill the
column; see the [0.19 migration
notes](../migration/v0-19.md#outbox-rows-wait-for-their-partition-keys-earlier-rows).

## How the consumer enforces ordering

Routing events to per-key streams is not enough on its own: a shared Redis
consumer group hands different messages to different engine instances with no key
affinity, so two events for the same key could still run at the same time on two
instances. The ordering guarantee is enforced by **partition ownership**, not by
a per-message lock.

For each partition the engine sees in the [discovery
index](#discovery-and-cold-partitions), one instance takes an **ownership
lease** and becomes the sole consumer of that partition's stream. The lease
carries a **fencing token** (a generation number that increases every time
ownership changes). An atomic "do I still hold the lease at this generation?"
check guards every read and ack. This gives four properties:

- **Single active consumer per partition**: Only the lease owner reads a
  partition, so two different same-key events are never processed at once.
  Their effects are committed in publish order. Different keys are owned
  independently and drain in parallel.
- **Crash failover with no loss**: If the owner dies, its lease expires, another
  instance takes over at a new generation and reclaims the dead owner's unacked
  entries (`XAUTOCLAIM`), then resumes in order. Delivery stays at-least-once:
  the single in-flight event may be re-run on failover, so handlers still rely
  on optimistic concurrency and idempotency for exactly-once *effect*.
- **Stall safety (the fence)**: If an owner stalls past its lease and another
  instance takes over, the stale owner's fenced read and ack are rejected. The
  stale owner can neither advance the partition nor ack entries that the new
  owner now holds, so committed order stays intact.
- **Halt on poison**: A message that a partition cannot process (after its
  retries) halts that partition: it stays as the pending head and the partition
  stops advancing, rather than being auto-moved to a DLQ (which would apply a
  later same-key event before it and reorder the key). The halt is scoped to
  one partition; other partitions keep flowing. An operator restarts a halted
  partition by an explicit action: the operator inspects the head, then skips
  it or moves it to the DLQ by hand.

### Discovery and cold partitions

The consumer discovers live partitions by reading a maintained index, a Redis
set `{stream_category}:__partitions__` the publisher writes on each publish,
not by scanning the keyspace. The consumer finds new partitions on the next
discovery cycle, with no restart. A partition that has fully drained and been
idle for `reap_idle_ms` is retired by its owner (its index entry and empty
stream are pruned), so the index stays bounded; a publish that re-creates the
partition is re-discovered.

Process managers own by **correlation value** rather than by a single stream:
one instance leases a correlation value and is the sole processor of every
subscribed category's partition for that value, so no two events for the same
process-manager instance are ever handled at once. Protean does not promise
cross-category order for one instance, because the events are on different
streams. Protean promises only that those events never overlap.

### Priority lanes

When [priority lanes](../../guides/server/using-priority-lanes.md) are enabled,
a low-priority partitioned event is published to the key's backfill lane
(`{category}:{key}:{backfill_suffix}`). The owner reads a key's primary lane
before its backfill lane (production before backfill, as elsewhere). Reaping a
cold key covers both lanes, so the owner consumes backfill-routed partitioned
events and never leaves them unread. With both features on, a higher-priority
event within a key can be handled before a lower-priority one published
earlier. Strict publish order holds within each lane.

## Configuration (`[server.partitioning]`)

The partitioned consumer's timing is tunable under `[server.partitioning]` in
`domain.toml`. The defaults suit most workloads. Tune the lease TTL to trade
failover speed against reclaim churn.

| Key | Type | Default | Meaning |
|-----|------|---------|---------|
| `lease_ttl_ms` | int | `15000` | How long an ownership lease is held before it must be renewed. Shorter means faster failover after a crash but more reclaim churn. |
| `heartbeat_interval_seconds` | float | `lease_ttl_ms / 5000` (≈ `3.0`) | How often the owner renews its held leases. Must be well under the TTL so a live owner never lets a lease lapse. |
| `poll_interval_seconds` | float | `0.25` | How long a per-partition worker waits between reads when its partition is empty. |
| `reap_idle_ms` | int | `3600000` | How long a drained partition must sit idle before its owner retires it from the index. |

## Applicability

Partition-per-key on Redis is bounded-cardinality by design. The key must be a
natural serialization domain with a bounded live set (a tenant, a region, an
account), **not** a high-cardinality per-entity key (one partition per order or
per request in a large population). See ADR-0028's "Applicability and limits"
for the reasoning and the ceiling.
