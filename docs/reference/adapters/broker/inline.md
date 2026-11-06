# Inline Broker

The Inline broker is an in-memory message broker that keeps messages within the
same process. With `message_processing = "sync"`, it delivers each message to
its subscribers as soon as it is published. It is the default broker in
Protean. It requires no external dependencies.

## Overview

The Inline broker is designed for:

- **Development environments** where a simple setup matters most
- **Testing scenarios** where deterministic behavior is required
- **Small applications** that don't need distributed messaging
- **Prototyping** when you want to defer technology decisions

The Inline broker maintains messages in memory using Python data structures:

- Messages are stored in dictionaries keyed by stream name
- Consumer groups track message processing state
- All data is lost when the process terminates

## Configuration

```toml
[brokers.default]
provider = "inline"

# Optional configuration for retry behavior
max_retries = 3  # Maximum retry attempts for failed messages
retry_delay = 1.0  # Initial retry delay in seconds
backoff_multiplier = 2.0  # Exponential backoff multiplier
message_timeout = 300.0  # Message timeout in seconds (5 minutes default)
enable_dlq = true  # Enable dead letter queue for failed messages
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"inline"` for Inline broker |
| `max_retries` | `3` | Maximum retry attempts for failed messages |
| `retry_delay` | `1.0` | Initial retry delay in seconds |
| `backoff_multiplier` | `2.0` | Multiplier for exponential backoff |
| `message_timeout` | `300.0` | Timeout for message processing (seconds) |
| `enable_dlq` | `true` | Enable dead letter queue |

## Capabilities

The Inline broker supports the following capabilities:

- ✅ **BASIC_PUBSUB** - Fire-and-forget message publishing
- ✅ **SIMPLE_QUEUING** - Consumer groups for message distribution
- ✅ **RELIABLE_MESSAGING** - Message acknowledgment and rejection
- ✅ **DEAD_LETTER_QUEUE** - Failed messages routed to DLQ for inspection and replay
- ❌ **ORDERED_MESSAGING** - Not supported
- ❌ **ENTERPRISE_STREAMING** - Not supported

## Usage Examples

### Basic Publishing and Subscribing

A subscriber is a class with a `__call__` method that receives each message as
a dict:

```python
--8<-- "adapters/broker/inline/001.py:basic"
```

The subscriber prints `User created: John Doe`.

### Testing with Inline Broker

The Inline broker is ideal for testing as it provides deterministic,
synchronous behavior. Use Protean's `DomainFixture` to set up and tear down the
domain in your tests:

```python
--8<-- "adapters/broker/inline/002.py:full"
```

### Consumer Groups

Consumer groups read a stream independently. Each group receives every message.
Within a group, the broker hands out each message once:

```python
--8<-- "adapters/broker/inline/001.py:consumer_groups"
```

## Limitations

- **No Persistence**
    - Messages are lost on process restart
    - No durability guarantees
    - Cannot recover from crashes
- **No Distribution**
    - Cannot scale across multiple processes
    - All processing happens in the same Python process
    - Not suitable for high-throughput scenarios
- **Does not guarantee message order**
    - Messages may be processed out of order
    - No support for partitioned delivery
    - Cannot ensure strict message sequencing
- **Offers only basic error recovery**
    - Basic retry support with configurable max retries
    - Dead letter queue stores failed messages in memory (lost on restart)
    - DLQ messages can be listed, inspected, replayed, and purged via
      [`protean dlq`](../../cli/data/dlq.md) CLI or the
      [Observatory dashboard](../../server/observability.md)

## Migration Path

The Inline broker is designed to be easily replaced with production-ready brokers:

```toml
# Development configuration
[dev.brokers.default]
provider = "inline"

# Production configuration (same code works!)
[prod.brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"
```

Your application code remains unchanged when switching brokers, as long as you:

1. Only use capabilities supported by both brokers
2. Catch the errors that each broker raises in your code
3. Test with the production broker before deployment

## Related pages

- Learn about [Redis broker](./redis.md) for production use
- Understand [broker capabilities](./index.md#broker-capabilities) in detail
- Explore [custom broker development](./custom-brokers.md)
