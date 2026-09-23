# Basic Subscriber

A subscriber that listens to a single external broker stream and processes raw dict payloads. This is the simplest subscriber pattern.

## Overview

Use this pattern when your domain needs to react to messages from a single external system. The subscriber receives raw `dict` payloads (not typed domain events) and performs a single action in response.

Common use cases:
- Processing payment gateway webhooks
- Consuming inventory updates from a warehouse system
- Reacting to user registration events from an external identity provider

## Code

The complete implementation is in [assets/subscriber_simple.py](../assets/subscriber_simple.py).

Key highlights:
- `@domain.subscriber(stream="payment_gateway")` -- subscribes to the `payment_gateway` broker stream
- `__call__(self, payload: dict)` -- single entry point for all messages on the stream
- No `@handle` decorator -- unlike event handlers, subscribers use `__call__` directly
- `domain.config["message_processing"] = "sync"` -- enables synchronous processing for testing

## Walkthrough

### The Aggregate

```python
@domain.aggregate
class Payment:
    order_id: Identifier(required=True)
    amount: Float(required=True)
    status: String(choices=["PENDING", "CONFIRMED", "FAILED"], default="PENDING")

    def confirm(self):
        self.status = "CONFIRMED"
```

A simple aggregate with a business method. The subscriber will call this method after receiving the external message.

### The Subscriber

```python
@domain.subscriber(stream="payment_gateway")
class PaymentConfirmationSubscriber:
    def __call__(self, payload: dict) -> None:
        order_id = payload["order_id"]
        repo = domain.repository_for(Payment)
        payment = repo._dao.find_by(order_id=order_id)
        payment.confirm()
        repo.add(payment)
```

The subscriber:
1. Receives a raw dict payload from the broker
2. Extracts data from the payload
3. Loads the aggregate from the repository
4. Calls a business method on the aggregate
5. Persists the updated aggregate

### Testing with Sync Broker

```python
domain.config["message_processing"] = "sync"

# Create prerequisite data
payment = Payment(order_id="ORD-001", amount=99.99)
domain.repository_for(Payment).add(payment)

# Publish to broker stream (triggers subscriber in sync mode)
domain.brokers["default"].publish(
    "payment_gateway",
    {"order_id": "ORD-001", "transaction_id": "txn-789"},
)

# Verify subscriber processed the message
updated = domain.repository_for(Payment)._dao.find_by(order_id="ORD-001")
assert updated.status == "CONFIRMED"
```

## Subscriber vs Event Handler

| Aspect | Event Handler | Subscriber |
|--------|--------------|------------|
| Message source | Internal event store | External message broker |
| Payload type | Typed domain event objects | Raw `dict` payloads |
| Dispatch | `@handle(EventClass)` per event type | Single `__call__(payload)` for all messages |
| Processing config | `event_processing` | `message_processing` |

## Related

- [Anti-corruption Layer](./anti-corruption-layer.md) - Translating external schemas into domain commands
- [Error Handling](./error-handling.md) - Custom error recovery
- `event-handler` - Compare/contrast: internal event consumption
