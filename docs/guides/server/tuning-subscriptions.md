# Tuning subscriptions

How to change the way a handler consumes its stream: pick a profile, override a
single setting, cap stream growth, stop a failing handler from burning through
its backlog, and check how far behind it is.

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

Set it per handler when only one needs it:

```toml
[server.subscriptions.OrderReportProjector]
subscription_profile = "batch"
```

## Override one setting

You do not need a custom profile to change a single value. Handler-level keys
win over the profile:

```toml
[server.subscriptions.NotificationHandler]
subscription_profile = "fast"
messages_per_tick = 25          # everything else stays as `fast` sets it
```

Reach for a **custom profile** only when the same combination is wanted by
several handlers:

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

Stream subscriptions read from Redis streams, which keep every message until
something trims them. Protean trims them, and no setting controls it.
After each batch, a stream subscription asks the broker to trim the stream it
read. The one exception is a handler that uses `sequential_by`: Protean does
not trim its per-key partition streams.
The broker removes only the entries that every consumer group on the stream has
read and acknowledged, so the trim never deletes an event an existing handler
still needs. A handler you add later starts at the oldest entry left. An entry that was delivered and not yet acknowledged stays until it is
acknowledged, so a retry or a claim after a crash still finds it.

The stream therefore grows as large as the slowest handler lets it. To shrink an
oversized stream, find the handler that is behind and fix it.

A consumer group that never reads stops all trimming on its stream, because it
has not read the first entry. This happens when a consumer dies before its first
read. A handler you remove and whose consumer group you leave behind stops
trimming in the same way, from the last entry that group read. Delete that group
to let the stream shrink again.

Trimming is approximate (Redis's `~`), so the stream can stay a little above the
point every group has reached.

Only a broker that declares `STREAM_RETENTION`, such as Redis Streams, trims. On
any other broker Protean does not call the trim.

Retention follows consumer progress only. There is no time-based option. For
history, use the event store.

## Stop a failing handler from burning through its backlog

When a handler fails repeatedly, retrying every message as fast as the stream
delivers them turns one broken dependency into a flood of dead letters. The
circuit breaker pauses reads instead:

```toml
[server.subscriptions.PaymentHandler]
circuit_breaker_threshold = 5       # consecutive failures before it trips
circuit_breaker_reset_seconds = 30  # how long it waits before probing again
```

What you will observe when it trips:

1. **Open**: Reads stop. Messages stay in the stream and the pending list, so
   nothing is lost, and they are redelivered later.
2. **Half-open**: After the reset window, one probe message is allowed through.
3. **Closed** if the probe succeeds. If the probe fails, the breaker goes back
   to open and restarts the timer.

The breaker counts *consecutive* failures, so a single success resets the count.
A subscription paused by its breaker does not make the engine unready: `/readyz`
still returns 200, because the pod is healthy and the rest of its subscriptions
are still working.

## Process events for the same entity in order

By default a handler may process several events concurrently, so two events for
the same order can overlap. `sequential_by` partitions the stream by a key so
that events sharing that key are handled one at a time, while different keys
still run in parallel:

```python
--8<-- "guides/server/tuning-subscriptions/001.py:model"
--8<-- "guides/server/tuning-subscriptions/001.py:handler"
```

Events for `order_id=A` are serialised against each other; events for
`order_id=B` proceed independently.

- [Sequential processing reference](../../reference/server/sequential-by.md):
  the option, its constraints, and how partitions are discovered.
- [Designing for concurrent event processing](../../patterns/designing-for-concurrent-event-processing.md):
  when to reach for this instead of a process manager, and the trade-offs.
- [ADR-0028](../../adr/0028-partition-per-key-sequential-processing.md): Why
  partition-per-key rather than a fixed partition count, superseding the
  deferral recorded in [ADR-0009](../../adr/0009-concurrent-event-processing-strategy.md).

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
Alert on the metrics; use the probe and the CLI when you are already looking at
a specific pod. The [hardening reference](../../reference/server/hardening.md)
covers the staleness fields of the `subscriptions` block in `/readyz` and the
cases that block does not yet cover.

---

## Trade pickup delay for event store load

An idle event-store subscription waits longer between reads. With the default
`tick_interval` of 0, the wait starts at 10 ms after the first empty read. With a
longer `tick_interval`, it doubles from `tick_interval`. Each further empty read
doubles it again, up to `max_tick_interval` (1 second by default). The first
read that returns messages sets the wait back to `tick_interval`.

The backoff adds at most `max_tick_interval`, or `tick_interval` when that is
longer, before an idle subscription picks up a new event. While idle, each
subscription runs about one read per that many seconds. Set the value for the whole domain:

```toml
# domain.toml
[server.event_store_subscription]
max_tick_interval = 0.25
```

A lower value picks up events sooner and reads the event store more often. A
higher value reads less often and picks up events later. `0` turns the backoff
off: the subscription waits `tick_interval` between reads, which is continuous
polling with the default `tick_interval` of 0.

This setting applies to event-store subscriptions only. A stream subscription
waits on a blocking read instead, set by `blocking_timeout_ms`.

## What to change first

If a subscription is not keeping up, work in this order:

1. **Look before tuning**: `protean subscriptions status` tells you whether the
   problem is lag (not reading fast enough), pending (reading but not
   acknowledging), or DLQ depth (failing outright). They need different fixes.
2. **Raise `messages_per_tick`** if lag is high and the handler is healthy. This
   is the single most effective knob, and `batch` exists to set it for you.
3. **Check the handler itself**: A slow handler is far more often the cause than
   a small batch size. Tuning around a handler that makes a network call per
   event will not save you.
4. **Only then reach for a custom profile**: If you are overriding more than two
   or three settings on one handler, that is the signal.

!!! warning "Two settings that are not performance knobs"

    `max_retries` and `enable_dlq` decide what happens to a message that cannot
    be processed. Turning retries up to hide a failing handler converts a fast,
    visible failure into a slow, invisible one. See
    [Dead letter queues](dead-letter-queues.md).

## Related reading

- [Server configuration reference](../../reference/server/configuration.md): Every option, its default, and the resolution order.
- [Subscription types](../../reference/server/subscription-types.md): Stream versus event-store consumption.
- [Hardening](hardening.md): Health probes, graceful shutdown, and operational limits.
- [Monitoring](monitoring.md): The metrics to alert on.
