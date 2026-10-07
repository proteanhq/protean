# Redis Stream Broker

The Redis Stream broker uses Redis Streams to provide durable, ordered message streaming with consumer group support. It's ideal for production environments requiring reliable message delivery.

## Overview

Redis Streams, introduced in Redis 5.0, provide a log-like data structure perfect for message streaming. The Redis broker uses these features to offer:

- **Persistent message storage** with configurable retention
- **Consumer groups** for distributed processing
- **Message acknowledgment** for reliable delivery
- **Ordered message processing** within streams
- **Automatic reconnection** and connection pooling

## Installation

The Redis broker requires the `redis` Python package:

```bash
# Install Protean with Redis support
pip install "protean[redis]"

# Or install Redis package separately
pip install "redis>=8.0.0,<8.2.0"
```

## Configuration

```toml
[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"

# Optional connection pool settings
max_connections = 10
socket_timeout = 5
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"redis"` for Redis Streams broker |
| `URI` | Required | Redis connection string |
| `max_connections` | Redis client default | Largest number of connections in the pool |
| `socket_timeout` | `None` | Seconds to wait when reading from a connection |
| `socket_connect_timeout` | `None` | Seconds to wait when connecting to Redis |
| `retry_on_timeout` | `false` | Retry a command when it times out |

The four pool settings are passed to the Redis client's connection pool as
they are. Leave a setting out to use the Redis client's default.

### Connection String Format

```
redis://[[username]:[password]@]host[:port][/database]

# Examples:
redis://localhost:6379/0  # Local Redis, database 0
redis://:password@redis.example.com:6379/1  # With password
redis://username:password@redis.example.com:6379  # With username and password
```

## Usage

The broker maps each operation to a Redis Streams command. This example needs
a running Redis server:

```python
# fragment
--8<-- "adapters/broker/redis/001.py:full"
```

`ack` returns `True`, and the next `get_next` for the group returns `None`.

## Capabilities

The Redis Stream broker provides the following capabilities:

- ✅ **ORDERED_MESSAGING** - Reliable messaging with ordering guarantees within streams
- ✅ **BLOCKING_READ** - Efficient blocking reads for new messages
- ✅ **DEAD_LETTER_QUEUE** - Failed messages routed to DLQ streams for inspection and replay
- ✅ **STREAM_PARTITIONING** - Partition-per-key streams for
  [`sequential_by`](../../server/sequential-by.md)

This includes:

- **Publish/subscribe** messaging
- **Consumer groups** for distributed processing
- **Message acknowledgment** (ACK/NACK) for reliable delivery
- **At-least-once delivery** guarantees
- **Message ordering** preservation within streams
- **Dead letter queue management**: List, inspect, replay, and purge failed messages via
  [`protean dlq`](../../cli/data/dlq.md) CLI or the
  [Observatory dashboard](../../server/observability.md)
- **Stream retention (XTRIM)**: When a subscription sets
  [`retention_maxlen`](../../server/subscription-types.md#stream-retention), the
  broker trims the stream after each batch. It uses `XTRIM MINID` at the slowest
  consumer group's position when several groups read the stream (so no unread
  entry is lost, though a group parked at `0-0` holds the floor down) and a
  fixed-size `XTRIM MAXLEN` when at most one group reads it (which can drop
  unread entries if that lone handler falls more than `retention_maxlen`
  behind). Both are approximate (Redis's `~`), trimming a node at a time. See
  [Stream retention](../../server/subscription-types.md#stream-retention) for the
  full caveats.

## Monitoring and Debugging

### Redis CLI Commands

Useful Redis commands for debugging:

```bash
# List all streams
redis-cli --scan --pattern "*"

# Get stream info
redis-cli XINFO STREAM user-events

# View consumer groups
redis-cli XINFO GROUPS user-events

# Check pending messages
redis-cli XPENDING user-events order-processor

# Read stream entries
redis-cli XRANGE user-events - + COUNT 10

# Monitor commands in real-time
redis-cli MONITOR
```

### Logging

The broker logs through the `protean.adapters.broker.redis` logger, and the
Redis client logs through the `redis` logger. Set either to `DEBUG` with the
standard `logging` module when you troubleshoot.

## Related pages

- Explore [Redis PubSub broker](./redis-pubsub.md) for simpler use cases
- Learn about [broker capabilities](./index.md#broker-capabilities) in detail
- Understand [custom broker development](./custom-brokers.md)
