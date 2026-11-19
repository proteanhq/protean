# Custom Brokers

You can write a custom broker adapter to connect Protean to any message broker or streaming platform.

## Overview

Custom brokers allow you to:

- Integrate new messaging technologies (Kafka, RabbitMQ, AWS SQS, etc.)
- Add company-specific messaging systems
- Create specialized brokers for testing or development

## Architecture

A broker adapter subclasses `BaseBroker` and `BrokerPort`, in that order.
`BrokerPort` holds the operations Protean calls on every broker. `BaseBroker`
stores the adapter's name, domain and configuration. Four capabilities have
their own Port, and each Port extends `BrokerPort`. A broker that advertises
one of them subclasses `BaseBroker` and that Port in place of `BrokerPort`:

| Capability | Port | Methods |
|------------|------|---------|
| `BLOCKING_READ` | `BlockingReadPort` | The blocking reads (see [Blocking reads](#blocking-reads)) |
| `DEAD_LETTER_QUEUE` | `DeadLetterQueuePort` | The dead letter queue operations (see [Dead letter queues](#dead-letter-queues)) |
| `STREAM_PARTITIONING` | `PartitioningPort` | The partition-per-key operations (see [Partitioning](partitioning.md)) |
| `STREAM_RETENTION` | `StreamRetentionPort` | `trim` (see [Stream retention](partitioning.md#stream-retention)) |

The adapter implements these members:

- Capabilities: the `capabilities` property
- Publishing and reading: `publish`, `read`
- Acknowledgment: `ack`, `nack`
- Consumer groups: `create_group`, `consumer_groups`
- Connection and health: `ping`, `health`, `get_connection`, `reconnect`, `clear`
- Dead letter queue, only on a broker that declares that capability: `dlq_list`, `dlq_get`, `dlq_replay`, `dlq_replay_all`, `dlq_purge`, `dlq_trim`, `dlq_depth`

A broker that does not support a feature still implements the `BrokerPort`
method, and returns an empty result or raises `NotSupportedError`. A broker
without `DEAD_LETTER_QUEUE` has no dead letter queue methods. The `Broker`
service answers its dead letter queue calls with an empty result.

`BrokerPort` also defines `close`, `mark_subscription_owned`,
`remove_stale_consumers` and `reclaim_idle_pending`. Their defaults do
nothing. Override them when your backend keeps connections or per-consumer
pending lists.

`read` takes a `new_messages` flag. When it is `True`, the broker skips
messages that are pending in the group, meaning delivered and not yet
acknowledged, and returns an empty list when only pending messages remain. A
broker that redelivers a nacked message by putting it back on the stream, as
the inline broker does, returns that message as a new one.

Your code does not call the adapter. `domain.brokers["default"]` returns a
`Broker` service that wraps it. The service records messages published inside
a unit of work, retries once after a connection error, checks capabilities
before `read`, `get_next`, `ack`, `nack`, `read_blocking` and
`read_blocking_streams`, and passes messages to subscribers when the
broker runs synchronously. End the adapter module with
`_PORT_CHECK: type[BrokerPort] = YourBroker` so mypy reports a missing or
mistyped method. A broker that subclasses `BlockingReadPort` adds
`_BLOCKING_READ_CHECK: type[BlockingReadPort] = YourBroker`, and the same
for each other Port it subclasses.

The broker below implements every method by handing it to an in-memory
`InlineBroker`. Replace those calls with calls to your messaging client:

```python
--8<-- "adapters/broker/custom-brokers/delegating_broker/__init__.py:broker"
```

Once registered, the broker is configured by its name like any other:

```python
--8<-- "adapters/broker/custom-brokers/delegating_broker/__init__.py:usage"
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
# fragment
[project]
name = "protean-kafka-broker"
version = "0.1.0"
description = "Kafka broker for Protean"
requires-python = ">=3.11"
dependencies = [
    "protean>=0.19",
    "kafka-python>=2.0",
]

[project.entry-points."protean.brokers"]
kafka = "protean_kafka:register"
```

### Registration Function

```python
# fragment
# src/protean_kafka/__init__.py
"""Kafka broker plugin for Protean."""

def register():
    """Register Kafka broker with Protean."""
    try:
        # Only register if kafka is available
        import kafka
        from protean.infra.registry import brokers

        brokers.register(
            "kafka",
            "protean_kafka.broker.KafkaBroker"
        )
    except ImportError:
        # Kafka not available, skip registration
        pass
```

### Broker Implementation

```python
# fragment
# src/protean_kafka/broker.py
"""Kafka broker implementation."""

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
import kafka
from protean.port.broker import (
    BaseBroker,
    BrokerCapabilities,
    BrokerHealth,
    BrokerMessage,
    BrokerPort,
)

if TYPE_CHECKING:
    from protean.domain import Domain


class KafkaBroker(BaseBroker, BrokerPort):
    """Kafka broker implementation for Protean."""

    broker_type = "kafka"

    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        super().__init__(name, domain, config)

        # Initialize Kafka connection
        self.producer = kafka.KafkaProducer(
            bootstrap_servers=config.get("BOOTSTRAP_SERVERS", ["localhost:9092"]),
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )

        self.consumer = kafka.KafkaConsumer(
            bootstrap_servers=config.get("BOOTSTRAP_SERVERS", ["localhost:9092"]),
            value_deserializer=lambda m: json.loads(m.decode('utf-8'))
        )

    @property
    def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities.ORDERED_MESSAGING

    def publish(self, stream: str, message: dict[str, Any]) -> str:
        """Publish message to Kafka topic."""
        future = self.producer.send(stream, message)
        record_metadata = future.get(timeout=10)
        return f"{record_metadata.partition}:{record_metadata.offset}"

    def read(
        self,
        stream: str,
        consumer_group: str,
        limit: int,
        *,
        new_messages: bool = False,
    ) -> list[BrokerMessage]:
        """Read messages from Kafka topic."""
        # Subscribe to topic with consumer group
        self.consumer.subscribe([stream])
        messages = []

        # Poll for messages
        records = self.consumer.poll(timeout_ms=1000, max_records=limit)

        for topic_partition, msgs in records.items():
            for msg in msgs:
                msg_id = f"{msg.partition}:{msg.offset}"
                messages.append(BrokerMessage(msg_id, msg.value))

        return messages

    def ack(self, stream: str, message_id: str, consumer_group: str) -> bool:
        """Acknowledge message (commit offset in Kafka)."""
        try:
            self.consumer.commit()
            return True
        except Exception:
            return False

    def nack(self, stream: str, message_id: str, consumer_group: str) -> bool:
        """Negative acknowledgment - seek back for reprocessing."""
        # In Kafka, NACK typically means not committing the offset
        # Message will be redelivered on next poll
        return True

    def ping(self) -> bool:
        """Test Kafka connectivity."""
        try:
            # Check if we can list topics
            self.consumer.list_topics(timeout=5)
            return True
        except:
            return False

    def health(self) -> BrokerHealth:
        """Get Kafka broker health statistics."""
        try:
            metrics = self.producer.metrics()
            return BrokerHealth(
                healthy=True,
                message_counts={},
                consumer_groups={},
                details={
                    "connection_count": metrics.get('connection-count', 0),
                    "request_rate": metrics.get('request-rate', 0),
                },
            )
        except Exception as e:
            return BrokerHealth(
                healthy=False,
                message_counts={},
                consumer_groups={},
                details={"error": str(e)},
            )

    def reconnect(self) -> bool:
        """Check the Kafka connection."""
        return self.ping()
```

This listing shows the core methods only. A complete Kafka broker also
implements `create_group`, `consumer_groups`, `get_connection` and `clear` from
the [Architecture](#architecture) list. Without them, Python refuses to create
an instance of the class.

## Installation & Usage

### For External Packages

Users install your broker package:

```bash
pip install protean-kafka-broker
```

Then configure it in their domain:

```toml
# fragment
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
# fragment
[project.entry-points."protean.brokers"]
mybroker = "protean.adapters.broker.mybroker:register"
```

## Declaring Capabilities

Choose the appropriate capability tier for your broker:

```python
# fragment
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

`ENTERPRISE_STREAMING` includes `BLOCKING_READ`, `DEAD_LETTER_QUEUE`,
`STREAM_PARTITIONING` and `STREAM_RETENTION`, so a broker that declares it
subclasses `BlockingReadPort`, `DeadLetterQueuePort`, `PartitioningPort` and
`StreamRetentionPort`.

### Blocking reads

A broker that declares `BLOCKING_READ` subclasses `BlockingReadPort` from
`protean.port.broker` and implements both of its methods, `read_blocking` and
`read_blocking_streams`. If the broker declares the capability and does not
subclass `BlockingReadPort`, `domain.init()` raises `ConfigurationError`. The
message names the methods the broker does not implement, if any. On a broker without the capability, the `Broker`
service reads each stream once with `read` and does not wait.

`read_blocking_streams` reads several streams in one call and returns a dict
with one key per stream, in the order given. Stream subscriptions with
priority lanes use it to read the primary and the backfill stream together.
It waits up to `timeout_ms` in total for a message on any of the streams, as
the Redis broker does with one blocking `XREADGROUP`. An empty `streams`
returns `{}`.

```python
# fragment
class MyBroker(BaseBroker, BlockingReadPort):
    def read_blocking(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int = 5000,
        limit: int = 1,
    ) -> list[BrokerMessage]:
        ...

    def read_blocking_streams(
        self,
        streams: Sequence[str],
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int = 5000,
        limit: int = 1,  # Applies to each stream
    ) -> dict[str, list[BrokerMessage]]:
        ...
```

### Dead letter queues

A broker that declares `DEAD_LETTER_QUEUE` subclasses `DeadLetterQueuePort`
from `protean.port.broker` and implements its seven methods. If the broker
declares the capability and does not subclass `DeadLetterQueuePort`,
`domain.init()` raises `ConfigurationError`. The message names the methods the
broker does not implement. The `Broker` service reads the capability flag, not
the methods. On a broker without the flag, `dlq_list` returns `[]`, `dlq_get`
returns `None`, `dlq_replay` returns `False`, and the counting methods return
0.

A dead letter queue lives on its own stream, named after the source stream
with a `:dlq` suffix. `dlq_trim` removes the entries that failed before
`older_than`, which must be a timezone-aware `datetime`. Both the `Broker`
service and the inline and Redis brokers raise `ValueError` for a naive one.

```python
# fragment
class MyBroker(BaseBroker, DeadLetterQueuePort):
    def dlq_list(self, dlq_streams: list[str], limit: int = 100) -> list[DLQEntry]:
        ...

    def dlq_get(self, dlq_stream: str, dlq_id: str) -> DLQEntry | None:
        ...

    def dlq_replay(self, dlq_stream: str, dlq_id: str, target_stream: str) -> bool:
        ...

    def dlq_replay_all(self, dlq_stream: str, target_stream: str) -> int:
        ...

    def dlq_purge(self, dlq_stream: str) -> int:
        ...

    def dlq_trim(self, dlq_stream: str, older_than: datetime) -> int:
        ...

    def dlq_depth(self, dlq_stream: str) -> int:
        ...
```

A broker that declares both `BLOCKING_READ` and `DEAD_LETTER_QUEUE` subclasses
both sub-protocols, as `class MyBroker(BaseBroker, BlockingReadPort,
DeadLetterQueuePort)`.

## Testing Your Broker

### Unit Tests

```python
# fragment
import pytest
from unittest.mock import Mock, patch

def test_broker_capabilities():
    """Test broker declares correct capabilities."""
    broker = KafkaBroker("test", Mock(), {"BOOTSTRAP_SERVERS": ["localhost:9092"]})
    assert BrokerCapabilities.MESSAGE_ORDERING in broker.capabilities

def test_publish():
    """Test message publishing."""
    with patch("kafka.KafkaProducer"):
        broker = KafkaBroker("test", Mock(), {})
        result = broker.publish("test-stream", {"data": "test"})
        assert result is not None
```

### Integration Tests

```python
# fragment
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

## Guidance for adapter authors

1. **Handle Connection Failures**: Implement reconnection logic in `reconnect()`
2. **Declare Accurate Capabilities**: Only declare capabilities you actually implement
3. **Follow Protean Conventions**: Use consistent naming and error handling
4. **Provide Health Checks**: Implement meaningful `ping()` and `health()`
5. **Document Configuration**: Clearly document all configuration options

## Common Patterns

### Connection Pooling

```python
# fragment
def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
    super().__init__(name, domain, config)

    # Create connection pool
    self.pool = []
    pool_size = config.get("POOL_SIZE", 10)

    for _ in range(pool_size):
        conn = self._create_connection()
        self.pool.append(conn)
```

### Retry Logic

```python
# fragment
import time

def publish(self, stream: str, message: dict[str, Any]) -> str:
    max_retries = 3

    for attempt in range(max_retries):
        try:
            return self._do_publish(stream, message)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)  # Exponential backoff
```

## Related pages

- Review [existing broker implementations](https://github.com/proteanhq/protean/tree/main/src/protean/adapters/broker) for examples
- Understand [broker capabilities](./index.md#broker-capabilities) in detail
- Test with the [broker test suite](https://github.com/proteanhq/protean/tree/main/tests/adapters/broker)
- Share your broker with the [Protean community](https://github.com/proteanhq/protean/discussions)
