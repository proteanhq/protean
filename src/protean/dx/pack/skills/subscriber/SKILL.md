---
name: subscriber
description: Define a Protean subscriber - a domain element that consumes messages from external message brokers and acts as an anti-corruption layer at the domain boundary. Subscribers listen to named broker streams, receive raw dict payloads (not typed domain events), and translate external data into domain operations. Unlike event handlers which react to internal domain events, subscribers react to messages arriving from outside the bounded context via external message brokers. Use when you need to consume external webhook messages, process messages from an external broker, integrate with an external system via messaging, translate external events into domain commands, build an anti-corruption layer, or when the user asks to "create a subscriber", "add a webhook handler", "consume external events", "listen to a broker stream", "integrate with an external service", or "add an anti-corruption layer".
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
  diagnostic_codes:
    - SUBSCRIBER_NO_STREAMS
---

# Subscriber

## How subscribers differ from event handlers

| Aspect | Event Handler | Subscriber |
|--------|--------------|------------|
| **Decorator** | `@domain.event_handler` | `@domain.subscriber` |
| **Message source** | Internal event store | External message broker |
| **Association** | `part_of` an aggregate or `stream_category` | `stream` on a broker |
| **Payload type** | Typed domain event objects | Raw `dict` payloads |
| **Dispatch** | `@handle(EventClass)` per event type | Single `__call__(payload)` for all messages |
| **Processing config** | `event_processing` | `message_processing` |
| **Use case** | React to domain changes within bounded context | Consume messages from external systems |

## Basic structure

```python
from protean import Domain
from protean.fields import Float, Identifier, String

domain = Domain()
domain.config["message_processing"] = "sync"

@domain.aggregate
class Payment:
    order_id: Identifier(required=True)
    amount: Float(required=True)
    status: String(default="PENDING")

    def confirm(self):
        self.status = "CONFIRMED"

@domain.subscriber(stream="payment_gateway")
class PaymentConfirmationSubscriber:
    def __call__(self, payload: dict) -> None:
        order_id = payload["order_id"]
        repo = domain.repository_for(Payment)
        payment = repo._dao.find_by(order_id=order_id)
        payment.confirm()
        repo.add(payment)
```

## Key rules

1. **stream is required** - Every subscriber must specify a stream: `@domain.subscriber(stream="payment_gateway")`
2. **Implement __call__** - Subscribers receive messages via `__call__(self, payload: dict)`, not `@handle`
3. **Payload is always a raw dict** - External broker messages arrive as plain Python dicts, not typed events
4. **broker defaults to "default"** - Optionally specify broker: `@domain.subscriber(stream="...", broker="my_broker")`
5. **Use message_processing for sync mode** - `domain.config["message_processing"] = "sync"` (NOT `event_processing`)
6. **No return values** - Subscribers follow fire-and-forget, return values are discarded
7. **One subscriber per stream** - Each subscriber class handles all messages on its stream
8. **Anti-corruption layer** - Translate external schemas into domain language at the subscriber boundary

## Subscriber options

| Option | Purpose | Required |
|--------|---------|----------|
| `stream` | Name of the external broker stream to consume | Yes |
| `broker` | Broker name (defaults to `"default"`) | No |

## Quick example: Multiple subscribers

```python
@domain.subscriber(stream="payment_gateway")
class PaymentWebhookSubscriber:
    def __call__(self, payload: dict) -> None:
        if payload["status"] == "SUCCESS":
            order = domain.repository_for(Order).get(payload["order_id"])
            order.mark_paid()
            domain.repository_for(Order).add(order)

@domain.subscriber(stream="shipping_updates", broker="default")
class ShippingUpdateSubscriber:
    def __call__(self, payload: dict) -> None:
        order = domain.repository_for(Order).get(payload["order_id"])
        order.mark_shipped(payload["tracking_number"])
        domain.repository_for(Order).add(order)
```

## Quick example: Anti-corruption layer

```python
@domain.subscriber(stream="erp_user_events")
class ERPUserSubscriber:
    """Translates external ERP format into domain commands."""

    def __call__(self, payload: dict) -> None:
        if payload.get("event_type") == "user.created":
            data = payload["data"]
            command = RegisterCustomer(
                customer_id=data["userId"],
                name=f"{data['firstName']} {data['lastName']}",
                email=data["emailAddress"],
            )
            domain.process(command)
```

## Error handling

Override `handle_error` classmethod for custom error recovery during async processing:

```python
@domain.subscriber(stream="inventory_updates")
class InventorySubscriber:
    def __call__(self, payload: dict) -> None:
        # ... processing logic ...
        pass

    @classmethod
    def handle_error(cls, exc: Exception, message: dict) -> None:
        logger.error("Inventory update failed: %s", exc)
```

## Common mistakes

### Missing stream parameter

```python
@domain.subscriber  # Wrong! Missing stream
class MySubscriber:
    def __call__(self, payload: dict) -> None:
        pass
```

Instead: Always specify stream

```python
@domain.subscriber(stream="my_external_stream")  # Correct!
class MySubscriber:
    def __call__(self, payload: dict) -> None:
        pass
```

### Using @handle decorator

```python
@domain.subscriber(stream="payment_gateway")
class PaymentSubscriber:
    @handle(PaymentReceived)  # Wrong! Subscribers don't use @handle
    def on_payment(self, event):
        pass
```

Instead: Use `__call__` with raw dict payload

### Using event_processing config

```python
domain.config["event_processing"] = "sync"  # Wrong config for subscribers!
```

Instead: Use `message_processing`

```python
domain.config["message_processing"] = "sync"  # Correct!
```

### Expecting typed event objects

```python
def __call__(self, event: PaymentConfirmed) -> None:  # Wrong type!
    order_id = event.order_id
```

Instead: Always expect `dict`

```python
def __call__(self, payload: dict) -> None:  # Correct!
    order_id = payload["order_id"]
```

## Detailed references

### Core Concepts
- [Basic Subscriber](references/basic-subscriber.md) - Simple single-stream subscriber
- [Anti-corruption Layer](references/anti-corruption-layer.md) - Translating external schemas into domain commands
- [Error Handling](references/error-handling.md) - Custom error recovery with handle_error
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Simple Subscriber](assets/subscriber_simple.py) - Basic payment confirmation subscriber
- [Domain Interaction](assets/subscriber_domain_interaction.py) - Subscriber updating aggregates through repositories
- [Multiple Streams](assets/subscriber_multiple_streams.py) - Multiple subscribers on different streams
- [Error Handling](assets/subscriber_error_handling.py) - Custom handle_error classmethod
- [Anti-corruption Layer](assets/subscriber_anti_corruption.py) - Translating external events to domain commands

### Related Skills
- `event-handler` - Compare/contrast: event handlers consume internal domain events, subscribers consume external broker messages
- `aggregate` - Subscribers often load and update aggregates through repositories
- `command` - Subscribers commonly translate external messages into domain commands
- `command-handler` - Subscribers often dispatch commands for processing

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
