# Sequential Processing by Partition Key (`sequential_by`)

`sequential_by` gives a handler a per-key ordering guarantee: two *different*
events that share a partition key are never processed at the same time, and
their committed effects land in publish order. Events with different keys still
run in parallel. This is the escape hatch for the one case the built-in
concurrency primitives (optimistic concurrency, process managers, idempotent
handlers) do not cover — a single high-throughput handler that must serialize by
an entity key without funnelling every key onto one worker.

The full design and its guarantees are in
[ADR-0028](../../adr/0028-partition-per-key-sequential-processing.md). Before
reaching for it, read
[Designing for Concurrent Event Processing](../../patterns/designing-for-concurrent-event-processing.md):
most concurrency problems have a simpler structural fix.

!!! note "Events on the Redis broker; command handlers still inert"
    The Redis broker advertises `STREAM_PARTITIONING`, so `sequential_by` is
    fully active there for **event handlers** and **process managers**: the
    publisher routes each event to its partition stream, and the consumer
    described under [How the consumer enforces ordering](#how-the-consumer-enforces-ordering)
    owns and serially drains each partition across engine instances.

    Commands do not currently go through the outbox at all — a command handler
    dispatches synchronously and never produces an outbox row, so it has no
    `stream_category` and nothing to partition. Declaring `sequential_by` on a
    **command handler** is accepted and checked at registration (field
    existence, one key per category), but that check is inert today: it has no
    runtime effect until command publishing exists.

    The **inline** broker does not advertise `STREAM_PARTITIONING`. There
    `sequential_by` is an accepted no-op (inline already processes messages in
    submission order), so handlers keep an ordinary subscription. Any broker that
    neither advertises the capability nor is the inline broker rejects a
    `sequential_by` handler at `domain.init()` with an `IncorrectUsageError`.

## Declaring the key

On an **event handler** or **command handler**, `sequential_by` is the name of a
direct field on the event or command payload. Only the event-handler case has a
runtime effect today — see the warning above.

```python
@domain.event_handler(part_of=Order, sequential_by="client_id")
class OrderProjector(BaseEventHandler):
    @handle(OrderPlaced)
    def on_placed(self, event: OrderPlaced) -> None:
        ...
```

On a **process manager** it is a boolean opt-in. A process manager already
declares its serialization domain through its `correlate` specs, so
`sequential_by=True` partitions each subscribed category by the field that
category's `correlate` maps to the correlation value:

```python
@domain.process_manager(sequential_by=True)
class OrderFulfillment(BaseProcessManager):
    order_id = Identifier(identifier=True)

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_placed(self, event: OrderPlaced) -> None:
        ...
```

Nested paths and computed keys are out of scope: the key is a single named field.

## What is validated at registration

`domain.init()` fails loud if any of these do not hold, turning a class of
runtime surprises into a startup error:

- **Field existence.** Every event or command type the handler handles must
  declare the named field. For a process manager, every handled event must carry
  the field its `correlate` spec resolves for that event.
- **One key per category.** A partition key is a property of the stream
  *category*, not of one handler. Two handlers on the same category that ask for
  different keys are rejected — all handlers on a category must agree on one key
  or not partition it at all.
- **Broker capability.** The target broker must advertise the
  `STREAM_PARTITIONING` capability. The inline broker is the accepted exception
  (it is a no-op there); any other broker without the capability is rejected.

## Key values that are rejected

The partition key becomes the `{stream_category}:{key}` stream-name segment, so
a value that would collide with reserved stream names is rejected. For an
event, the value is extracted and validated **synchronously in the caller's
transaction** when the outbox record is created, so a bad value fails the
caller's operation immediately and never enters the outbox. A key is rejected
when it is:

- null or empty,
- contains a colon (`:`),
- equals a reserved lane/DLQ token (`dlq`, or the configured
  `[server.priority_lanes]` `backfill_suffix`, default `backfill`), or
- matches the reserved `__name__` sentinel form (double-underscore delimited,
  e.g. `__partitions__`).

Real partition keys are entity identifiers (a `client_id`, an `order_id`, a
UUID), which never hit these rules. Rejecting rather than routing a bad key to a
default partition is deliberate: a default partition would silently coalesce
unrelated keys and break ordering for all of them.

## How a partitioned event is routed

For a partitioned category the outbox stores the validated key on the row's
`partition_key` field. When the target broker advertises `STREAM_PARTITIONING`,
the outbox processor routes the row to `{stream_category}:{key}`, composing with
the priority-lane suffix when a low-priority row also uses the backfill lane:

- partition stream: `{stream_category}:{key}` (for example `order:client-123`)
- partition backfill lane: `{stream_category}:{key}:{backfill_suffix}`

Under a broker without the capability the key is carried on the row but not
applied, so routing falls back to the base category. As a safety backstop, a row
that somehow reaches publishing with an invalid key is marked `ABANDONED` at once
rather than retried, so one bad row can never wedge the outbox behind it.

## How the consumer enforces ordering

Routing events to per-key streams is not enough on its own: a shared Redis
consumer group hands different messages to different engine instances with no key
affinity, so two events for the same key could still run at the same time on two
instances. The ordering guarantee is enforced by **partition ownership**, not by
a per-message lock.

For each partition the engine sees in the [discovery index](#discovery-and-cold-partitions),
one instance takes an **ownership lease** and becomes the sole consumer of that
partition's stream. The lease carries a **fencing token** — a generation number
that increases every time ownership changes hands — and every read and ack is
guarded by an atomic "do I still hold the lease at this generation?" check. This
gives four properties:

- **Single active consumer per partition.** Only the lease owner reads a
  partition, so two different same-key events are never processed at once and
  their committed effects land in publish order. Different keys are owned
  independently and drain in parallel.
- **Crash failover with no loss.** If the owner dies, its lease expires, another
  instance takes over at a new generation and reclaims the dead owner's unacked
  entries (`XAUTOCLAIM`), then resumes in order. Delivery stays
  at-least-once: the single in-flight event may be re-run on failover, so
  handlers still lean on optimistic concurrency and idempotency for exactly-once
  *effect*.
- **Stall safety (the fence).** If an owner stalls past its lease and another
  instance takes over, the stale owner's fenced read and ack are rejected — it
  can neither advance the partition nor ack out from under the new owner, so
  committed order stays intact.
- **Halt on poison.** A message that a partition cannot process (after its
  retries) halts that partition: it stays as the pending head and the partition
  stops advancing, rather than being auto-moved to a DLQ (which would apply a
  later same-key event before it and reorder the key). The halt is scoped to one
  partition; other partitions keep flowing. Unwedging a halted partition is an
  explicit operator action (inspect the head, then skip it or move it to the DLQ
  by hand).

### Discovery and cold partitions

The consumer discovers live partitions by reading a maintained index — a Redis
set `{stream_category}:__partitions__` the publisher writes on each publish — not
by scanning the keyspace. New partitions are picked up on the next discovery
cycle with no restart. A partition that has fully drained and been idle for
`reap_idle_ms` is retired by its owner (its index entry and empty stream are
pruned), so the index stays bounded; a publish that re-creates the partition is
simply re-discovered.

Process managers own by **correlation value** rather than by a single stream: one
instance leases a correlation value and is the sole processor of every subscribed
category's partition for that value, so no two events for the same process-manager
instance are ever handled at once. Cross-category order for one instance is not
promised (the events live on different streams) — only that they never overlap.

### Priority lanes

When [priority lanes](../../guides/server/using-priority-lanes.md) are enabled, a low-priority
partitioned event is published to the key's backfill lane
(`{category}:{key}:{backfill_suffix}`). The owner drains a key's primary lane
before its backfill lane (production before backfill, as elsewhere), and reaping
a cold key covers both lanes, so backfill-routed partitioned events are consumed
and never stranded. Combining the two features means, within a key, a
higher-priority event can be handled before a lower-priority one published
earlier; strict publish order holds within each lane.

## Configuration (`[server.partitioning]`)

The partitioned consumer's timing is tunable under `[server.partitioning]` in
`domain.toml`. The defaults suit most workloads; tune the lease TTL to trade
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
