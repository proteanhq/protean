---
name: add-subscriber-flow
description: Build a complete external integration flow in Protean using subscribers. Subscribers consume messages from external systems via broker streams and translate them into domain actions using the anti-corruption layer (ACL) pattern. Use when the user asks to "add an external integration", "consume external events", "handle webhook events", "integrate with an external system", "add a subscriber flow", "build an anti-corruption layer", "translate external messages", "process broker messages", or when they describe scenarios like "when the payment gateway confirms", "when the ERP syncs users", "react to external system notifications".
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [subscriber, command, command-handler, aggregate]
---

# Add Subscriber Flow

A subscriber flow bridges external systems with your domain. It consumes raw messages from broker streams and translates them into domain-native commands or aggregate operations.

## What this creates

| Component | Purpose | Decorator |
|-----------|---------|-----------|
| Subscriber | Consume external broker messages | `@domain.subscriber(stream=...)` |
| Anti-corruption translation | Convert external format to domain language | Methods on subscriber |
| Command (optional) | Domain-native command from external data | `@domain.command(part_of=...)` |
| Command Handler (optional) | Process the translated command | `@domain.command_handler(part_of=...)` |
| Aggregate | Domain entity being updated | `@domain.aggregate` |

## Information to gather

Before building a subscriber flow, understand:

- [ ] **What external system sends messages?** — Payment gateway, ERP, third-party API, etc.
- [ ] **What stream name to listen to?** — The broker stream name (e.g., `"payment_gateway"`, `"erp_events"`)
- [ ] **What does the external payload look like?** — JSON structure, field names, conventions (camelCase, nested, etc.)
- [ ] **What domain action should result?** — Create aggregate, update state, dispatch command
- [ ] **What translation is needed?** — Field mapping, naming conventions, data transformation

## Process

### Step 1: Define the subscriber

A subscriber listens to a named broker stream. It implements `__call__` with a `payload: dict` parameter.

```python
@domain.subscriber(stream="payment_gateway")
class PaymentSubscriber:
    def __call__(self, payload: dict) -> None:
        # payload is always a raw dict from the external broker
        event_type = payload.get("type")
        if event_type == "payment.confirmed":
            self._handle_payment_confirmed(payload["data"])

    def _handle_payment_confirmed(self, data: dict) -> None:
        # Translate and act on the external message
        ...
```

**Key rules for subscribers** (see [subscriber](../subscriber/SKILL.md)):
- `stream` parameter is required — names the broker stream to listen to
- `__call__(self, payload: dict)` — only method to implement
- Payload is always a raw `dict` — no typed events, no Protean objects
- Subscriber is the anti-corruption boundary — only place that knows external format

### Step 2: Design the anti-corruption translation

The subscriber translates external data formats into domain language. This is the key DDD concept: the **Anti-Corruption Layer (ACL)**.

```python
def _handle_payment_confirmed(self, data: dict) -> None:
    # External format (camelCase, external IDs):
    #   {"orderId": "ext-123", "amountPaid": 99.99, "paymentMethod": "card"}
    #
    # Domain format (snake_case, domain language):
    #   ConfirmPayment(order_id="ext-123", amount=99.99)

    command = ConfirmPayment(
        order_id=data["orderId"],
        amount=data["amountPaid"],
    )
    domain.process(command)
```

### Step 3: Choose the integration pattern

**Pattern A: Subscriber → Command → Handler → Aggregate**

For complex flows where the domain action warrants a full command flow:

```python
@domain.subscriber(stream="erp_events")
class ERPSubscriber:
    def __call__(self, payload: dict) -> None:
        if payload["type"] == "user.created":
            command = RegisterCustomer(
                name=f"{payload['firstName']} {payload['lastName']}",
                email=payload["email"],
            )
            domain.process(command)
```

**Pattern B: Subscriber → Aggregate directly**

For simpler flows where the subscriber can directly update the aggregate:

```python
@domain.subscriber(stream="payment_gateway")
class PaymentSubscriber:
    def __call__(self, payload: dict) -> None:
        if payload["status"] == "SUCCESS":
            order = domain.repository_for(Order).get(payload["order_id"])
            order.mark_paid()
            domain.repository_for(Order).add(order)
```

### Step 4: Enable synchronous processing (for testing)

```python
domain.config["message_processing"] = "sync"
domain.config["command_processing"] = "sync"  # if dispatching commands
```

### Step 5: Publish test messages

In tests, use the broker to simulate external messages:

```python
domain.brokers["default"].publish(
    "payment_gateway",
    {"order_id": "ORD-001", "status": "SUCCESS"},
)
```

## The anti-corruption layer (ACL)

The ACL is a DDD pattern that protects your domain from external system changes:

```
External System → [Broker Stream] → Subscriber (ACL) → Domain Command/Aggregate
                                     ↑
                                     Only place that knows external format
```

**Why ACL matters:**
- External formats change without notice — the ACL absorbs changes
- Domain language stays clean — no camelCase, no external IDs leaking in
- Single point of translation — when the external system changes, only the subscriber changes
- Domain remains testable — test domain logic without external system dependencies

## Common external payload patterns

| External System | Typical Format | Translation Needed |
|----------------|---------------|-------------------|
| REST webhook | camelCase JSON | Field renaming, flatten nested |
| ERP system | Custom schema with IDs | Map IDs, combine fields |
| Payment gateway | Status codes | Map codes to domain states |
| Message queue | Envelope + body | Unwrap envelope, parse body |

## Common mistakes

### Letting external formats leak into the domain

```python
# Wrong! Raw external payload pushed into domain logic
def __call__(self, payload: dict) -> None:
    order = domain.repository_for(Order).get(payload["orderId"])
    order.apply(payload)  # camelCase + external IDs leak into the aggregate
```

Instead: translate at the subscriber (the ACL) into domain language first, then act.

### Business logic in the subscriber

```python
# Wrong! Domain rules enforced in the ACL
def __call__(self, payload: dict) -> None:
    if payload["amountPaid"] >= order.total:   # rule belongs on the aggregate
        order.mark_paid()
```

Instead: the subscriber only translates and delegates; rules live on the aggregate or a command handler.

### Typing the payload as a domain event

```python
# Wrong! Subscribers receive raw dicts, not typed events
def __call__(self, payload: PaymentConfirmed) -> None:
    ...
```

Instead: `def __call__(self, payload: dict)` — it is always a raw dict from the broker.

### Forgetting sync processing in tests

```python
# Wrong! Nothing processes the published message
domain.brokers["default"].publish("payment_gateway", {"order_id": "O-1"})
assert order.is_paid  # fails — subscriber never ran
```

Instead: set `domain.config["message_processing"] = "sync"` (and `command_processing` if you dispatch commands) in tests.

## Complete examples

- [Subscriber with command dispatch](assets/subscriber_with_command.py) — Full ACL: external event → command → handler → aggregate
- [Subscriber with direct update](assets/subscriber_direct_update.py) — Simple: external webhook → aggregate update
- [Subscriber with event routing](assets/subscriber_event_routing.py) — Multiple external event types routed to different handlers

## Detailed references

- [Anti-Corruption Layer Pattern](references/anti-corruption-layer.md) — ACL design principles and translation strategies
- [External Integration Patterns](references/external-integration.md) — Command dispatch vs direct update patterns

## Related skills

- [subscriber](../subscriber/SKILL.md) — Subscriber definition and stream configuration
- [command](../command/SKILL.md) — Command definition for translated actions
- [command-handler](../command-handler/SKILL.md) — Processing translated commands
- [add-use-case](../add-use-case/SKILL.md) — Full command flow (complement to subscriber flow)

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and resolve what it reports
