# Redis PubSub Broker

The Redis PubSub broker uses Redis Lists for simple queuing with consumer groups. Despite its name, it doesn't use Redis's native Pub/Sub mechanism but implements a queue-based messaging system.

## Overview

This broker uses Redis Lists as queues where:

- **Publishers** append messages to Redis lists using `rpush`
- **Subscribers** read messages from lists using `lindex` with position tracking
- **Messages are persisted** in Redis lists until Redis is flushed
- **Consumer groups** track their position in each list independently

## Installation

The Redis PubSub broker requires the `redis` Python package:

```bash
# Install Protean with Redis support
pip install "protean[redis]"

# Or install Redis package separately
pip install "redis>=8.0.0,<8.2.0"
```

## Configuration

```toml
[brokers.notifications]
provider = "redis_pubsub"
URI = "redis://localhost:6379/0"
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"redis_pubsub"` for Redis PubSub broker |
| `URI` | Required | Redis connection string |

## Capabilities

The Redis PubSub broker provides simple queuing capabilities:

- ✅ **BASIC_PUBSUB** - Publish and subscribe
- ✅ **SIMPLE_QUEUING** - Consumer groups with position tracking
- ❌ **RELIABLE_MESSAGING** - No acknowledgments (ack/nack not supported)
- ❌ **ORDERED_MESSAGING** - No ordering guarantees
- ❌ **ENTERPRISE_STREAMING** - Not supported

## Usage Examples

The examples on this page need a running Redis server. They build on one
another.

### Basic Publishing

Configure the broker, then publish to a stream. Each stream is a Redis list
with the same name:

```python
# fragment
--8<-- "adapters/broker/redis-pubsub/001.py:setup"
--8<-- "adapters/broker/redis-pubsub/001.py:publish"
```

### Subscribing to Streams

A subscriber is a class with a `__call__` method that receives each message as
a dict. Name the broker with `broker=`, and register the subscriber before you
initialize the domain:

```python
# fragment
--8<-- "adapters/broker/redis-pubsub/001.py:subscribe"
```

With `message_processing = "sync"` (set in the configuration above), the
subscriber runs as soon as the message is published. Here `pushed` becomes
`[("123", "New Message")]`.

A subscriber reads one stream by its exact name. Stream names are not
patterns, so `stream="chat:*"` reads a list literally named `chat:*`.

### Consumer Groups

Each consumer group keeps its own position in the list, in a Redis key named
`position:<stream>:<group>`. Two groups read the same messages:

```python
# fragment
--8<-- "adapters/broker/redis-pubsub/001.py:groups"
```

The broker does not track whether a message was processed. `ack` and `nack`
log a warning and return `False`.

## Limitations and Considerations

### Limited Persistence

Messages stay in Redis lists until Redis is flushed. If Redis restarts without
persistence (RDB snapshots or AOF) turned on, the messages are lost. For
durable messaging, use the [Redis Streams broker](./redis.md) with persistence
turned on.

### No Acknowledgment Support

`publish` returns a message identifier, but there is no delivery confirmation.
A consumer group moves its position forward when it reads a message, whether
or not a subscriber handled it.

### Position Tracking

The group positions are Redis keys. If they are deleted (for example by
`FLUSHDB`), every group reads its streams from the start again.

## Performance Considerations

### Message Size

Keep messages small. Put large payloads in a store such as S3, and publish a
reference to them (a URL and a size) instead of the payload.

### Stream Naming

Use hierarchical names such as `user:123:notifications` or
`system:alerts:critical`, so `redis-cli --scan --pattern` can find related
streams.

### Message Processing

Messages are processed sequentially per consumer group. Each group maintains its own position counter in Redis.

## Monitoring and Debugging

### Redis CLI Commands

The broker stores messages in lists, so the list commands show its state:

```bash
# List streams and group positions
redis-cli --scan --pattern "*"

# Count the messages in a stream
redis-cli LLEN user:notifications

# Read the first ten messages
redis-cli LRANGE user:notifications 0 9

# Show a group's position in a stream
redis-cli GET position:user:notifications:billing
```

### Logging

The broker logs through the `protean.adapters.broker.redis_pubsub` logger. Set
it to `DEBUG` with the standard `logging` module when you troubleshoot.

### Health Checks

`health_stats()` returns the common health dict. The Redis details, such as
`connected_clients` and `used_memory_human`, are under `details`:

```python
# fragment
--8<-- "adapters/broker/redis-pubsub/001.py:health"
```

## Migration Strategies

### To Redis Streams

When you need persistence and reliability, change the provider:

```toml
# Before: Redis PubSub
[brokers.notifications]
provider = "redis_pubsub"
URI = "redis://localhost:6379/0"
```

```toml
# After: Redis Streams
[brokers.notifications]
provider = "redis"
URI = "redis://localhost:6379/0"
```

Subscribers stay the same. Two things change:

1. `ack` and `nack` work, so a message that is not acknowledged stays pending
   for its group.
2. `publish` returns a Redis Streams entry id such as `1700000000000-0`.

## Working with Redis PubSub

### Use for Simple Queuing

Redis PubSub broker is suitable for:

- Simple message distribution
- Development and testing
- Scenarios where ack/nack isn't needed
- Basic consumer group functionality

Not suitable for:

- Critical business events requiring acknowledgment
- Complex message routing
- Scenarios requiring message replay
- High-throughput production systems

## Comparison with Other Brokers

| Feature | Redis PubSub | Redis Streams | Inline |
|---------|--------------|---------------|--------|
| Persistence | Redis Lists | Yes (durable) | No |
| Delivery Guarantee | None | At-least-once | Best-effort |
| Consumer Groups | Basic | Advanced | Yes |
| Message Ordering | No | Yes | No |
| Acknowledgments | No | Yes | Yes |
| Performance | High | High | Very High |
| Use Case | Simple Queuing | Event Streaming | Development |

## Related pages

- Learn about [Redis Streams broker](./redis.md) for reliable messaging
- Understand [broker capabilities](./index.md#broker-capabilities) in detail
- Explore [custom broker development](./custom-brokers.md)
