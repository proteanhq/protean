# Brokers

Brokers enable asynchronous message passing between different parts of your system and external services. They decouple message producers from consumers, allowing for scalable, resilient architectures.

## Overview

The Broker port in Protean provides a unified interface for different message broker implementations. Each broker adapter implements this interface while providing access to the unique features of the underlying technology.

!!!note
    Protean internally uses an Event Store for domain events and commands within a bounded context. Brokers are primarily used for integration between different systems and for publishing messages to external consumers.

## Available Brokers

Protean includes several broker adapters:

### Inline Broker

The `inline` broker processes messages synchronously within the same process. It's ideal for development, testing, and simple applications that don't require distributed messaging.

- **Use cases**: Development, testing, small applications
- **Capabilities**: Basic pub/sub, simple queuing, reliable messaging
- **No external dependencies required**

### Redis Stream Broker

The `redis` broker uses Redis Streams for durable message streaming with consumer groups support.

- **Use cases**: Production environments requiring reliable message delivery
- **Capabilities**: Consumer groups, message acknowledgment, ordered delivery
- **Requires**: Redis 5.0+

### Redis PubSub Broker

The `redis_pubsub` broker uses Redis Lists for simple queuing with basic consumer group support.

- **Use cases**: Simple message distribution, development environments
- **Capabilities**: Simple queuing with position tracking
- **Requires**: Redis 2.0+

## Configuration

Brokers are configured in your domain configuration file (`domain.toml` or `.domain.toml`):

```toml
# Default broker configuration (required)
[brokers.default]
provider = "inline"

# Additional named brokers
[brokers.notifications]
provider = "redis_pubsub"
URI = "redis://localhost:6379/0"

[brokers.analytics]
provider = "redis"
URI = "redis://localhost:6379/1"
```

Each broker configuration must specify:

- `provider`: The broker adapter to use (`inline`, `redis`, `redis_pubsub`, or custom)
- Additional provider-specific options (like `URI` for Redis brokers)

!!!important
    You must define a `default` broker in your configuration. This broker will be used unless a specific broker is requested.

## Broker Capabilities

Brokers in Protean declare their capabilities through a capability-based system. This allows you to understand what features each broker supports and write code that adapts to available capabilities.

### Capability Tiers

Brokers are organized into capability tiers, each building upon the previous:

1. **BASIC_PUBSUB**: Fire-and-forget message publishing
2. **SIMPLE_QUEUING**: Basic pub/sub + consumer groups
3. **RELIABLE_MESSAGING**: Simple queuing + acknowledgment/rejection
4. **ORDERED_MESSAGING**: Reliable messaging + message ordering
5. **ENTERPRISE_STREAMING**: Full features including DLQ, replay, partitioning

### Checking Capabilities

You can check broker capabilities at runtime:

```python
--8<-- "adapters/broker/index/001.py:full"
```

## Basic Usage

### Consuming Messages

Messages are typically consumed through Subscribers. A subscriber is a class
with a `__call__` method that receives the message as a dict. Register
subscribers before you initialize the domain.

By default, a published message waits for the message processing engine (see
below). With `message_processing = "sync"`, the inline broker delivers each
message to its subscribers as soon as it is published. The examples on this
page use that setting:

```python
--8<-- "adapters/broker/index/002.py:subscriber"
```

### Publishing Messages

```python
--8<-- "adapters/broker/index/002.py:publish"
```

After the first publish, the subscriber above has recorded
`user@example.com`.

## Message Processing Engine

Protean includes a built-in message processing engine that handles message consumption from brokers:

```bash
# Start the message processing engine
protean server

# With specific domain
protean --domain path.to.domain server
```

The engine automatically:

- Discovers all registered subscribers
- Manages consumer groups
- Handles message acknowledgment
- Implements retry logic based on broker capabilities
- Provides graceful shutdown

## Error Handling

`publish` rejects an empty message with a `ValidationError` before it reaches
the broker:

```python
--8<-- "adapters/broker/index/002.py:errors"
```

Here `error` is `{"message": ["Message cannot be empty"]}`.

On a connection error, Protean tries to reconnect. If it reconnects, it retries
the operation once. If it cannot reconnect, or the retry fails, the error from
the broker's client library is raised (for Redis, a
`redis.exceptions.ConnectionError`).

## Health Checks

Monitor broker health and connectivity. `health_stats()` returns a dict with
`status` (`"healthy"`, `"degraded"` or `"unhealthy"`), `connected`,
`last_ping_ms`, `uptime_seconds` and a broker-specific `details` dict:

```python
--8<-- "adapters/broker/index/002.py:health"
```

## Configuring a broker

1. **A default broker is required**: Even if it's just the inline broker for development

2. **Check capabilities before using features**: Not all brokers support all features

3. **Handle broker failures gracefully**: Implement retry logic and circuit breakers

4. **Use appropriate brokers for different concerns**:

    - Inline for tests
    - Redis PubSub for notifications
    - Redis Streams for reliable event processing

5. **Monitor broker health**: Set up alerts for connection failures and high queue depths

6. **Consider message size limits**: Different brokers have different message size constraints

## Broker Registry

Brokers register themselves through Python
[entry points](https://packaging.python.org/en/latest/specifications/entry-points/)
under the `protean.brokers` group. This means third-party broker packages can
be pip-installed and automatically discovered by Protean.

Protean's built-in brokers are registered in `pyproject.toml`:

```toml
[project.entry-points."protean.brokers"]
inline = "protean.adapters.broker.inline:register"
redis = "protean.adapters.broker.redis:register"
redis_pubsub = "protean.adapters.broker.redis_pubsub:register"
```

Each entry point maps a broker name to a `register()` function. The function
is called on first access and registers the broker class path with the
`BrokerRegistry`. Dependencies are wrapped in `try/except` so that brokers
with uninstalled optional dependencies are silently skipped.

External packages can register their own brokers the same way. See
[Custom Brokers](./custom-brokers.md) for a complete guide including a Kafka
example.

## Related pages

- [Configure specific brokers](./inline.md) for your use case
- [Create custom broker adapters](./custom-brokers.md) for other technologies
- Learn about [subscribers and message processing](../../../guides/consume-state/subscribers.md)
