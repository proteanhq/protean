# Event Stores

The Event Store port provides persistence for domain events and commands in
event-sourced systems. It serves a dual role: storing the event stream that
forms the source of truth for event-sourced aggregates, and acting as the
internal messaging backbone within a Protean-based application.

## Overview

An event store is fundamentally an append-only log. Events are written to named
streams and read back in order. Protean's `BaseEventStore` interface provides:

- **Stream writes** -- Append events and commands to named streams
- **Stream reads** -- Read messages from streams by position
- **Aggregate loading** -- Reconstitute event-sourced aggregates by replaying
  events
- **Temporal queries** -- Load an aggregate at a specific version or point in
  time
- **Snapshots** -- Create and restore aggregate snapshots for performance
- **Causation tracing** -- Traverse causal chains to understand how events
  triggered other events

## Available Event Stores

### Memory

The `memory` event store is the default. It stores events in Python data
structures and requires no external services. Ideal for development, testing,
and prototyping.

- **No external dependencies**
- All data is lost on process restart
- Full interface compliance -- same API as production event stores

### Message DB

[Message DB](./message-db.md) is a PostgreSQL-based event store that provides
durable, production-grade event storage with SQL-based stream operations.

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

# Production: Message DB
[event_store]
provider = "message_db"
database_uri = "postgresql://postgres:postgres@localhost:5433/message_store"
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | `"memory"` | Event store provider (`memory` or `message_db`) |
| `database_uri` | -- | Connection string (required for Message DB) |

## Core Operations

### Writing Events

Events are written to streams by the framework as part of aggregate
persistence. You do not typically call the event store directly:

```python
@domain.aggregate(is_event_sourced=True)
class Account:
    balance: Float(default=0.0)

    @apply
    def deposited(self, event: Deposited):
        self.balance += event.amount

    def deposit(self, amount):
        self.raise_(Deposited(amount=amount))
```

When the aggregate is persisted, Protean writes the raised events to the event
store automatically.

### Reading Streams

```python
# Read from the beginning of a stream
messages = domain.event_store.read("account-123")

# Read from a specific position
messages = domain.event_store.read("account-123", position=5)

# Read the last message in a stream
last = domain.event_store.read_last_message("account-123")
```

### Temporal Queries

Load an event-sourced aggregate at a specific version or point in time:

```python
# Load at version 5 (replay only the first 5 events)
account = domain.event_store.load_aggregate(Account, "123", at_version=5)

# Load as of a specific timestamp
from datetime import datetime
account = domain.event_store.load_aggregate(
    Account, "123",
    as_of=datetime(2024, 6, 15, 12, 0, 0)
)
```

See [Temporal Queries](../../../guides/change-state/temporal-queries.md) for
the full guide.

### Snapshots

Snapshots cache aggregate state to avoid replaying long event streams:

```python
# Create a snapshot for one aggregate
domain.event_store.create_snapshot(Account, "123")

# Create snapshots for all instances of an aggregate type
domain.event_store.create_snapshots(Account)
```

### Causation Tracing

Trace the causal chain of events to understand how one event led to another:

```python
# Find the root cause of an event
chain = domain.event_store.trace_causation(message_id="evt-456")

# Find all effects triggered by an event
effects = domain.event_store.trace_effects(message_id="evt-123")

# Build a full causation tree
tree = domain.event_store.build_causation_tree(message_id="evt-123")
```

See [Message Tracing](../../../guides/domain-behavior/message-tracing.md) for
the full guide.

## Monitoring

Use the `protean events` CLI to inspect event store contents:

```bash
# Read from a stream
protean events read account-123

# View aggregate history
protean events history --stream account-123

# Trace a causal chain
protean events trace --correlation-id "corr-abc"
```

See [`protean events`](../../cli/data/events.md) for the full CLI reference.

## Next Steps

- Learn about [Message DB](./message-db.md) for production event storage
- Explore [temporal queries](../../../guides/change-state/temporal-queries.md)
- Learn about [event sourcing](../../../concepts/architecture/event-sourcing.md)
- Set up the [`protean events` CLI](../../cli/data/events.md) for monitoring
