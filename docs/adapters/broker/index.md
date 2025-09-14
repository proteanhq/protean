# Brokers

Brokers enable asynchronous message passing between different parts of your system and external services. They decouple message producers from consumers, allowing for scalable, resilient architectures.

## Overview

The Broker port in Protean provides a unified interface for different message broker implementations. Each broker adapter implements this interface while providing access to the unique features of the underlying technology.

!!!note
    Protean internally uses an Event Store for domain events and commands within a bounded context. Brokers are primarily used for integration between different systems and for publishing messages to external consumers.

## Available Brokers

Protean includes several broker adapters out of the box:

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
from protean.port.broker import BrokerCapabilities

# Get a broker instance
broker = domain.brokers['default']

# Check for specific capabilities
if broker.has_capability(BrokerCapabilities.CONSUMER_GROUPS):
    # Use consumer group features
    messages = broker.read(
        stream="orders", 
        consumer_group="order-processor"
    )

# Check for any of multiple capabilities
if broker.has_any_capability(
    BrokerCapabilities.MESSAGE_ACKNOWLEDGEMENT | 
    BrokerCapabilities.MESSAGE_REJECTION
):
    # Handle acknowledgments
    broker.ack(stream="orders", message_id=msg_id)
```

## Basic Usage

### Publishing Messages

```python
from protean import Domain

domain = Domain(__name__)

# Publish to the default broker
domain.brokers.publish(
    stream="user-events",
    message={
        "event_type": "user.registered",
        "user_id": "123",
        "email": "user@example.com"
    }
)

# Publish to a specific broker
domain.brokers['notifications'].publish(
    stream="notifications",
    message={
        "type": "email",
        "to": "user@example.com",
        "subject": "Welcome!"
    }
)
```

### Consuming Messages

Messages are typically consumed through Subscribers:

```python
from protean import Domain, handle

domain = Domain(__name__)

@domain.subscriber(stream="user-events")
class UserEventSubscriber:
    @handle("user.registered")
    def send_welcome_email(self, message):
        # Process the message
        user_id = message["user_id"]
        email = message["email"]
        # Send welcome email...
```

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

Brokers provide robust error handling mechanisms:

```python
from protean.exceptions import BrokerConnectionError

try:
    domain.brokers.publish(stream="events", message=data)
except BrokerConnectionError as e:
    # Handle connection failures
    logger.error(f"Failed to publish: {e}")
    # Implement retry logic or fallback
```

## Health Checks

Monitor broker health and connectivity:

```python
# Check broker connection
broker = domain.brokers['default']
if broker.ping():
    print("Broker is healthy")

# Get detailed health statistics
health_stats = broker.health_stats()
print(f"Healthy: {health_stats.get('healthy', False)}")
print(f"Message counts: {health_stats.get('message_counts', {})}")
```

## Best Practices

1. **Always define a default broker** - Even if it's just the inline broker for development

2. **Check capabilities before using features** - Not all brokers support all features

3. **Handle broker failures gracefully** - Implement retry logic and circuit breakers

4. **Use appropriate brokers for different concerns**:

    - Inline for tests
    - Redis PubSub for notifications
    - Redis Streams for reliable event processing

5. **Monitor broker health** - Set up alerts for connection failures and high queue depths

6. **Consider message size limits** - Different brokers have different message size constraints

## Next Steps

- [Configure specific brokers](./inline.md) for your use case
- [Create custom broker adapters](./custom-brokers.md) for other technologies
- Learn about [subscribers and message processing](../../guides/consume-state/subscribers.md)
- Understand [event-driven architecture patterns](../../patterns/event-driven-architecture.md)