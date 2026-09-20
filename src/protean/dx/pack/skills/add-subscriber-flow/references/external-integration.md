# External Integration Patterns

## Pattern A: Subscriber → Command → Handler → Aggregate

The subscriber translates the external message into a domain command and dispatches it via `domain.process()`.

```python
@domain.subscriber(stream="erp_events")
class ERPSubscriber:
    def __call__(self, payload: dict) -> None:
        command = RegisterEmployee(
            employee_id=payload["empId"],
            name=f"{payload['firstName']} {payload['lastName']}",
        )
        domain.process(command)
```

**Advantages:**
- Full command validation (Layer 1 field checks)
- Handler guards available (Layer 4 authorization)
- Command is a reusable domain contract
- Clear separation: translation vs business logic

**Best for:** Complex actions, actions that need authorization, reusable commands.

## Pattern B: Subscriber → Aggregate directly

The subscriber loads the aggregate from repository and calls methods directly.

```python
@domain.subscriber(stream="payment_gateway")
class PaymentSubscriber:
    def __call__(self, payload: dict) -> None:
        order = domain.repository_for(Order).get(payload["orderId"])
        order.mark_paid()
        domain.repository_for(Order).add(order)
```

**Advantages:**
- Simpler, fewer components
- Direct aggregate access
- Less boilerplate

**Best for:** Simple status updates, single aggregate mutations, no authorization needed.

## Configuration

Subscribers need `message_processing` set to `"sync"` for testing:

```python
domain.config["message_processing"] = "sync"
```

If the subscriber dispatches commands, also set:

```python
domain.config["command_processing"] = "sync"
```

## Publishing test messages

Use the broker to simulate external messages in tests:

```python
domain.brokers["default"].publish(
    "stream_name",
    {"key": "value"},
)
```
