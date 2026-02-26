# Subscribers

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Subscribers consume messages from external message brokers and other systems
outside the domain boundary. They bridge external messaging infrastructure and
the domain's internal handling, serving as the entry point for inter-system
integration at the messaging level.

!!!note "Subscribers vs. Event Handlers"
    **Event handlers** consume domain events from the internal event store and
    are associated with an aggregate via `part_of`. Use them to react to changes
    within your bounded context.

    **Subscribers** consume raw `dict` payloads from external brokers and are
    associated with a `stream`. Use them to consume messages from external
    systems like payment gateways, shipping providers, or third-party webhooks.

    See [Event Handlers](event-handlers.md) for handling domain events.

For background on how subscribers bridge external systems, see
[Subscribers concept](../../concepts/building-blocks/subscribers.md).

## Defining a Subscriber

Subscribers are defined with the `Domain.subscriber` decorator:

```python hl_lines="23-33"
--8<-- "guides/consume-state/003.py:full"
```

1. `@domain.subscriber(stream="payment_gateway")` registers this class as a
   subscriber listening to the `"payment_gateway"` broker stream. The default
   broker is used since no `broker` parameter is specified.

2. The `__call__` method receives a raw `dict` payload. The structure of the
   payload depends entirely on what the external system publishes.

3. The subscriber loads the relevant aggregate from the repository, applies
   business logic, and persists the changes.

## Subscriber Workflow

```mermaid
sequenceDiagram
  autonumber
  External System->>Broker: Publish Message
  Broker->>Broker: Store in Stream

  Note over Broker,Subscriber: Asynchronous Processing (Engine)

  Broker->>Engine: Deliver Message Batch
  Engine->>Subscriber: __call__(payload)
  Subscriber->>Subscriber: Process Message
  Subscriber->>Repository: Load/Update Aggregate
  Repository-->>Subscriber: 
  Subscriber->>Repository: Persist Changes
  Subscriber-->>Engine: Success/Failure
  Engine->>Broker: Acknowledge / Nack
```

1. **External System Publishes Message**: An external system sends a message to
   the broker on a named stream.

1. **Broker Stores Message**: The broker stores the message in the stream for
   later consumption.

1. **Engine Delivers Messages**: The Protean Engine's broker subscription polls
   the broker for new messages in batches.

1. **Engine Invokes Subscriber**: For each message, the engine instantiates the
   subscriber and calls its `__call__` method with the raw `dict` payload.

1. **Subscriber Processes Message**: The subscriber extracts data from the
   payload and performs business logic.

1. **Load/Update Aggregate**: The subscriber may load and modify aggregates
   through repositories.

1. **Persist Changes**: Modified aggregates are persisted.

1. **Acknowledge/Nack**: On success, the message is acknowledged. On failure,
   it is negatively acknowledged for potential reprocessing.

## Configuration Options

### `stream` (required)

The name of the broker stream this subscriber listens to. This must be
specified; omitting it raises an `IncorrectUsageError`.

```python
@domain.subscriber(stream="external_orders")
class ExternalOrderSubscriber:
    def __call__(self, payload: dict) -> None:
        ...
```

### `broker` (optional, default: `"default"`)

The name of the broker to use, as configured in the domain configuration. If
not specified, the subscriber uses the `"default"` broker.

```python
# Uses the default broker
@domain.subscriber(stream="order_events")
class OrderSubscriber:
    def __call__(self, payload: dict) -> None:
        ...

# Uses a specific named broker
@domain.subscriber(stream="analytics_events", broker="analytics")
class AnalyticsSubscriber:
    def __call__(self, payload: dict) -> None:
        ...
```

!!!note
    The broker name must correspond to a broker configured in your domain
    configuration. If the specified broker has not been configured, Protean
    will raise a `ConfigurationError` during domain initialization.

    See [Brokers](../../reference/adapters/broker/index.md) for details on configuring
    brokers.

## Processing Modes

### Synchronous Processing

When `message_processing` is set to `"sync"`, subscribers are invoked
immediately within the `publish()` call. This is useful for development,
testing, and simple applications.

```toml
# domain.toml
message_processing = "sync"
```

In sync mode, when a message is published to a broker stream, the broker looks
up all subscribers registered for that stream and invokes them inline before
returning.

### Asynchronous Processing

When `message_processing` is set to `"async"` (the default), messages are
stored in the broker and processed later by the Protean Engine. This is the
recommended mode for production.

```toml
# domain.toml
message_processing = "async"
```

In async mode, you must run the Protean server to process subscriber messages:

```bash
protean server
```

The engine creates a broker subscription for each registered subscriber,
managing consumer groups, message batching, and acknowledgment automatically.

Learn more in [Server](../../concepts/async-processing/index.md) and
[Subscriptions](../../concepts/async-processing/subscriptions.md).

## Error Handling

Subscribers support custom error handling through the optional `handle_error`
method. This method is called when an exception occurs during message
processing, allowing you to implement specialized error handling strategies.

### The `handle_error` Method

You can define a `handle_error` class method in your subscriber to handle
exceptions:

```python
@domain.subscriber(stream="payment_gateway")
class PaymentSubscriber:
    def __call__(self, payload: dict) -> None:
        # Processing logic that might raise exceptions
        ...

    @classmethod
    def handle_error(cls, exc: Exception, message: dict) -> None:
        """Custom error handling for message processing failures."""
        logger.error(f"Failed to process payment message: {exc}")
        # Perform recovery: store for retry, notify monitoring, etc.
        ...
```

### How It Works

1. When an exception occurs in a subscriber's `__call__` method, the Protean
   Engine catches it.
2. The engine logs detailed error information including stack traces.
3. The engine calls the subscriber's `handle_error` classmethod, passing:
   - The original exception that was raised
   - The message `dict` being processed when the exception occurred
4. After `handle_error` completes, processing continues with the next message.
5. The failed message is negatively acknowledged for potential reprocessing by
   the broker.

### Error Handler Failures

If an exception occurs within the `handle_error` method itself, the Protean
Engine will catch and log that exception as well, ensuring that the message
processing pipeline continues to function. This provides an additional layer
of resilience:

```python
@classmethod
def handle_error(cls, exc: Exception, message: dict) -> None:
    try:
        # Error handling logic that might itself fail
        ...
    except Exception as error_exc:
        # The engine will catch and log this secondary exception
        logger.error(f"Error handler failed: {error_exc}")
        # Processing continues regardless
```

### Best Practices

1. Make error handlers robust and avoid complex logic that might fail.
2. Use error handlers for logging, notification, and simple recovery.
3. Do not throw exceptions from error handlers unless absolutely necessary.
4. Consider implementing retry logic or dead-letter patterns for persistent
   failures.

## Patterns

### Payload Validation

Subscribers receive raw dicts from external systems. Validate shape and types
before trusting the data:

```python
@domain.subscriber(stream="payments")
class PaymentWebhookSubscriber:

    REQUIRED_FIELDS = ("order_id", "status", "amount")

    def __call__(self, payload: dict) -> None:
        # Validate required fields
        missing = [f for f in self.REQUIRED_FIELDS if f not in payload]
        if missing:
            logger.warning(f"Missing fields {missing}, skipping message")
            return

        # Validate types
        if not isinstance(payload["amount"], (int, float)):
            logger.warning(f"Invalid amount type: {type(payload['amount'])}")
            return

        # Safe to process
        current_domain.process(
            RecordPayment(
                order_id=payload["order_id"],
                status=payload["status"],
                amount=payload["amount"],
            )
        )
```

### Accessing Message Context

The Protean Engine sets `g.message_in_context` during subscriber processing,
using the same mechanism as event and command handlers. This gives subscribers
access to the broker message ID and stream name — useful for idempotency
checks, audit logging, and debugging:

```python
from protean.utils.globals import g

@domain.subscriber(stream="orders")
class OrderSubscriber:

    def __call__(self, payload: dict) -> None:
        msg = g.message_in_context

        # Use the broker message ID for idempotency
        message_id = msg.metadata.headers.id
        repo = current_domain.repository_for(ProcessedMessage)
        if repo.find(message_id=message_id):
            logger.info(f"Already processed {message_id}, skipping")
            return

        # Process the message
        current_domain.process(
            CreateShipment(order_id=payload["order_id"], items=payload["items"])
        )

        # Record that we processed this message
        repo.add(ProcessedMessage(message_id=message_id))
```

The context `Message` wraps the broker metadata:

| Attribute | Description |
|-----------|-------------|
| `msg.metadata.headers.id` | The broker-assigned message identifier |
| `msg.metadata.headers.stream` | The broker stream from which the message was consumed |
| `msg.data` | The raw payload `dict` |

Because this is the same `message_in_context` used for domain events and
commands, any commands dispatched by the subscriber via `domain.process()`
automatically inherit the broker message ID as their `causation_id`, linking
the full trace chain back to the original external message.

The context is automatically set before `__call__` is invoked and cleaned up
afterward — even if the subscriber raises an exception.

## Subscribers vs. Event Handlers

| Aspect | Event Handler | Subscriber |
|--------|--------------|------------|
| **Decorator** | `@domain.event_handler` | `@domain.subscriber` |
| **Message source** | Internal event store | External message broker |
| **Association** | `part_of` an aggregate | `stream` on a broker |
| **Payload type** | Typed domain event objects | Raw `dict` payloads |
| **Dispatch** | `@handle(EventClass)` per event type | Single `__call__(payload)` for all messages |
| **Processing config** | `event_processing` | `message_processing` |
| **Use case** | React to domain changes within bounded context | Consume messages from external systems |

Use **event handlers** when you need to react to events raised by aggregates
within your domain. Use **subscribers** when you need to integrate with external
systems that publish messages to a broker.

## Complete Example

Below is a comprehensive example showing two subscribers processing webhooks
from different external systems -- a payment gateway and a shipping provider:

```python hl_lines="24-48 51-63"
--8<-- "guides/consume-state/004.py:full"
```

1. `PaymentWebhookSubscriber` listens to the `"payment_gateway"` stream on the
   default broker.

2. The `__call__` method receives the raw webhook payload, extracts the order
   ID and status, and updates the order accordingly.

3. The `handle_error` classmethod provides custom error handling. If `__call__`
   raises an exception, this method is invoked with the exception and the
   original message.

4. `ShippingUpdateSubscriber` listens to a different stream
   (`"shipping_updates"`), demonstrating that multiple subscribers can coexist,
   each consuming from their own stream.

---

!!! tip "See also"
    **Concept overview:** [Subscribers](../../concepts/building-blocks/subscribers.md) — Anti-corruption layer for external message consumption.

    **Patterns:**

    - [Consuming Events from Other Domains](../../patterns/consuming-events-from-other-domains.md) — Patterns for integrating with external bounded contexts.
    - [Connecting Concepts Across Domains](../../patterns/connect-concepts-across-domains.md) — Bridging domain boundaries with shared concepts.
