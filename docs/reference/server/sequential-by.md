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

!!! warning "Publishing side only — inline broker only, today"
    This page documents the **publishing** behaviour that ships today: the
    option, its registration-time validation, and how the outbox routes a
    partitioned event. The **consumer** side that actually enforces the ordering
    across multiple engine instances (partition ownership lease, fencing token,
    crash reclaim, partition discovery) is tracked separately and is not yet
    active.

    No broker shipped with Protean advertises the `STREAM_PARTITIONING`
    capability yet, so today `sequential_by` is usable **only on the inline
    broker**, where it is a validated no-op (inline already processes messages in
    submission order). On any other broker (for example Redis) declaring
    `sequential_by` fails `domain.init()` with an `IncorrectUsageError` — the
    broker-capability check below rejects it — and it stays that way until the
    consumer side lands and a broker turns the capability on. The routing and
    Redis-specific guidance below describe the target behaviour for that future
    broker, not something you can switch on now.

## Declaring the key

On an **event handler** or **command handler**, `sequential_by` is the name of a
direct field on the event or command payload:

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
a value that would collide with reserved stream names is rejected. The value is
extracted and validated **synchronously in the caller's transaction** when the
outbox record is created, so a bad value fails the caller's operation
immediately and never enters the outbox. A key is rejected when it is:

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

## Applicability

Partition-per-key on Redis is bounded-cardinality by design. The key must be a
natural serialization domain with a bounded live set (a tenant, a region, an
account), **not** a high-cardinality per-entity key (one partition per order or
per request in a large population). See ADR-0028's "Applicability and limits"
for the reasoning and the ceiling.
