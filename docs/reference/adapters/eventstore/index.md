# Event Stores

The Event Store port provides persistence for domain events and commands in
event-sourced systems. It serves a dual role: storing the event stream that
forms the source of truth for event-sourced aggregates, and acting as the
internal messaging backbone within a Protean-based application.

## Overview

An event store is fundamentally an append-only log. Events are written to named
streams and read back in order. Protean's `BaseEventStore` interface provides:

- **Stream writes**: Append events and commands to named streams
- **Stream reads**: Read messages from streams by position
- **Aggregate loading**: Reconstitute event-sourced aggregates by replaying
  events
- **Temporal queries**: Load an aggregate at a specific version or point in
  time
- **Snapshots**: Create and restore aggregate snapshots for performance
- **Causation tracing**: Traverse causal chains to understand how events
  triggered other events

## Available Event Stores

### Memory

The `memory` event store is the default. It stores events in Python data
structures and requires no external services. Ideal for development, testing,
and prototyping.

- **No external dependencies**
- All data is lost on process restart
- Full interface compliance, same API as production event stores

### Message DB

[Message DB](./message-db.md) is a PostgreSQL-based event store that provides
durable event storage with SQL-based stream operations.

- **Requires**: PostgreSQL with the Message DB extension
- Persistent, durable storage
- Production-ready with proven reliability

## Configuration

Event stores are configured in the `[event_store]` section of your domain
configuration:

```toml
# Default: in-memory event store
[event_store]
provider = "memory"
```

For production, point it at Message DB instead:

```toml
[event_store]
provider = "message_db"
database_uri = "postgresql://postgres:postgres@localhost:5433/message_store"
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | `"memory"` | Event store provider (`memory` or `message_db`) |
| `database_uri` | —  | Connection string (required for Message DB) |

## Core Operations

The examples below build on one another. They use a small banking domain with
an event-sourced `Account`.

### Writing Events

Events are written to streams by the framework as part of aggregate
persistence. You do not typically call the event store directly:

```python
--8<-- "adapters/eventstore/index/001.py:write"
```

When the aggregate is persisted, Protean writes the raised events to the event
store automatically.

### Reading Streams

The event store adapter is at `domain.event_store.store`. Each aggregate
instance has its own stream, named after the aggregate's stream category and
its identifier. For the account above, the stream is
`banking::account-<id>`.

```python
--8<-- "adapters/eventstore/index/001.py:read"
```

Positions count from 0, so `position=1` skips the first event.

### Temporal Queries

Load an event-sourced aggregate at a specific version or point in time:

```python
--8<-- "adapters/eventstore/index/001.py:temporal"
```

See [Temporal Queries](../../../guides/change-state/temporal-queries.md) for
the full guide.

### Snapshots

Snapshots cache aggregate state to avoid replaying long event streams:

```python
--8<-- "adapters/eventstore/index/001.py:snapshots"
```

`create_snapshot` returns `True` when it wrote a snapshot.
`create_snapshots` returns the number of aggregates it snapshotted.

### Causation Tracing

Trace the causal chain of events to understand how one message led to another.
`trace_causation` and `trace_effects` take a message id. `build_causation_tree`
takes a correlation id:

```python
--8<-- "adapters/eventstore/index/001.py:causation"
```

Here `chain` holds the `Deposit` command and then the `Deposited` event, and
`effects` holds the `Deposited` event.

See [Message Tracing](../../../guides/domain-behavior/message-tracing.md) for
the full guide.

## Monitoring

Use the `protean events` CLI to inspect event store contents:

```bash
# Read from a stream
protean events read "banking::account-<id>" --domain=my_domain

# View aggregate history
protean events history --aggregate=Account --id=<id> --domain=my_domain

# Trace a causal chain
protean events trace "<correlation-id>" --domain=my_domain
```

See [`protean events`](../../cli/data/events.md) for the full CLI reference.

## Related pages

- Learn about [Message DB](./message-db.md) for production event storage
- Explore [temporal queries](../../../guides/change-state/temporal-queries.md)
- Learn about [event sourcing](../../../concepts/architecture/event-sourcing.md)
- Set up the [`protean events` CLI](../../cli/data/events.md) for monitoring
