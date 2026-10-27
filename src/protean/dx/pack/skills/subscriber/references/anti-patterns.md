# Subscriber Anti-patterns

## 1. Using @handle Decorator Instead of __call__

**Wrong:**
```python
# fragment
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

## 2. Expecting Typed Event Objects

**Wrong:**
```python
# fragment
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

## 3. Using event_processing Instead of message_processing

**Wrong:**
```python
domain.config["event_processing"] = "sync"  # Wrong config key!
```

**Correct:**
```python
domain.config["message_processing"] = "sync"  # Correct for subscribers
```

## 4. Confusing Subscribers with Event Handlers

**Wrong approach:** Using a subscriber to consume internal domain events.

```python
# fragment
# Wrong: subscribing to internal event streams
@domain.subscriber(stream="order")
class OrderSubscriber:
    def __call__(self, payload: dict) -> None:
        # This should be an event handler, not a subscriber!
        pass
```

**Correct approach:** Use an event handler, `@domain.event_handler(part_of=Order)`, for internal events, and a subscriber for external broker messages.

## 5. Business Logic in the Subscriber

The examples in this section use this aggregate:

```python
from decimal import Decimal as D


@domain.aggregate
class Order:
    total_amount: Decimal(precision=19, scale=4, default=0)
    amount_paid: Decimal(precision=19, scale=4, default=0)
    status: String(max_length=20, default="PENDING")

    def process_payment(self, amount: D) -> None:
        self.amount_paid = amount
        if self.total_amount > 1000:
            self.status = "REQUIRES_REVIEW"
        else:
            self.status = "PAID"
```

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

## 6. Letting External Schemas Leak into the Domain

The examples in this section use this aggregate and command:

```python
@domain.aggregate
class Customer:
    name: String(required=True)
    email: String(required=True)

@domain.command(part_of="Customer")
class RegisterCustomer:
    name: String(required=True)
    email: String(required=True)
```

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

## Related

- [Basic Subscriber](./basic-subscriber.md): Correct basic pattern
- [Anti-corruption Layer](./anti-corruption-layer.md): Correct translation pattern
- [Error Handling](./error-handling.md): Proper error handling
- `event-handler`: Internal event consumption (compare/contrast)
