# Command Issuance

Process managers drive other aggregates forward by issuing commands. This is the primary mechanism for coordinating multi-step business processes — the PM decides *what* should happen next, and the target aggregate's command handler decides *how*.

## Overview

Inside any PM handler method, call `current_domain.process()` to issue a command:

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

## Code

The complete command issuance example is in [assets/pm_command_issuance.py](../assets/pm_command_issuance.py).

`OrderPaymentPM` demonstrates two patterns:
1. **From event data**: `RequestPayment` constructed using `event.order_id` and `event.total`
2. **From PM state**: `CancelOrder` constructed using `self.order_id` (stored from a previous event)

## Import Path

Import `current_domain` from `protean` (the public API):

```python
from protean import current_domain
```

Do NOT import from `protean.utils.globals` — that is an internal module.

## Atomicity

Commands issued inside a handler are committed **atomically** as part of the same Unit of Work:

1. Handler runs (updates PM state, issues commands)
2. Transition event is persisted to PM's stream
3. Commands are enqueued for processing
4. Unit of Work commits everything atomically

If the handler fails (raises an exception), the entire operation is rolled back — no transition is persisted and no commands are issued.

## The Coordinator Pattern

Process managers should act purely as coordinators:

**Right** — PM decides WHAT, aggregate decides HOW:
```python
@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event: OrderPlaced) -> None:
    self.order_id = event.order_id
    self.status = "awaiting_payment"
    # PM issues command; Payment aggregate handles the details
    current_domain.process(
        RequestPayment(order_id=event.order_id, amount=event.total)
    )
```

**Wrong** — PM contains business logic:
```python
@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event: OrderPlaced) -> None:
    # Business rule validation belongs in the aggregate, not the PM
    if event.total > 10000:
        current_domain.process(RequestManualReview(...))
    else:
        current_domain.process(RequestPayment(...))
```

## Multiple Commands

A single handler can issue multiple commands:

```python
@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event: OrderPlaced) -> None:
    self.order_id = event.order_id
    self.status = "processing"
    current_domain.process(RequestPayment(order_id=event.order_id, amount=event.total))
    current_domain.process(ReserveInventory(order_id=event.order_id))
```

All commands are part of the same Unit of Work and committed together.

## Related

- [Lifecycle Management](./lifecycle.md) - How completion interacts with commands
- [Correlation](./correlation.md) - How events reach the PM to trigger commands
- [Command skill](../../command/SKILL.md) - Defining command classes
- [Command Handler skill](../../command-handler/SKILL.md) - Processing commands issued by PMs
