# Error Handling

This guide covers how Protean handles message processing failures across
all subscription types, including retry logic, dead letter queues (DLQ),
and recovery mechanisms.

For monitoring failed messages in production, see
[Monitoring](./monitoring.md). For the DLQ CLI commands, see
[DLQ Commands](../../reference/cli/data/dlq.md).

---

## Processing guarantees

Protean provides **at-least-once** delivery for all subscription types.
When a handler fails to process a message, the framework retries it a
configurable number of times before routing it to a dead letter queue or
marking it as exhausted.

No message is silently dropped. Every failure is logged, traced, and
either retried or preserved for manual inspection.

---

## Subscription error flows

Each subscription type handles failures differently based on its
underlying transport, but all share the same configuration model.

### StreamSubscription

Used with Redis Streams for event and command handlers when
`default_subscription_type = "stream"`.

**Flow**: Handler fails &rarr; NACK + retry &rarr; DLQ after exhaustion

1. Handler raises an exception.
2. Retry count incremented. If retries remain, the message is NACKed
   (returned to the Redis consumer group for re-delivery) after a
   configurable delay.
3. When retries are exhausted, the message is published to a DLQ stream
   (`{stream}:dlq`) with enriched metadata, then ACKed from the original
   stream.
4. If priority lanes are enabled, backfill stream failures route to
   `{stream}:backfill:dlq`.

**Deserialization errors** skip the retry pipeline entirely and go
straight to the DLQ, since retrying a malformed message cannot succeed.

```toml
[server.stream_subscription]
max_retries = 3
retry_delay_seconds = 1
enable_dlq = true
```

### EventStoreSubscription

Used with event stores (Memory, MessageDB) for event and command handlers
when `default_subscription_type = "event_store"` (the default).

**Flow**: Handler fails &rarr; position recorded &rarr; recovery pass retries

1. Handler raises an exception. The read position advances normally so the
   subscription is not blocked (avoids the poison-pill problem).
2. The failed position is recorded in-memory and checkpointed to the event
   store for durability.
3. A periodic recovery pass re-reads the original message from the event
   store and retries the handler.
4. On success, the position is marked as resolved. After exhausting
   `max_retries`, it is marked as exhausted and logged.

This approach leverages the event store's inherent durability — events
are immutable and always available for replay.

```toml
[server.event_store_subscription]
max_retries = 3
retry_delay_seconds = 1
enable_recovery = true
recovery_interval_seconds = 30
```

### BrokerSubscription

Used for subscribers that consume messages from external broker streams.

**Flow**: Handler fails &rarr; NACK + retry &rarr; DLQ after exhaustion

1. Subscriber raises an exception.
2. Retry count incremented. If retries remain, the message is NACKed
   after a configurable delay.
3. When retries are exhausted, the message is published to a DLQ stream
   (`{stream}:dlq`), ACKed from the original stream, and logged.

```toml
[server.broker_subscription]
max_retries = 3
retry_delay_seconds = 1
enable_dlq = true
```

### OutboxProcessor

Handles **outgoing** messages (domain &rarr; broker). Uses exponential
backoff with jitter. Failed messages stay in the outbox table with a
retry status — no DLQ is needed because the outbox table itself is
durable.

---

## Dead letter queue lifecycle

### How messages enter the DLQ

Messages enter the DLQ when:

- A handler/subscriber fails more times than `max_retries` allows.
- A message cannot be deserialized (StreamSubscription only).

Each DLQ message preserves the original payload and adds a
`_dlq_metadata` dict:

```json
{
  "original_stream": "orders",
  "original_id": "msg-abc-123",
  "consumer_group": "OrderHandler",
  "consumer": "OrderHandler-host-12345-a1b2c3",
  "failed_at": "2025-01-15T10:30:00+00:00",
  "retry_count": 3
}
```

### Inspecting and replaying

Use the `protean dlq` CLI commands:

```bash
# List all DLQ messages
protean dlq list --domain=my_domain

# Filter by subscription
protean dlq list --domain=my_domain --subscription=orders

# Inspect a specific message
protean dlq inspect MSG_ID --domain=my_domain

# Replay a single message back to the original stream
protean dlq replay MSG_ID --domain=my_domain --subscription=orders

# Replay all messages for a subscription
protean dlq replay-all --domain=my_domain --subscription=orders

# Purge all DLQ messages for a subscription
protean dlq purge --domain=my_domain --subscription=orders
```

### Disabling the DLQ

Set `enable_dlq = false` to discard messages after exhausting retries
instead of routing them to a DLQ. The message is still ACKed (removed
from pending) and logged as a warning.

```toml
[server.stream_subscription]
enable_dlq = false
```

---

## Configuration reference

All error-handling configuration lives under `[server]` in `domain.toml`:

| Key | Default | Description |
|-----|---------|-------------|
| `stream_subscription.max_retries` | 3 | Retry attempts before DLQ |
| `stream_subscription.retry_delay_seconds` | 1 | Delay between retries |
| `stream_subscription.enable_dlq` | true | Route to DLQ or discard |
| `event_store_subscription.max_retries` | 3 | Retry attempts before marking exhausted |
| `event_store_subscription.retry_delay_seconds` | 1 | Delay between recovery retries |
| `event_store_subscription.enable_recovery` | true | Enable periodic recovery pass |
| `event_store_subscription.recovery_interval_seconds` | 30 | Interval between recovery sweeps |
| `broker_subscription.max_retries` | 3 | Retry attempts before DLQ |
| `broker_subscription.retry_delay_seconds` | 1 | Delay between retries |
| `broker_subscription.enable_dlq` | true | Route to DLQ or discard |

Per-handler overrides can be passed via constructor arguments when
creating subscriptions programmatically.

---

## Custom error handling

Every handler and subscriber class can override `handle_error()` to
implement custom error logic:

```python
@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event):
        # ... processing logic
        pass

    @classmethod
    def handle_error(cls, exc, message):
        """Called when the handler raises an exception."""
        if isinstance(exc, ExternalServiceUnavailable):
            alert_ops_team(exc, message)
        logger.error(f"OrderEventHandler failed: {exc}")
```

The `handle_error()` callback receives the exception and the original
message. If `handle_error()` itself raises, the exception is caught and
logged — the engine continues processing.

---

## Trace events

The server emits trace events for observability:

| Event | When | Key metadata |
|-------|------|-------------|
| `message.acked` | Message processed successfully | `stream`, `handler` |
| `message.nacked` | Message failed, will retry | `stream`, `retry_count`, `max_retries` |
| `message.dlq` | Message moved to DLQ | `stream`, `dlq_stream`, `retry_count` |
| `handler.failed` | Handler raised an exception | `handler`, `error` |

These events are visible in the [Observatory](./monitoring.md) dashboard
and can be used for alerting.

---

## Operational runbooks

### Inspect a failure

```bash
# Find the failed message
protean dlq list --domain=my_domain

# Get full details
protean dlq inspect MSG_ID --domain=my_domain
```

Review the payload, error metadata, and retry count to determine the
root cause.

### Replay after fixing the bug

1. Fix the handler code that caused the failure.
2. Deploy the fix.
3. Replay the message:

```bash
protean dlq replay MSG_ID --domain=my_domain --subscription=orders
```

### Bulk replay

After a transient issue (network outage, dependency downtime) is
resolved:

```bash
protean dlq replay-all --domain=my_domain --subscription=orders
```

### Clear stale DLQ messages

If messages are no longer relevant (e.g., superseded by newer events):

```bash
protean dlq purge --domain=my_domain --subscription=orders
```

---

## Next steps

- [Monitoring](./monitoring.md) — Observatory dashboard and metrics
- [Logging](./logging.md) — Structured logging configuration
- [Production Deployment](./production-deployment.md) — Process management and scaling
- [Using Priority Lanes](./using-priority-lanes.md) — Route background workloads
