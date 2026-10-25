# Basic Subscriber

A subscriber that listens to a single external broker stream and performs a single action for each message. This is the simplest subscriber pattern.

## Walkthrough

### The Aggregate

```python
@domain.aggregate
class Payment:
    order_id: Identifier(required=True)
    amount: Decimal(precision=19, scale=4, required=True)
    status: String(choices=["PENDING", "CONFIRMED", "FAILED"], default="PENDING")

    def confirm(self):
        self.status = "CONFIRMED"
```

### The Subscriber

```python
@domain.subscriber(stream="payment_gateway")
class PaymentConfirmationSubscriber:
    def __call__(self, payload: dict) -> None:
        order_id = payload["order_id"]
        repo = domain.repository_for(Payment)
        payment = repo.find_by(order_id=order_id)
        payment.confirm()
        repo.add(payment)
```

### Testing with Sync Broker

```python
domain.config["message_processing"] = "sync"
domain.init(traverse=False)

with domain.domain_context():
    # Create prerequisite data
    payment = Payment(order_id="ORD-001", amount=99.99)
    domain.repository_for(Payment).add(payment)

    # Publish to broker stream (triggers subscriber in sync mode)
    domain.brokers["default"].publish(
        "payment_gateway",
        {"order_id": "ORD-001", "transaction_id": "txn-789"},
    )

    # Verify subscriber processed the message
    updated = domain.repository_for(Payment).find_by(order_id="ORD-001")
    assert updated.status == "CONFIRMED"
```

## Related

- [Anti-corruption Layer](./anti-corruption-layer.md): Translating external schemas into domain commands
- [Error Handling](./error-handling.md): Custom error recovery
- `event-handler`: Compare/contrast: internal event consumption
