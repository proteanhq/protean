# Chapter 12: Going Async — The Server

Processing everything synchronously was fine for development. But a
customer placing an order should not wait while the system updates the
catalog projection, stocks inventory, and sends notifications. In this
chapter we will configure Redis as the message broker, enable the outbox
pattern for reliable delivery, and start the Protean server for
asynchronous event and command processing.

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

Update `domain.toml` to add a broker and switch to async processing:

```toml
debug = true

[databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL|postgresql://postgres:postgres@localhost:5432/bookshelf}"

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

You need Redis running alongside PostgreSQL:

```shell
docker run -d --name bookshelf-redis -p 6379:6379 redis:7-alpine
```

## Starting the Server

The Protean server is a long-running process that polls Redis Streams
and dispatches messages to handlers:

```shell
$ protean server --domain bookshelf
Starting Protean Engine...
Registered subscriptions:
  BookCommandHandler -> bookshelf::book:command (StreamSubscription)
  OrderCommandHandler -> bookshelf::order:command (StreamSubscription)
  BookEventHandler -> bookshelf::book (StreamSubscription)
  OrderEventHandler -> bookshelf::order (StreamSubscription)
  BookCatalogProjector -> bookshelf::book (StreamSubscription)
Engine running. Press Ctrl+C to stop.
```

Each handler gets its own **consumer group** in Redis. This means:

- Each handler maintains its own read position.
- Multiple instances of the same handler can run in parallel (horizontal
  scaling).
- A slow handler does not block other handlers.
- Failed messages are retried automatically before moving to the DLQ.

## How It All Fits Together

```
              ┌──────────┐
              │   API    │
              │ (FastAPI)│
              └─────┬────┘
                    │ domain.process(command)
              ┌─────▼────┐
              │  Outbox  │
              └─────┬────┘
                    │ (outbox processor publishes)
              ┌─────▼────┐
              │  Redis   │
              │ Streams  │
              └──┬──┬──┬─┘
                 │  │  │ (consumer groups)
         ┌───────┘  │  └───────┐
   ┌─────▼─────┐ ┌──▼──────┐ ┌▼──────────┐
   │ Command   │ │ Event   │ │ Projector │
   │ Handler   │ │ Handler │ │           │
   └───────────┘ └─────────┘ └───────────┘
```

The API returns immediately after writing the command to the outbox.
The server processes it asynchronously.

## Sending Commands Asynchronously

With async processing enabled, `domain.process()` publishes the command
to the command stream instead of executing it immediately:

```python
# This returns immediately — the command is queued
domain.process(
    AddBook(title="Gatsby", author="Fitzgerald", price_amount=12.99)
)
```

The server picks up the command from the Redis stream and dispatches it
to the command handler asynchronously.

## Verifying Async Processing

Start the server in one terminal and the API in another:

```shell
# Terminal 1 — start the server
$ protean server --domain bookshelf

# Terminal 2 — start the API
$ uvicorn bookshelf.api:app --reload

# Terminal 3 — add a book
$ curl -X POST http://localhost:8000/books \
  -H "Content-Type: application/json" \
  -d '{"title": "Dune", "author": "Frank Herbert", "price_amount": 15.99}'

# Wait a moment, then check the catalog
$ curl http://localhost:8000/catalog
```

The book appears in the catalog after the server processes the event
and the projector updates the projection — all asynchronously.

!!! tip "Testing with Sync Processing"
    For tests, override processing to sync mode in your `conftest.py`
    (as we did in Chapter 11). This ensures events and commands are
    processed immediately without needing Redis or the server running.

## What We Built

- **Redis** as the message broker with `domain.toml` configuration.
- The **outbox pattern** for reliable event delivery.
- **StreamSubscription** with consumer groups, retries, and DLQ.
- The **Protean server** (`protean server`) for async processing.
- An understanding of how events flow from the aggregate through the
  outbox to Redis Streams to handlers.

The system is now truly asynchronous. In the next chapter, we will add
a domain service to validate inventory before confirming orders.

## Next

[Chapter 13: Check Before You Ship →](13-domain-services.md)
