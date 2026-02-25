# Message DB

Message DB is a PostgreSQL-based event store that provides durable,
production-grade event storage. It is built on the
[Message DB](https://github.com/message-db/message-db) project and accessed
through the [message-db-py](https://pypi.org/project/message-db-py/) Python
client.

## Overview

Message DB is designed for:

- **Production environments** requiring durable event storage
- **Event sourcing** with full stream semantics
- **Multi-process deployments** where events must survive restarts
- **Temporal queries** and **causation tracing** at scale

It stores events in a PostgreSQL database using a dedicated schema optimized
for append-only stream operations.

## Installation

```bash
pip install message-db-py
```

You also need a running Message DB instance. The easiest way is with Docker:

```bash
# Using Protean's Docker Compose setup
make up

# Or run the Message DB container directly
docker run -d \
  --name message-db \
  -p 5433:5432 \
  -e POSTGRES_HOST_AUTH_METHOD=trust \
  ethangarofolo/message-db:1.2.6
```

## Configuration

```toml
[event_store]
provider = "message_db"
database_uri = "postgresql://postgres:postgres@localhost:5433/message_store"
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"message_db"` for Message DB |
| `database_uri` | Required | PostgreSQL connection string for the Message DB database |

### Connection String Format

```
postgresql://[username]:[password]@[host]:[port]/[database]

# Default for Protean's Docker Compose setup:
postgresql://postgres:postgres@localhost:5433/message_store
```

!!!note
    Message DB typically runs on port **5433** to avoid conflicts with a
    standard PostgreSQL instance on port 5432. Check your Docker Compose
    configuration for the correct port.

## Operations

Message DB supports all `BaseEventStore` operations:

| Operation | Supported | Notes |
|-----------|:---------:|-------|
| Write events | :white_check_mark: | Append to named streams |
| Read stream | :white_check_mark: | Read from any position |
| Read last message | :white_check_mark: | Single latest message |
| Load aggregate | :white_check_mark: | Event replay with version/time bounds |
| Snapshots | :white_check_mark: | Create and restore |
| Causation tracing | :white_check_mark: | Full causal chain traversal |
| Data reset | :white_check_mark: | Truncate all messages (testing) |

## Monitoring

Inspect event store contents using the CLI:

```bash
# Read events from a stream
protean events read account-123

# View aggregate event history
protean events history --stream account-123

# Trace a causal chain by correlation ID
protean events trace --correlation-id "corr-abc"

# View stream statistics
protean events stats
```

See [`protean events`](../../cli/data/events.md) for the full CLI reference.

## Limitations

- **Requires PostgreSQL** -- Message DB is built on PostgreSQL and requires a
  running instance with the Message DB extension installed.
- **Separate Database** -- Message DB uses its own PostgreSQL database
  (`message_store`), separate from your application database.
- **Docker Dependency** -- The recommended setup uses Docker. Installing
  Message DB directly on a PostgreSQL instance requires additional setup.

## Next Steps

- Learn about [temporal queries](../../../guides/change-state/temporal-queries.md)
- Explore [event sourcing architecture](../../../concepts/architecture/event-sourcing.md)
- Set up the [`protean events` CLI](../../cli/data/events.md) for monitoring
- Understand [snapshots](../../cli/data/snapshot.md) for performance
  optimization
