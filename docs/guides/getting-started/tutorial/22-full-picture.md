# Chapter 22: The Full Picture

We have built a complete online bookstore from scratch. Let's step back
and see the full architecture, review what we built, and look at where
to go from here.

## Architecture Overview

```
                              ┌──────────────┐
                              │   FastAPI    │
                              │  Endpoints   │
                              └──────┬───────┘
                                     │
                  ┌──────────────────┼──────────────────┐
                  │                  │                  │
          domain.process()    domain.view_for()     domain.view_for()
          (Commands)          (BookCatalog)         (StorefrontView)
                  │                  │                  │
                  ▼                  ▼                  ▼
           ┌──────────┐      ┌──────────┐       ┌──────────┐
           │ Command  │      │Projection│       │Projection│
           │ Handlers │      │(Read DB) │       │(Read DB) │
           └────┬─────┘      └──────────┘       └──────────┘
                │
           ┌────▼─────┐
           │Aggregates│
           │  (Book,  │
           │  Order,  │
           │Inventory,│
           │Shipping) │
           └────┬─────┘
                │ raise_() events
           ┌────▼─────┐
           │  Outbox   │──────► Redis Streams
           └──────────┘              │
                              ┌──────┼──────┐
                              │      │      │
                         ┌────▼─┐ ┌──▼───┐ ┌▼────────┐
                         │Event │ │Proj- │ │Process  │
                         │Handl.│ │ectors│ │Manager  │
                         └──────┘ └──────┘ └─────────┘
```

## Everything We Built

### Domain Elements

| Element | Count | Examples |
|---------|-------|---------|
| Aggregates | 4 | Book, Order, Inventory, Shipping |
| Entities | 1 | OrderItem |
| Value Objects | 2 | Money, Address |
| Commands | 8+ | AddBook, PlaceOrder, ConfirmOrder, ShipOrder, RestockInventory, ... |
| Events | 6+ | BookAdded, OrderConfirmed, OrderShipped, BookPriceUpdated, ... |
| Command Handlers | 3+ | BookCommandHandler, OrderCommandHandler, InventoryCommandHandler |
| Event Handlers | 2 | BookEventHandler, OrderEventHandler |
| Projections | 3 | BookCatalog, BookReport, StorefrontView |
| Projectors | 3 | BookCatalogProjector, BookReportProjector, StorefrontProjector |
| Domain Services | 1 | OrderFulfillmentService |
| Process Managers | 1 | OrderFulfillmentPM |
| Subscribers | 1 | BookSupplyWebhookSubscriber |

### CLI Commands Used

| Command | Purpose | Chapter |
|---------|---------|---------|
| `protean shell` | Interactive exploration | 1 |
| `protean database setup` | Create database tables | 8 |
| `protean database drop` | Drop database tables | 8 |
| `protean database truncate` | Clear all data | 8 |
| `protean server` | Start async processing engine | 12 |
| `protean events trace` | Trace message causation chains | 16 |
| `protean dlq list` | List dead-letter queue entries | 17 |
| `protean dlq inspect` | Inspect a failed message | 17 |
| `protean dlq replay` | Replay a failed message | 17 |
| `protean dlq purge` | Remove unrecoverable messages | 17 |
| `protean subscriptions status` | Check handler health | 18 |
| `protean observatory` | Real-time monitoring dashboard | 18 |

### CQRS Patterns Applied

| Pattern | How We Used It |
|---------|---------------|
| Command/Query Separation | Commands change state via `domain.process()`; `view_for()` reads projections |
| Event-Driven Side Effects | Events trigger inventory, notifications, projections |
| Read Model Projections | BookCatalog, BookReport, StorefrontView |
| Outbox Pattern | Reliable event delivery via Redis |
| Anti-Corruption Layer | Subscriber translates external data |
| Domain Services | Cross-aggregate validation (inventory check) |
| Process Manager / Saga | Multi-step fulfillment with compensation |
| Priority Lanes | Bulk imports without starving production |
| Dead Letter Queues | Failure recovery with fix-and-replay |

## Production Configuration Reference

A complete `domain.toml` for production:

```toml
[databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL}"

[brokers.default]
provider = "redis"
url = "${REDIS_URL}"

event_processing = "async"
command_processing = "async"
enable_outbox = true

[event_store]
provider = "memory"

[server]
default_subscription_type = "stream"
messages_per_tick = 100
priority_lanes = true

[server.stream_subscription]
blocking_timeout_ms = 100
max_retries = 3
retry_delay_seconds = 1
enable_dlq = true
```

## Running the Complete System

```shell
# 1. Start infrastructure
docker run -d --name bookshelf-db -e POSTGRES_DB=bookshelf -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15
docker run -d --name bookshelf-redis -p 6379:6379 redis:7-alpine

# 2. Set up the database
export PROTEAN_DOMAIN=bookshelf
protean database setup

# 3. Start the async processing server
protean server &

# 4. Start the API
uvicorn bookshelf.api:app --host 0.0.0.0 --port 8000 &

# 5. Start the observatory (optional)
protean observatory --port 9000 &
```

## Where to Go from Here

### Event Sourcing

Store events as the source of truth instead of snapshots. The
**[Event Sourcing Tutorial](../es-tutorial/index.md)** is a
comprehensive 22-chapter guide that builds a banking platform, covering
temporal queries, snapshots, event upcasting, and more.

### Deep Dives

- **[Guides](../../compose-a-domain/index.md)** — detailed coverage of
  each domain element
- **[Architecture](../../../concepts/architecture/ddd.md)** — DDD, CQRS,
  and Event Sourcing theory
- **[Adapters](../../../reference/adapters/index.md)** — database, broker,
  cache, and event store adapters
- **[Patterns](../../../patterns/index.md)** — aggregate sizing,
  idempotent handlers, validation layering
- **[CLI Reference](../../../reference/cli/index.md)** — all command-line
  tools

### Application Services (The DDD Alternative)

This tutorial used **Commands and Command Handlers** (the CQRS approach).
In the **pure DDD** approach, **Application Services** fill the same
role — they receive requests directly and coordinate the domain logic,
without the explicit command objects. See
[Application Services](../../change-state/application-services.md) and the
[DDD Pathway](../../pathways/ddd.md) for that reading order.

---

Congratulations! You have built and operated a complete production CQRS
system with Protean. The bookstore handles real traffic asynchronously,
validates business rules across aggregates, integrates with external
systems, and has full operational tooling for monitoring, debugging,
and recovery.

---
