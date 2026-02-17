# Inline Broker

The Inline broker is a synchronous, stubbed, in-memory message broker that processes messages within the same process. It's the default broker in Protean and requires no external dependencies.

## Overview

The Inline broker is designed for:

- **Development environments** where simplicity is key
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

Note: `IS_ASYNC` is always set to `false` for the Inline broker, regardless of configuration.

## Capabilities

The Inline broker supports the following capabilities:

- ✅ **BASIC_PUBSUB** - Fire-and-forget message publishing
- ✅ **SIMPLE_QUEUING** - Consumer groups for message distribution
- ✅ **RELIABLE_MESSAGING** - Message acknowledgment and rejection
- ❌ **ORDERED_MESSAGING** - Not supported
- ❌ **ENTERPRISE_STREAMING** - Not supported

## Usage Examples

### Basic Publishing and Subscribing

```python
from protean import Domain, handle

domain = Domain(__name__)
domain.config['brokers'] = {
    'default': {
        'provider': 'inline'
    }
}
domain.init()

# Publishing messages
domain.brokers.publish(
    stream="user-events",
    message={
        "type": "user.created",
        "user_id": "123",
        "name": "John Doe"
    }
)

# Subscribing to messages
@domain.subscriber(stream="user-events")
class UserEventSubscriber:
    @handle("user.created")
    def on_user_created(self, message):
        print(f"User created: {message['name']}")
```

### Testing with Inline Broker

The Inline broker is ideal for testing as it provides deterministic, synchronous behavior. Use Protean's `DomainFixture` to manage the domain lifecycle:

```python
import pytest
from protean import Domain
from protean.integrations.pytest import DomainFixture

domain = Domain(__name__)
domain.config['brokers'] = {
    'default': {'provider': 'inline'}
}


@pytest.fixture(scope="session")
def app_fixture():
    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield


def test_message_processing():
    # Track processed messages
    processed = []

    @domain.subscriber(stream="test-stream")
    class TestSubscriber:
        @handle("test.event")
        def process(self, message):
            processed.append(message)

    # Publish a message
    domain.brokers.publish(
        stream="test-stream",
        message={"type": "test.event", "data": "test"}
    )

    # Message is processed synchronously
    assert len(processed) == 1
    assert processed[0]["data"] == "test"
```

### Consumer Groups

The Inline broker supports consumer groups for distributing messages:

```python
# Multiple subscribers in the same consumer group
@domain.subscriber(stream="orders", consumer_group="order-processor")
class OrderProcessor1:
    @handle("order.created")
    def process(self, message):
        print(f"Processor 1 handling order {message['order_id']}")

@domain.subscriber(stream="orders", consumer_group="order-processor")
class OrderProcessor2:
    @handle("order.created")
    def process(self, message):
        print(f"Processor 2 handling order {message['order_id']}")

# Messages are distributed across processors in the same group
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
- **No Ordering Guarantees**
    - Messages may be processed out of order
    - No support for partitioned delivery
    - Cannot ensure strict message sequencing
- **Limited Error Recovery**
    - Basic retry support only
    - No dead letter queue functionality
    - Limited visibility into failed messages

## Migration Path

The Inline broker is designed to be easily replaced with production-ready brokers:

```python
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
2. Handle broker-specific errors appropriately
3. Test with the production broker before deployment

## Next Steps

- Learn about [Redis broker](./redis.md) for production use
- Understand [broker capabilities](./index.md#broker-capabilities) in detail
- Explore [custom broker development](./custom-brokers.md)