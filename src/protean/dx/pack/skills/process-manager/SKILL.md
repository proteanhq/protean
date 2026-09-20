---
name: process-manager
description: "Define a Protean process manager - a stateful, event-driven coordinator that manages multi-step business processes spanning multiple aggregates. Process managers maintain their own event-sourced state, correlate related events to the same running instance via correlation keys, have a defined lifecycle (start, intermediate, end), and issue commands to drive other aggregates forward. Unlike stateless event handlers, process managers remember what has happened and decide what to do next. Use when you need to coordinate a multi-aggregate workflow, manage a saga, orchestrate a business process, track process state across events, implement eventual consistency with compensation, or when the user asks to 'create a process manager', 'coordinate aggregates', 'manage a workflow', 'add a saga', 'track order fulfillment', or 'orchestrate a multi-step process'."
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: element
---

# Process Manager

## Basic structure

```python
from protean import Domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(__file__, "ecommerce")

@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    customer_id: Identifier(required=True)
    total: Float(required=True)

@domain.event(part_of="Payment")
class PaymentConfirmed:
    payment_id: Identifier(required=True)
    order_id: Identifier(required=True)

@domain.aggregate
class Order:
    customer_id: Identifier(required=True)
    total: Float(required=True)

@domain.aggregate
class Payment:
    order_id: Identifier(required=True)

@domain.process_manager(
    stream_categories=["ecommerce::order", "ecommerce::payment"]
)
class OrderFulfillmentPM:
    order_id: Identifier()
    status: String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.status = "awaiting_payment"

    @handle(PaymentConfirmed, correlate="order_id")
    def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
        self.status = "completed"
        self.mark_as_complete()
```

## Key rules

1. **Requires `stream_categories` or `aggregates`** — PM must subscribe to at least one event stream: `@domain.process_manager(stream_categories=["domain::order", "domain::payment"])`. Alternatively, pass `aggregates=[Order, Payment]` and Protean infers the stream categories
2. **Use `@handle` with PM-specific parameters** — Each handler uses `@handle(EventClass, start=..., correlate=..., end=...)`. These three parameters control lifecycle and routing
3. **Every handler must specify `correlate`** — Maps events to PM instances: `correlate="order_id"` (string) or `correlate={"order_id": "ext_order_ref"}` (dict when names differ)
4. **Exactly one handler must have `start=True`** — The entry point that creates new PM instances. If a non-start event arrives with no existing PM, it is silently skipped
5. **Handler methods take self and event** — Signature: `def method_name(self, event: EventType) -> None`
6. **No return values** — Process managers follow fire-and-forget pattern. Return values are discarded
7. **Import `handle` from `protean`** — `from protean import handle` (not from `protean.core` or `protean.utils`)
8. **Issue commands via `current_domain.process()`** — Import from `protean`: `from protean import current_domain`. Call `current_domain.process(CommandClass(...))` to drive other aggregates
9. **Always define at least one terminal state** — Use `end=True` on a handler or call `self.mark_as_complete()` inside a handler. Without this, the PM accepts events indefinitely
10. **PM fields are persisted as transition events** — After each handler runs, the framework auto-generates a transition event capturing all field values and persists it to the PM's own stream
11. **Completed PMs skip subsequent events** — Once a PM is marked complete, any further events for that correlation value are silently skipped

## Process manager options

| Option | Purpose | Required |
|--------|---------|----------|
| `stream_categories` | List of stream categories to subscribe to | Yes (unless `aggregates` provided) |
| `aggregates` | List of aggregate classes (categories inferred) | Alternative to `stream_categories` |
| `subscription_type` | `"stream"` or `"event_store"` | No |
| `subscription_profile` | `"production"`, `"fast"`, `"batch"`, `"debug"`, `"projection"` | No |
| `subscription_config` | Custom config dict (messages_per_tick, max_retries, etc.) | No |

## @handle parameters for process managers

| Parameter | Purpose | Required |
|-----------|---------|----------|
| First arg (event class) | The event class this handler processes | Yes |
| `start` | `True` creates new PM instance (exactly one per PM) | One handler must have `True` |
| `correlate` | String or dict mapping event field to PM identity | Yes (all PM handlers) |
| `end` | `True` auto-marks PM as complete after handler runs | No |

## Quick example: Dictionary correlation

When PM field names differ from event field names, use a dictionary:

```python
@domain.process_manager(stream_categories=["billing::invoice"])
class PaymentReconciliationPM:
    order_id: Identifier()
    status: String(default="pending")

    @handle(
        ExternalPaymentReceived,
        start=True,
        correlate={"order_id": "ext_order_ref"},
    )
    def on_payment_received(self, event: ExternalPaymentReceived) -> None:
        self.order_id = event.ext_order_ref
        self.status = "received"
        self.mark_as_complete()
```

This extracts `event.ext_order_ref` and maps it to the PM's `order_id` field.

## Quick example: Issuing commands

Process managers drive other aggregates forward by issuing commands:

```python
from protean import current_domain

@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event: OrderPlaced) -> None:
    self.order_id = event.order_id
    self.status = "awaiting_payment"
    current_domain.process(
        RequestPayment(order_id=event.order_id, amount=event.total)
    )
```

Commands issued inside a handler are committed atomically as part of the same Unit of Work.

## Process manager vs event handler

| Aspect | Event Handler | Process Manager |
|--------|---------------|-----------------|
| **State** | Stateless | Stateful (event-sourced) |
| **Correlation** | None | Explicit via `correlate` |
| **Lifecycle** | N/A | start → intermediate → end |
| **Persistence** | None | Auto-generated transition events |
| **Multi-stream** | Typically single aggregate | Multiple aggregate streams |

**Use an event handler** when each event is handled independently with no memory of prior events.

**Use a process manager** when you need to track state across multiple events from different aggregates to coordinate a multi-step business process.

## Error handling

Override `handle_error` classmethod for custom error recovery during async processing:

```python
@domain.process_manager(stream_categories=["onboarding::account"])
class OnboardingPM:
    account_id: Identifier()
    status: String(default="new")

    @handle(AccountCreated, start=True, correlate="account_id")
    def on_account_created(self, event) -> None:
        self.account_id = event.account_id
        self.status = "awaiting_verification"

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        logger.error(f"Onboarding PM failed: {exc}")
```

## Common mistakes

### Missing `correlate` on handlers

```python
# WRONG — correlate is required for all PM handlers
@handle(OrderPlaced, start=True)
def on_order_placed(self, event):
    pass
```

Instead: Always specify `correlate` on every PM handler

```python
# CORRECT
@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event):
    self.order_id = event.order_id
```

### No `start=True` handler

```python
# WRONG — PM has no entry point
@domain.process_manager(stream_categories=["ecommerce::order"])
class BadPM:
    @handle(OrderPlaced, correlate="order_id")  # Missing start=True
    def on_order_placed(self, event):
        pass
```

Every PM must have exactly one handler with `start=True`.

### Business logic in the process manager

```python
# WRONG — PM is doing business validation
@handle(PaymentConfirmed, correlate="order_id")
def on_payment_confirmed(self, event):
    if event.amount < self.total * 0.95:
        current_domain.process(RejectPayment(...))
```

Instead: Keep business logic in aggregates. PM only coordinates.

### Missing terminal state

A PM without `end=True` or `mark_as_complete()` on any handler will never finish. Its stream will grow indefinitely and it will continue accepting events.

### Inconsistent correlation keys

All events in a process must carry the same correlation field. If `OrderPlaced` uses `order_id` but `PaymentConfirmed` uses `payment_order_id`, the PM cannot route them to the same instance. Use dictionary correlate to map different names: `correlate={"order_id": "payment_order_id"}`.

### Using event handler when process manager is needed

If you find yourself tracking state in external stores from an event handler, or needing to correlate events across aggregates, you need a process manager — not an event handler with workarounds.

## Detailed references

### Core Concepts
- [Correlation](references/correlation.md) - String vs dictionary correlation, routing mechanics
- [Lifecycle Management](references/lifecycle.md) - Start events, completion, transition events
- [Command Issuance](references/command-issuance.md) - Issuing commands, coordinator pattern, atomicity
- [Anti-patterns](references/anti-patterns.md) - Common mistakes and how to avoid them

### Complete Examples
- [Basic PM (Order Fulfillment)](assets/pm_basic.py) - Full lifecycle with string correlation
- [Dictionary Correlation](assets/pm_dict_correlation.py) - Mapping different field names
- [Command Issuance](assets/pm_command_issuance.py) - Issuing commands via current_domain.process()
- [Error Handling](assets/pm_error_handling.py) - Custom handle_error classmethod

### Related Skills
- `event-handler` - Stateless event handlers (contrast with stateful PM)
- `event` - Events are the input to process managers
- `aggregate` - Process managers coordinate aggregates
- `command` - Process managers issue commands to drive aggregates
- `command-handler` - Commands issued by PMs are processed by command handlers
