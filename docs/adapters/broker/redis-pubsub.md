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
pip install redis>=2.0.0
```

## Configuration

```toml
[brokers.notifications]
provider = "redis_pubsub"
URI = "redis://localhost:6379/0"
IS_ASYNC = true  # Optional: Use async processing (default: false)
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | Required | Must be `"redis_pubsub"` for Redis PubSub broker |
| `URI` | Required | Redis connection string |
| `IS_ASYNC` | `false` | Enable asynchronous message processing |

## Capabilities

The Redis PubSub broker provides simple queuing capabilities:

- ❌ **BASIC_PUBSUB** - Not supported
- ✅ **SIMPLE_QUEUING** - Consumer groups with position tracking
- ❌ **RELIABLE_MESSAGING** - No acknowledgments (ack/nack not supported)
- ❌ **ORDERED_MESSAGING** - No ordering guarantees
- ❌ **ENTERPRISE_STREAMING** - Not supported

## Usage Examples

### Basic Publishing

```python
from protean import Domain

domain = Domain(__name__)
domain.config['brokers'] = {
    'notifications': {
        'provider': 'redis_pubsub',
        'URI': 'redis://localhost:6379/0'
    }
}
domain.init()

# Publish a notification
domain.brokers['notifications'].publish(
    stream="user:notifications",  # Channel name in Redis
    message={
        "type": "notification",
        "user_id": "123",
        "title": "New Message",
        "body": "You have a new message!"
    }
)
```

### Subscribing to Channels

```python
@domain.subscriber(
    stream="user:notifications",
    broker="notifications"
)
class NotificationSubscriber:
    @handle("notification")
    def send_push_notification(self, message):
        # Send push notification to user's device
        push_service.send(
            user_id=message["user_id"],
            title=message["title"],
            body=message["body"]
        )
```


### Message Distribution

Useful for distributing messages across consumer groups:

```python
# WebSocket handler example
class ChatRoom:
    def __init__(self, room_id: str):
        self.room_id = room_id
        self.channel = f"chat:{room_id}"
    
    def send_message(self, user_id: str, message: str):
        # Broadcast to all connected clients
        domain.brokers['notifications'].publish(
            stream=self.channel,
            message={
                "type": "chat.message",
                "user_id": user_id,
                "message": message,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

# Subscribe to chat messages
@domain.subscriber(
    stream="chat:*",
    broker="notifications"
)
class ChatSubscriber:
    @handle("chat.message")
    async def relay_to_websocket(self, message):
        # Send to WebSocket clients
        await websocket_manager.broadcast(
            room=message["stream"].split(":")[1],
            data=message
        )
```

## Use Cases

### 1. Real-time Notifications

```python
# User notification system
class NotificationService:
    def notify_user(self, user_id: str, notification: dict):
        domain.brokers['notifications'].publish(
            stream=f"user:{user_id}:notifications",
            message={
                "type": "notification",
                **notification
            }
        )
    
    def notify_followers(self, user_id: str, update: dict):
        # Notify all followers about user activity
        for follower_id in get_followers(user_id):
            self.notify_user(follower_id, update)
```

### 2. Cache Invalidation

```python
# Coordinate cache invalidation across services
@domain.subscriber(stream="cache:invalidation", broker="notifications")
class CacheInvalidator:
    @handle("invalidate")
    def clear_cache(self, message):
        cache_key = message["key"]
        cache.delete(cache_key)
        logger.info(f"Invalidated cache key: {cache_key}")

# Trigger cache invalidation
def update_user_profile(user_id: str, data: dict):
    # Update database
    user_repo.update(user_id, data)
    
    # Broadcast cache invalidation
    domain.brokers['notifications'].publish(
        stream="cache:invalidation",
        message={
            "type": "invalidate",
            "key": f"user:{user_id}"
        }
    )
```

### 3. Metrics and Monitoring

```python
# Collect metrics from distributed services
@domain.subscriber(stream="metrics:*", broker="notifications")
class MetricsCollector:
    @handle("metric")
    def collect_metric(self, message):
        metric_name = message["name"]
        value = message["value"]
        tags = message.get("tags", {})
        
        # Send to monitoring system
        statsd.gauge(metric_name, value, tags=tags)

# Emit metrics
def track_api_latency(endpoint: str, duration: float):
    domain.brokers['notifications'].publish(
        stream="metrics:api",
        message={
            "type": "metric",
            "name": "api.latency",
            "value": duration,
            "tags": {"endpoint": endpoint}
        }
    )
```

## Limitations and Considerations

### Limited Persistence

Messages are stored in Redis lists but have no durability guarantees:

```python
# Messages persist in Redis lists, but lost if Redis restarts without persistence
domain.brokers['notifications'].publish(
    stream="important-events",
    message={"type": "critical", "data": "Stored in Redis list"}
)

# For better durability, use Redis Streams with AOF persistence
domain.brokers['reliable'].publish(  # Redis Stream broker
    stream="important-events",
    message={"type": "critical", "data": "More durable with Redis Streams"}
)
```

### No Acknowledgment Support

```python
# Messages cannot be acknowledged or rejected
# The broker doesn't track if messages were successfully processed
result = domain.brokers['notifications'].publish(
    stream="notifications",
    message={"type": "alert"}
)
# result is just a message identifier, no delivery confirmation
```

### Simple Consumer Groups

Consumer groups are supported but with limitations:

```python
# Consumer groups track position in the list independently
@domain.subscriber(stream="orders", broker="notifications", consumer_group="group1")
class OrderProcessor1:
    @handle("order.created")
    def process(self, msg):
        print("Group 1 processing")

@domain.subscriber(stream="orders", broker="notifications", consumer_group="group2")  
class OrderProcessor2:
    @handle("order.created")
    def process(self, msg):
        print("Group 2 processing")  # Different group, processes same messages
```

### Position Tracking

Consumer groups track their position, but positions can be lost:

```python
# Implement reconnection logic
class ResilientSubscriber:
    def __init__(self):
        self.connected = False
        self.reconnect_attempts = 0
    
    def connect(self):
        while self.reconnect_attempts < 5:
            try:
                # Subscribe to channel
                self.subscribe()
                self.connected = True
                break
            except ConnectionError:
                self.reconnect_attempts += 1
                time.sleep(2 ** self.reconnect_attempts)
```

## Performance Considerations

### Message Size

Keep messages small for optimal performance:

```python
# Bad: Large message
domain.brokers['notifications'].publish(
    stream="updates",
    message={
        "type": "update",
        "data": large_binary_data  # Avoid!
    }
)

# Good: Reference to data
domain.brokers['notifications'].publish(
    stream="updates",
    message={
        "type": "update",
        "data_url": "s3://bucket/key",  # Reference instead
        "size_bytes": 1024
    }
)
```

### Channel Naming

Use hierarchical channel names for efficient pattern matching:

```python
# Good channel naming
"user:123:notifications"     # User-specific
"chat:room:456"              # Chat room
"system:alerts:critical"     # System alerts
"metrics:api:latency"        # API metrics

# Pattern subscriptions
"user:*:notifications"       # All user notifications
"chat:room:*"                # All chat rooms
"system:alerts:*"            # All system alerts
"metrics:*"                  # All metrics
```

### Message Processing

Messages are processed sequentially per consumer group. Each group maintains its own position counter in Redis.

## Monitoring and Debugging

### Redis CLI Commands

Monitor Pub/Sub activity:

```bash
# List active channels
redis-cli PUBSUB CHANNELS

# Count subscribers for a channel
redis-cli PUBSUB NUMSUB user:123:notifications

# Monitor all Pub/Sub activity
redis-cli MONITOR | grep -E "PUBLISH|SUBSCRIBE"

# Subscribe to a channel for debugging
redis-cli SUBSCRIBE user:notifications
```

### Logging

Enable debug logging:

```python
import logging

# Enable Redis PubSub broker logging
logging.getLogger('protean.adapters.broker.redis_pubsub').setLevel(logging.DEBUG)

# Log all published messages
class LoggingPubSubBroker(RedisPubSubBroker):
    def _publish(self, stream: str, message: dict) -> int:
        logger.debug(f"Publishing to {stream}: {message}")
        result = super()._publish(stream, message)
        logger.debug(f"Delivered to {result} subscribers")
        return result
```

### Health Checks

Monitor broker health:

```python
def health_check():
    broker = domain.brokers['notifications']
    
    # Test connectivity
    if not broker.ping():
        return {"status": "unhealthy", "error": "Connection failed"}
    
    # Get health statistics
    stats = broker.health_stats()
    
    if stats.get('healthy', False):
        return {
            "status": "healthy",
            "connected_clients": stats.get('connected_clients', 0),
            "used_memory": stats.get('used_memory_human', 'unknown')
        }
    else:
        return {"status": "degraded", "error": stats.get('error', 'Unknown')}
```

## Migration Strategies

### To Redis Streams

When you need persistence and reliability:

```python
# Before: Redis PubSub
[brokers.notifications]
provider = "redis_pubsub"
URI = "redis://localhost:6379/0"

# After: Redis Streams
[brokers.notifications]
provider = "redis"  # Redis Streams
URI = "redis://localhost:6379/0"
MAXLEN = 10000  # Keep last 10k messages
```

Key differences to handle:
1. Add consumer group parameter to subscribers
2. Implement message acknowledgment
3. Handle message IDs returned from publish

### From Redis PubSub

When migrating from Redis PubSub to other brokers:

```python
# Compatibility layer
class BrokerCompatibilityLayer:
    def __init__(self, old_broker, new_broker):
        self.old_broker = old_broker
        self.new_broker = new_broker
        self.migration_mode = True
    
    def publish(self, stream: str, message: dict):
        # Publish to both during migration
        if self.migration_mode:
            self.old_broker.publish(stream, message)
        return self.new_broker.publish(stream, message)
    
    def complete_migration(self):
        self.migration_mode = False
```

## Best Practices

### 1. Use for Simple Queuing

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

### 2. Implement Circuit Breakers

```python
from circuit_breaker import CircuitBreaker

class ResilientPubSubBroker:
    def __init__(self, broker):
        self.broker = broker
        self.breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60
        )
    
    @circuit_breaker
    def publish(self, stream: str, message: dict):
        return self.broker.publish(stream, message)
```

### 3. Keep Messages Small

```python
# Compress large messages
import zlib
import json

def publish_compressed(broker, stream: str, message: dict):
    serialized = json.dumps(message)
    if len(serialized) > 1024:  # Compress if > 1KB
        compressed = zlib.compress(serialized.encode())
        broker.publish(stream, {
            "compressed": True,
            "data": compressed.hex()
        })
    else:
        broker.publish(stream, message)
```

### 4. Monitor Subscriber Count

```python
def ensure_subscribers(broker, stream: str, min_subscribers: int = 1):
    """Ensure minimum subscribers before publishing critical messages."""
    subscriber_count = broker.get_subscriber_count(stream)
    if subscriber_count < min_subscribers:
        logger.warning(
            f"Only {subscriber_count} subscribers for {stream}, "
            f"expected at least {min_subscribers}"
        )
        return False
    return True
```

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

## Next Steps

- Learn about [Redis Streams broker](./redis.md) for reliable messaging
- Understand [broker capabilities](./index.md#broker-capabilities) in detail
- Explore [custom broker development](./custom-brokers.md)
- Read about [real-time patterns](../../patterns/real-time-messaging.md)