# Tune subscriptions

How to change the way a handler consumes its stream: pick a profile, override a
single setting, cap stream growth, pause a failing handler before it retries
its whole backlog, and check how far behind it is.

For the full list of options and their defaults, see the
[server configuration reference](../../reference/server/configuration.md). For
why subscriptions work the way they do, see
[Subscriptions](../../concepts/async-processing/subscriptions.md).

---

## Start with a profile

A profile is a named bundle of subscription settings. Naming one is the shortest
way to change how a handler consumes, and it is usually enough:

```toml
# domain.toml
[server]
subscription_profile = "batch"
```

Five profiles ship with Protean:

| Profile | Reach for it when |
|---------|-------------------|
| `production` | The default posture for real workloads. |
| `fast` | Latency matters more than throughput: small batches, no idle delay. |
| `batch` | Throughput matters more than latency, such as a backfill or an import. |
| `debug` | You are watching one message at a time in development. |
| `projection` | The handler rebuilds a read model and you want event-store replay rather than stream consumption. |

When only one handler needs a profile, set the profile on that handler:

```toml
[server.subscriptions.OrderReportProjector]
subscription_profile = "batch"
```

## Override one setting

You do not need a custom profile to change a single value. Handler-level keys
override the profile:

```toml
[server.subscriptions.NotificationHandler]
subscription_profile = "fast"
messages_per_tick = 25          # everything else stays as `fast` sets it
```

When several handlers need the same combination of settings, and only then,
define a **custom profile**:

```toml
[server.profiles.reporting]
inherits = "batch"
messages_per_tick = 1000
max_retries = 10

[server.subscriptions.OrderReportProjector]
subscription_profile = "reporting"
```

A custom profile inherits from a built-in, not from another custom profile.
The full resolution order is in the
[configuration reference](../../reference/server/configuration.md).

## Stop a stream from growing forever

Stream subscriptions read from Redis streams. A Redis stream keeps every
message until a client trims the stream. Set a cap:

```toml
[server.subscriptions.OrderEventHandler]
retention_maxlen = 100_000
```

**Read this before you rely on that number.** What Protean actually does depends
on how many consumer groups read the stream, because the priority is never
deleting an event somebody still needs:

- **Two or more consumer groups**: The stream is trimmed to the slowest group's
  read position. In this case **`retention_maxlen` is ignored**. Consumer
  progress bounds the stream, not your number. A stream with several handlers
  on it therefore grows as large as the slowest handler lets it. To shrink an
  oversized stream, find the handler that is behind, because lowering
  `retention_maxlen` has no effect here.
- **One consumer group, or none**: The stream is capped at `retention_maxlen`.
  This cap is a hard size ceiling. It is *not* progress-safe: if the single
  reader falls more than `retention_maxlen` behind, the oldest **unread**
  entries are dropped. That happens during an initial catch-up on a
  pre-existing stream, after an outage, or under a producer faster than the
  handler. Set `retention_maxlen` above the largest backlog you expect. A value
  at the steady-state length is too small.

Trimming is approximate in both cases (Redis's `~`), so the stream stays
slightly longer than the length Protean trims it to. Exact trimming costs far
more for a bound that did not need to be exact.

Retention is size-based only. There is no time-based option, so choose from how
far behind you will let a consumer fall, not from how long you want to keep
history. For history, use the event store.

`production`, `fast`, and `batch` already set a cap. The bare default with no
profile does not.

## Pause a failing handler before it retries its whole backlog

Without a circuit breaker, Protean retries every message for a repeatedly
failing handler at the rate the stream delivers them. One broken dependency
then sends a large number of messages to the dead-letter queue. The circuit
breaker pauses reads instead:

```toml
[server.subscriptions.PaymentHandler]
circuit_breaker_threshold = 5       # consecutive failures before it trips
circuit_breaker_reset_seconds = 30  # how long it waits before probing again
```

What you will observe when it trips:

1. **Open**: Reads stop. Messages stay in the stream and the pending list, so
   nothing is lost. Protean redelivers them later.
2. **Half-open**: After the reset window, one probe message is allowed through.
3. **Closed** if the probe succeeds. If the probe fails, the breaker goes back
   to open and restarts the timer.

The breaker counts *consecutive* failures, so a single success resets the count.
A subscription paused by its breaker does not make the engine unready: `/readyz`
still returns 200, because the pod is healthy and the rest of its subscriptions
are still working.

## Process events for the same entity in order

By default a handler may process several events concurrently, so two events for
the same order can overlap. `sequential_by` partitions the stream by a key, and
the handler processes events that share a key one at a time. Events with
different keys still run in parallel:

```python
--8<-- "guides/server/tuning-subscriptions/001.py:model"
--8<-- "guides/server/tuning-subscriptions/001.py:handler"
```

Events for `order_id=A` are serialised against each other. Events for
`order_id=B` proceed independently.

- [Sequential processing reference](../../reference/server/sequential-by.md):
  the option, its constraints, and how partitions are discovered.
- [Designing for concurrent event
  processing](../../patterns/designing-for-concurrent-event-processing.md):
  when to use `sequential_by` instead of a process manager, and the trade-offs.
- Partition-per-key sequential processing
  ([ADR-0028](../../adr/0028-partition-per-key-sequential-processing.md)): Why
  Protean partitions per key instead of using a fixed partition count. This
  decision supersedes the deferral recorded in the concurrent event processing
  strategy
  ([ADR-0009](../../adr/0009-concurrent-event-processing-strategy.md)).

## Check how far behind a subscription is

From the command line:

```shell
protean subscriptions status
```

From a running engine, the readiness probe reports the same data per
subscription, including circuit-breaker state:

```shell
curl -s localhost:8080/readyz | jq '.checks.subscriptions'
```

```json
{
  "total": 12,
  "details": [
    {
      "name": "OrderProjector-order",
      "handler_name": "OrderProjector",
      "subscription_type": "stream",
      "stream_category": "order",
      "lag": 0,
      "pending": 0,
      "dlq_depth": 0,
      "status": "ok",
      "circuit_state": "closed"
    }
  ]
}
```

Both read the same source as the `protean.subscription.consumer_lag` and
`protean.subscription.pending_messages` metrics, so the three never disagree.
Set your alerts on the metrics. When you are already looking at a specific pod,
use the probe or the CLI. The [hardening
reference](../../reference/server/hardening.md) covers the staleness fields of
the `subscriptions` block in `/readyz` and the cases that block does not yet
cover.

---

## What to change first

If a subscription is not keeping up, work in this order:

1. **Look before tuning**: `protean subscriptions status` tells you whether the
   problem is lag (not reading fast enough), pending (reading but not
   acknowledging), or DLQ depth (failing outright). They need different fixes.
2. If lag is high and the handler is healthy, **raise `messages_per_tick`**.
   Of all the subscription settings, `messages_per_tick` changes throughput the
   most. The `batch` profile exists to set it for you.
3. **Check the handler itself**: A slow handler is far more often the cause than
   a small batch size. If the handler makes a network call per event, no
   subscription setting will make it fast enough.
4. **Only then consider a custom profile**: When you override more than two or
   three settings on one handler, move those settings into a custom profile.

!!! warning "Two settings that are not performance knobs"

    `max_retries` and `enable_dlq` decide what happens to a message that cannot
    be processed. If you turn retries up to hide a failing handler, you convert
    a fast, visible failure into a slow, invisible one. See [Dead letter
    queues](dead-letter-queues.md).

## Read more about subscriptions

- [Server configuration reference](../../reference/server/configuration.md): Every option, its default, and the resolution order.
- [Subscription types](../../reference/server/subscription-types.md): Stream versus event-store consumption.
- [Hardening](hardening.md): Health probes, graceful shutdown, and operational limits.
- [Monitoring](monitoring.md): The metrics to alert on.
