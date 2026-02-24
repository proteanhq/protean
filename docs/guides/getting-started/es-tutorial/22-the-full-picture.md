# Chapter 22: The Full Picture

We have built a complete digital banking platform from the ground up.
In this final chapter, we step back and survey the full architecture,
add a multi-aggregate projection, present the complete production
configuration, and review every tool at our disposal.

## A Multi-Aggregate Projection

So far, our projections consumed events from a single aggregate. But
what about an **activity feed** that combines account transactions
and transfers into one unified view?

```python
--8<-- "guides/getting-started/es-tutorial/ch22.py:activity_feed_projection"
```

```python
--8<-- "guides/getting-started/es-tutorial/ch22.py:activity_feed_projector"
```

The key difference is **`aggregates=[Account, Transfer]`** — this
projector subscribes to events from both aggregates, combining them
into a single projection.

## The Complete Production Configuration

```toml
# domain.toml (production)

[databases.default]
provider = "postgresql"
database_uri = "${DATABASE_URL}"

[brokers.default]
provider = "redis"
url = "${REDIS_URL}"

[event_store]
provider = "message_db"
database_uri = "${MESSAGE_DB_URL}"

event_processing = "async"
command_processing = "async"
enable_outbox = true
snapshot_threshold = 100

[server]
default_subscription_type = "stream"
default_subscription_profile = "production"
messages_per_tick = 100

[server.stream_subscription]
blocking_timeout_ms = 100
max_retries = 5
retry_delay_seconds = 2
enable_dlq = true

[server.priority_lanes]
enabled = true
threshold = 0
backfill_suffix = "backfill"
```

This configuration uses:

- **PostgreSQL** for projections and read models
- **Redis** for message brokering (streams, consumer groups)
- **MessageDB** (PostgreSQL-backed) for the event store
- **StreamSubscription** for all handlers
- **Priority lanes** for bulk migration isolation
- **DLQ** for failed message management

## CLI Reference

| Command | Purpose |
|---------|---------|
| `protean server --domain=fidelis` | Start the async processing engine |
| `protean observatory --domain=fidelis` | Launch the observability dashboard |
| `protean shell --domain=fidelis` | Interactive shell with domain context |
| `protean snapshot create --domain=fidelis` | Create aggregate snapshots |
| `protean projection rebuild --domain=fidelis` | Rebuild projections from events |
| `protean events read <stream>` | Read events from a stream |
| `protean events stats` | View domain-wide event statistics |
| `protean events search --type=<type>` | Search for events by type |
| `protean events history --aggregate=<A> --id=<id>` | View aggregate timeline |
| `protean events trace <correlation_id>` | Trace a causal chain |
| `protean dlq list` | List failed messages |
| `protean dlq inspect <id>` | Inspect a DLQ message |
| `protean dlq replay <id>` | Replay a failed message |
| `protean dlq replay-all --subscription=<name>` | Replay all failed messages |
| `protean dlq purge --subscription=<name>` | Purge DLQ messages |
| `protean subscriptions status` | Monitor subscription health |

## Architecture Overview

```
                         ┌──────────────┐
                         │   API Layer  │
                         │  (FastAPI)   │
                         └──────┬───────┘
                                │ domain.process(command)
                         ┌──────▼───────┐
                         │    Domain    │
                         │   Process    │
                         └──────┬───────┘
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
             ┌──────────┐ ┌──────────┐ ┌──────────┐
             │ Account  │ │ Transfer │ │  Funds   │
             │ Command  │ │ Command  │ │ Transfer │
             │ Handler  │ │ Handler  │ │   PM     │
             └────┬─────┘ └────┬─────┘ └────┬─────┘
                  │            │            │
                  ▼            ▼            ▼
             ┌──────────┐ ┌──────────┐
             │ Account  │ │ Transfer │
             │Aggregate │ │Aggregate │
             │  (ES)    │ │  (ES)    │
             └────┬─────┘ └────┬─────┘
                  │            │
                  ▼            ▼
         ┌─────────────────────────────┐
         │       Event Store           │
         │  (Memory / MessageDB)       │
         └─────────┬───────────────────┘
                   │ (outbox → broker)
         ┌─────────▼───────────────────┐
         │     Redis Streams           │
         │  (StreamSubscription)       │
         └──┬──────┬──────┬──────┬─────┘
            │      │      │      │
            ▼      ▼      ▼      ▼
       ┌────────┐ ┌────┐ ┌────┐ ┌──────────┐
       │Summary │ │Rpt │ │Feed│ │Compliance│
       │Project.│ │Proj│ │Proj│ │ Handler  │
       └────┬───┘ └──┬─┘ └──┬─┘ └──────────┘
            │        │      │
            ▼        ▼      ▼
       ┌────────────────────────┐
       │   Projection Store     │
       │   (PostgreSQL/Redis)   │
       └────────────────────────┘
```

## What We Built Across 22 Chapters

### Domain Modeling (Part I)
- Event-sourced aggregates with `@apply` handlers
- Domain methods that validate and raise events
- Commands as typed DTOs for external contracts
- Post-invariants for business rule enforcement
- Fluent testing DSL for comprehensive coverage

### Growing the Platform (Part II)
- Projections as read-optimized views
- Event handlers for side effects
- Async processing with Redis and StreamSubscription
- Process managers for cross-aggregate coordination
- Child entities inside aggregates

### Evolution (Part III)
- Event upcasting for schema evolution
- Snapshots for high-volume aggregate performance
- Temporal queries for historical state reconstruction
- Subscribers as anti-corruption layers
- Message enrichment for cross-cutting metadata

### Production Operations (Part IV)
- Fact events for reporting pipelines
- Correlation and causation tracing for auditing
- Dead-letter queue management for failure recovery
- Observatory and Prometheus for monitoring
- Priority lanes for migration isolation

### Mastery (Part V)
- Projection rebuilding from event history
- Event store exploration and querying
- Multi-aggregate projections
- Complete production configuration

## Continue Learning

- **[Guides](../../compose-a-domain/index.md)** — deep dives into each
  concept
- **[Architecture](../../../concepts/architecture/event-sourcing.md)** —
  event sourcing theory and internals
- **[Patterns](../../../patterns/index.md)** — aggregate design,
  idempotent handlers, event versioning
- **[Adapters](../../../reference/adapters/index.md)** — database,
  broker, cache, and event store adapters
- **[CLI Reference](../../../reference/cli/index.md)** — all
  command-line tools
- **[Testing](../../testing/event-sourcing-tests.md)** — advanced
  testing patterns for event-sourced systems

## Full Source

```python
--8<-- "guides/getting-started/es-tutorial/ch22.py:full"
```
