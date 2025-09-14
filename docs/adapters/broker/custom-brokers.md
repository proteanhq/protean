# Custom Brokers

Learn how to create custom broker adapters for Protean to integrate with any message broker or streaming platform.

## Overview

Custom brokers allow you to:

- Integrate new messaging technologies (Kafka, RabbitMQ, AWS SQS, etc.)
- Add company-specific messaging systems
- Create specialized brokers for testing or development

## Architecture

All brokers must inherit from `BaseBroker` and implement the required abstract methods:

```python
from typing import TYPE_CHECKING, Dict, List, Tuple
from protean.port.broker import BaseBroker, BrokerCapabilities

if TYPE_CHECKING:
    from protean.domain import Domain

class CustomBroker(BaseBroker):
    """Custom broker implementation."""
    
    def __init__(self, name: str, domain: "Domain", conn_info: Dict) -> None:
        super().__init__(name, domain, conn_info)
        # Initialize your broker connection here
    
    @property
    def capabilities(self) -> BrokerCapabilities:
        """Declare broker capabilities."""
        return BrokerCapabilities.BASIC_PUBSUB
    
    def _publish(self, stream: str, message: dict) -> str:
        """Publish a message to the broker."""
        # Implementation required
        pass
    
    def _read(
        self, 
        stream: str, 
        consumer_group: str, 
        no_of_messages: int
    ) -> List[Tuple[str, dict]]:
        """Read messages from the broker."""
        # Implementation required
        pass
    
    def _ack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Acknowledge message processing."""
        # Required if ACK_NACK capability is declared
        pass
    
    def _nack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Reject message for reprocessing."""
        # Required if ACK_NACK capability is declared
        pass
    
    def _ping(self) -> bool:
        """Test broker connectivity."""
        # Implementation required
        pass
    
    def _health_stats(self) -> dict:
        """Get broker health statistics."""
        # Implementation required
        pass
    
    def _ensure_connection(self) -> bool:
        """Ensure connection is healthy."""
        # Implementation required
        pass
```

## Example: Kafka Broker

Here's a complete example of creating a Kafka broker as an external package:

### Project Structure

```
protean-kafka-broker/
├── pyproject.toml
├── src/
│   └── protean_kafka/
│       ├── __init__.py
│       └── broker.py
└── tests/
```

### pyproject.toml

```toml
[tool.poetry]
name = "protean-kafka-broker"
version = "0.1.0"
description = "Kafka broker for Protean"

[tool.poetry.dependencies]
python = "^3.11"
protean = "^0.14"
kafka-python = "^2.0"

[tool.poetry.plugins."protean.brokers"]
kafka = "protean_kafka:register"
```

### Registration Function

```python
# src/protean_kafka/__init__.py
"""Kafka broker plugin for Protean."""

def register():
    """Register Kafka broker with Protean."""
    try:
        # Only register if kafka is available
        import kafka
        from protean.port.broker import registry
        
        registry.register(
            "kafka",
            "protean_kafka.broker.KafkaBroker"
        )
    except ImportError:
        # Kafka not available, skip registration
        pass
```

### Broker Implementation

```python
# src/protean_kafka/broker.py
"""Kafka broker implementation."""

import json
from typing import TYPE_CHECKING, Dict, List, Tuple
import kafka
from protean.port.broker import BaseBroker, BrokerCapabilities

if TYPE_CHECKING:
    from protean.domain import Domain


class KafkaBroker(BaseBroker):
    """Kafka broker implementation for Protean."""
    
    __broker__ = "kafka"
    
    def __init__(self, name: str, domain: "Domain", conn_info: Dict) -> None:
        super().__init__(name, domain, conn_info)
        
        # Initialize Kafka connection
        self.producer = kafka.KafkaProducer(
            bootstrap_servers=conn_info.get("BOOTSTRAP_SERVERS", ["localhost:9092"]),
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        
        self.consumer = kafka.KafkaConsumer(
            bootstrap_servers=conn_info.get("BOOTSTRAP_SERVERS", ["localhost:9092"]),
            value_deserializer=lambda m: json.loads(m.decode('utf-8'))
        )
    
    @property
    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities.ORDERED_MESSAGING
    
    def _publish(self, stream: str, message: dict) -> str:
        """Publish message to Kafka topic."""
        future = self.producer.send(stream, message)
        record_metadata = future.get(timeout=10)
        return f"{record_metadata.partition}:{record_metadata.offset}"
    
    def _read(self, stream: str, consumer_group: str, no_of_messages: int) -> List[Tuple[str, dict]]:
        """Read messages from Kafka topic."""
        # Subscribe to topic with consumer group
        self.consumer.subscribe([stream])
        messages = []
        
        # Poll for messages
        records = self.consumer.poll(timeout_ms=1000, max_records=no_of_messages)
        
        for topic_partition, msgs in records.items():
            for msg in msgs:
                msg_id = f"{msg.partition}:{msg.offset}"
                messages.append((msg_id, msg.value))
        
        return messages
    
    def _ack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Acknowledge message (commit offset in Kafka)."""
        try:
            self.consumer.commit()
            return True
        except Exception:
            return False
    
    def _nack(self, stream: str, identifier: str, consumer_group: str) -> bool:
        """Negative acknowledgment - seek back for reprocessing."""
        # In Kafka, NACK typically means not committing the offset
        # Message will be redelivered on next poll
        return True
    
    def _ping(self) -> bool:
        """Test Kafka connectivity."""
        try:
            # Check if we can list topics
            self.consumer.list_topics(timeout=5)
            return True
        except:
            return False
    
    def _health_stats(self) -> dict:
        """Get Kafka broker health statistics."""
        try:
            metrics = self.producer.metrics()
            return {
                "healthy": True,
                "connection_count": metrics.get('connection-count', 0),
                "request_rate": metrics.get('request-rate', 0)
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}
    
    def _ensure_connection(self) -> bool:
        """Ensure Kafka connection is healthy."""
        return self._ping()
```

## Installation & Usage

### For External Packages

Users install your broker package:

```bash
pip install protean-kafka-broker
```

Then configure it in their domain:

```toml
# domain.toml
[brokers.default]
provider = "kafka"
BOOTSTRAP_SERVERS = ["localhost:9092"]
```

### For Internal Brokers

If adding a broker to Protean itself:

1. Add the broker implementation in `src/protean/adapters/broker/`
2. Create a `register()` function in your broker module
3. Add entry point in `pyproject.toml`:

```toml
[tool.poetry.plugins."protean.brokers"]
mybroker = "protean.adapters.broker.mybroker:register"
```

## Declaring Capabilities

Choose the appropriate capability tier for your broker:

```python
@property
def capabilities(self) -> BrokerCapabilities:
    # Basic pub/sub only
    return BrokerCapabilities.BASIC_PUBSUB
    
    # With consumer groups
    return BrokerCapabilities.SIMPLE_QUEUING
    
    # With acknowledgments
    return BrokerCapabilities.RELIABLE_MESSAGING
    
    # With ordering guarantees
    return BrokerCapabilities.ORDERED_MESSAGING
    
    # Full enterprise features
    return BrokerCapabilities.ENTERPRISE_STREAMING
```

## Testing Your Broker

### Unit Tests

```python
import pytest
from unittest.mock import Mock, patch

def test_broker_capabilities():
    """Test broker declares correct capabilities."""
    broker = KafkaBroker("test", Mock(), {"BOOTSTRAP_SERVERS": ["localhost:9092"]})
    assert broker.has_capability(BrokerCapabilities.MESSAGE_ORDERING)

def test_publish():
    """Test message publishing."""
    with patch("kafka.KafkaProducer"):
        broker = KafkaBroker("test", Mock(), {})
        result = broker.publish("test-stream", {"data": "test"})
        assert result is not None
```

### Integration Tests

```python
@pytest.mark.integration
def test_end_to_end():
    """Test full message flow."""
    domain = Domain(__name__)
    domain.config['brokers'] = {
        'default': {
            'provider': 'kafka',
            'BOOTSTRAP_SERVERS': ['localhost:9092']
        }
    }
    domain.init()
    
    # Publish message
    msg_id = domain.brokers.publish("test", {"data": "test"})
    
    # Read message
    messages = domain.brokers['default'].read("test", "group", 1)
    assert len(messages) == 1
```

## Best Practices

1. **Handle Connection Failures**: Implement reconnection logic in `_ensure_connection()`
2. **Declare Accurate Capabilities**: Only declare capabilities you actually implement
3. **Follow Protean Conventions**: Use consistent naming and error handling
4. **Provide Health Checks**: Implement meaningful `_ping()` and `_health_stats()`
5. **Document Configuration**: Clearly document all configuration options

## Common Patterns

### Connection Pooling

```python
def __init__(self, name: str, domain: "Domain", conn_info: Dict) -> None:
    super().__init__(name, domain, conn_info)
    
    # Create connection pool
    self.pool = []
    pool_size = conn_info.get("POOL_SIZE", 10)
    
    for _ in range(pool_size):
        conn = self._create_connection()
        self.pool.append(conn)
```

### Retry Logic

```python
import time

def _publish(self, stream: str, message: dict) -> str:
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
            return self._do_publish(stream, message)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)  # Exponential backoff
```

## Next Steps

- Review [existing broker implementations](https://github.com/proteanhq/protean/tree/main/src/protean/adapters/broker) for examples
- Understand [broker capabilities](./index.md#broker-capabilities) in detail
- Test with the [broker test suite](https://github.com/proteanhq/protean/tree/main/tests/adapters/broker)
- Share your broker with the [Protean community](https://github.com/proteanhq/protean/discussions)