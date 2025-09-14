# Redis Stream Broker

The Redis Stream broker uses Redis Streams to provide durable, ordered message streaming with consumer group support. It's ideal for production environments requiring reliable message delivery.

## Overview

Redis Streams, introduced in Redis 5.0, provide a log-like data structure perfect for message streaming. The Redis broker leverages these features to offer:

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
pip install redis>=5.0.0
```

## Configuration

```toml
[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"
IS_ASYNC = true  # Optional: Use async processing (default: false)
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"redis"` for Redis Streams broker |
| `URI` | Required | Redis connection string |
| `IS_ASYNC` | `false` | Enable asynchronous message processing |

### Connection String Format

```
redis://[[username]:[password]@]host[:port][/database]

# Examples:
redis://localhost:6379/0  # Local Redis, database 0
redis://:password@redis.example.com:6379/1  # With password
redis://username:password@redis.example.com:6379  # With username and password
```

## Capabilities

The Redis Stream broker provides the following capabilities:

- ✅ **ORDERED_MESSAGING** - Reliable messaging with ordering guarantees within streams
- ✅ **BLOCKING_READ** - Efficient blocking reads for new messages

This includes:
- **Publish/subscribe** messaging
- **Consumer groups** for distributed processing
- **Message acknowledgment** (ACK/NACK) for reliable delivery
- **At-least-once delivery** guarantees
- **Message ordering** preservation within streams

Not supported:
- ❌ **Dead Letter Queue (DLQ)** - Not implemented
- ❌ **Stream partitioning** - Not a native feature
- ❌ **Message replay** - Not implemented

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

Enable detailed logging for troubleshooting:

```python
import logging

# Enable Redis broker logging
logging.getLogger('protean.adapters.broker.redis').setLevel(logging.DEBUG)
logging.getLogger('redis').setLevel(logging.DEBUG)

# Custom instrumentation
class InstrumentedRedisBroker(RedisBroker):
    def _publish(self, stream: str, message: dict) -> str:
        start = time.time()
        try:
            result = super()._publish(stream, message)
            duration = time.time() - start
            metrics.histogram('broker.publish.duration', duration, tags={'stream': stream})
            return result
        except Exception as e:
            metrics.increment('broker.publish.error', tags={'stream': stream, 'error': str(e)})
            raise
```

## Next Steps

- Explore [Redis PubSub broker](./redis-pubsub.md) for simpler use cases
- Learn about [broker capabilities](./index.md#broker-capabilities) in detail
- Understand [custom broker development](./custom-brokers.md)
- Read about [message processing patterns](../../patterns/message-processing.md)