# Chapter 8: Going Async — The Server

Processing everything synchronously was fine for development. But in
production, a slow compliance check should not block the deposit
response. In this chapter we will configure Redis as the message broker,
enable the outbox pattern for reliable delivery, and start the Protean
server for asynchronous event processing.

## The Outbox Pattern

When an aggregate raises events, they need to reach event handlers and
projectors reliably. Protean uses the **outbox pattern**:

1. When the Unit of Work commits, events are written to both the
   **event store** and an **outbox table** atomically.
2. The **outbox processor** reads from the outbox table and publishes
   events to Redis Streams.
3. **StreamSubscriptions** consume from Redis Streams and dispatch to
   handlers.

This guarantees **at-least-once delivery** — events are never lost, even
if Redis is temporarily unavailable.

## Configuration

Create a `domain.toml` file in your project directory:

```toml
[brokers.default]
provider = "redis"
url = "${REDIS_URL|redis://localhost:6379/0}"

event_processing = "async"
command_processing = "async"
enable_outbox = true

[event_store]
provider = "memory"

[server]
default_subscription_type = "stream"
messages_per_tick = 100

[server.stream_subscription]
blocking_timeout_ms = 100
max_retries = 3
retry_delay_seconds = 1
enable_dlq = true
```

Key settings:

- **`brokers.default.provider = "redis"`** — use Redis as the message
  broker.
- **`event_processing = "async"`** — events flow through the broker
  instead of being processed inline.
- **`enable_outbox = true`** — reliable delivery via the outbox pattern.
- **`default_subscription_type = "stream"`** — use `StreamSubscription`
  (Redis Streams with consumer groups) for all handlers.
- **`enable_dlq = true`** — failed messages go to a dead-letter queue
  instead of being lost.

## Starting Docker Services

You need Redis running:

```shell
docker run -d --name fidelis-redis -p 6379:6379 redis:7-alpine
```

Or use Protean's Docker Compose (if available):

```shell
make up
```

## Starting the Server

The Protean server is a long-running process that polls Redis Streams
and dispatches messages to handlers:

```shell
$ protean server --domain=fidelis
Starting Protean Engine...
Registered subscriptions:
  AccountCommandHandler -> fidelis::account:command (StreamSubscription)
  AccountSummaryProjector -> fidelis::account (StreamSubscription)
  ComplianceAlertHandler -> fidelis::account (StreamSubscription)
  NotificationHandler -> fidelis::account (StreamSubscription)
Engine running. Press Ctrl+C to stop.
```

Each handler gets its own **consumer group** in Redis. This means:

- Each handler maintains its own read position
- Multiple instances of the same handler can run in parallel (horizontal
  scaling)
- A slow handler does not block other handlers
- Failed messages are retried automatically before moving to the DLQ

## How StreamSubscription Works

```
                    ┌─────────────┐
                    │ Event Store │
                    └──────┬──────┘
                           │ (events written)
                    ┌──────▼──────┐
                    │   Outbox    │
                    └──────┬──────┘
                           │ (outbox processor publishes)
                    ┌──────▼──────┐
                    │Redis Stream │
                    │(fidelis::   │
                    │  account)   │
                    └──┬───┬───┬──┘
                       │   │   │ (consumer groups)
           ┌───────────┘   │   └───────────┐
    ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
    │  Projector  │ │ Compliance  │ │Notification │
    │  Consumer   │ │  Consumer   │ │  Consumer   │
    │   Group     │ │   Group     │ │   Group     │
    └─────────────┘ └─────────────┘ └─────────────┘
```

Each consumer group reads independently. If the compliance handler is
slow, the projector and notification handler continue at full speed.

## StreamSubscription vs. EventStoreSubscription

| | StreamSubscription | EventStoreSubscription |
|---|-------------------|----------------------|
| **Backed by** | Redis Streams | Event store directly |
| **Delivery** | At-least-once via consumer groups | At-least-once via position tracking |
| **DLQ** | Built-in | Not yet available |
| **Retries** | Configurable with backoff | None |
| **Use for** | Production handlers | Development, projections |

For production systems, **StreamSubscription is the recommended
choice**. It provides consumer groups, automatic retries, dead-letter
queues, and horizontal scaling.

## Sending Commands Asynchronously

With async processing enabled, `domain.process()` publishes the command
to the command stream instead of executing it immediately:

```python
# This returns immediately — the command is queued
domain.process(
    MakeDeposit(account_id=account_id, amount=500.00, reference="paycheck")
)
```

The server picks up the command from the Redis stream and dispatches it
to the command handler asynchronously.

## What We Built

- **Redis** as the message broker with `domain.toml` configuration.
- The **outbox pattern** for reliable event delivery.
- **StreamSubscription** with consumer groups, retries, and DLQ.
- The **Protean server** (`protean server`) for async processing.
- An understanding of how events flow from the aggregate through the
  outbox to Redis Streams to handlers.

The system is now truly asynchronous. In the next chapter, we will add
account-to-account transfers — a multi-aggregate workflow that requires
a process manager.

## Next

[Chapter 9: Transferring Funds →](09-transferring-funds.md)
