# Subscriber Anti-patterns

Common mistakes when implementing subscribers in Protean and how to avoid them.

## 1. Missing stream Parameter

**Wrong:**
```python
@domain.subscriber  # Missing stream!
class MySubscriber:
    def __call__(self, payload: dict) -> None:
        pass
```

**Correct:**
```python
@domain.subscriber(stream="my_external_stream")
class MySubscriber:
    def __call__(self, payload: dict) -> None:
        pass
```

Protean raises `IncorrectUsageError` at class definition time, with the message "Subscriber `MySubscriber` needs to be associated with a stream", so a streamless subscriber never reaches the registry. A subscriber must name the stream it consumes.

## 2. Using @handle Decorator Instead of __call__

**Wrong:**
```python
from protean import handle

@domain.subscriber(stream="payment_gateway")
class PaymentSubscriber:
    @handle(PaymentReceived)  # Wrong! Subscribers don't use @handle
    def on_payment(self, event):
        pass
```

**Correct:**
```python
@domain.subscriber(stream="payment_gateway")
class PaymentSubscriber:
    def __call__(self, payload: dict) -> None:  # Single entry point
        pass
```

Subscribers use a single `__call__` method to receive all messages on their stream. They do NOT use `@handle` decorators (that is for event handlers).

## 3. Expecting Typed Event Objects

**Wrong:**
```python
@domain.subscriber(stream="payment_gateway")
class PaymentSubscriber:
    def __call__(self, event: PaymentConfirmed) -> None:  # Wrong type!
        order_id = event.order_id  # Will fail - payload is a dict
```

**Correct:**
```python
@domain.subscriber(stream="payment_gateway")
class PaymentSubscriber:
    def __call__(self, payload: dict) -> None:  # Always dict
        order_id = payload["order_id"]  # Access as dict
```

Subscribers receive raw `dict` payloads from external brokers, not typed domain event objects. The payload structure depends on the external system.

## 4. Using event_processing Instead of message_processing

**Wrong:**
```python
domain.config["event_processing"] = "sync"  # Wrong config key!
```

**Correct:**
```python
domain.config["message_processing"] = "sync"  # Correct for subscribers
```

Event handlers use `event_processing`. Subscribers use `message_processing`. These are separate configuration keys.

## 5. Confusing Subscribers with Event Handlers

**Wrong approach:** Using a subscriber to consume internal domain events.

```python
# Wrong: subscribing to internal event streams
@domain.subscriber(stream="order")
class OrderSubscriber:
    def __call__(self, payload: dict) -> None:
        # This should be an event handler, not a subscriber!
        pass
```

**Correct approach:** Use event handlers for internal events, subscribers for external broker messages.

| Use Case | Element |
|----------|---------|
| React to internal domain events | `@domain.event_handler(part_of=Order)` |
| Consume external broker messages | `@domain.subscriber(stream="external_stream")` |

## 6. Business Logic in the Subscriber

**Wrong:**
```python
@domain.subscriber(stream="payment_gateway")
class PaymentSubscriber:
    def __call__(self, payload: dict) -> None:
        order = domain.repository_for(Order).get(payload["order_id"])
        # Business logic leaking into subscriber!
        if order.total_amount > 1000:
            order.status = "REQUIRES_REVIEW"
        else:
            order.status = "PAID"
        domain.repository_for(Order).add(order)
```

**Correct:** Keep business logic in the aggregate. Subscriber only orchestrates.

```python
@domain.subscriber(stream="payment_gateway")
class PaymentSubscriber:
    def __call__(self, payload: dict) -> None:
        order = domain.repository_for(Order).get(payload["order_id"])
        order.process_payment(payload["amount"])  # Logic in aggregate
        domain.repository_for(Order).add(order)
```

## 7. Letting External Schemas Leak into the Domain

**Wrong:**
```python
@domain.subscriber(stream="erp_events")
class ERPSubscriber:
    def __call__(self, payload: dict) -> None:
        # Passing external field names directly into domain!
        customer = Customer(
            name=payload["firstName"],  # External schema leaked!
            email=payload["emailAddress"],
        )
```

**Correct:** Translate external schemas at the subscriber boundary.

```python
@domain.subscriber(stream="erp_events")
class ERPSubscriber:
    def __call__(self, payload: dict) -> None:
        # Translate at the boundary
        name = f"{payload['firstName']} {payload['lastName']}"
        email = payload["emailAddress"]
        command = RegisterCustomer(name=name, email=email)
        domain.process(command)
```

The subscriber is the anti-corruption layer. It should be the ONLY place that understands the external format.

## Related

- [Basic Subscriber](./basic-subscriber.md) - Correct basic pattern
- [Anti-corruption Layer](./anti-corruption-layer.md) - Correct translation pattern
- [Error Handling](./error-handling.md) - Proper error handling
- `event-handler` - Internal event consumption (compare/contrast)
