# Command Issuance

Process managers drive other aggregates forward by issuing commands. This is the primary mechanism for coordinating multi-step business processes — the PM decides *what* should happen next, and the target aggregate's command handler decides *how*.

## Overview

Inside any PM handler method, call `current_domain.process()` to issue a command:

```python
# fragment
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

## Command persistence

Each PM handler runs inside a Unit of Work:

1. Handler runs, updating PM state and calling `current_domain.process()` to issue commands
2. When the handler returns, the framework appends the PM's transition event to the PM's own stream

If the handler raises after issuing a command, the Unit of Work rolls back the PM's state change. Whether the command is written at all depends on the event store. The memory store writes the command through the handler's Unit of Work, so the failure discards it. Message-DB writes straight through on its own connection, so there the command survives while the transition does not. Do not rely on either behavior. Keep issued commands idempotent so re-issuing one is safe.

## The Coordinator Pattern

Process managers should act purely as coordinators:

**Right** — PM decides WHAT, aggregate decides HOW:
```python
# fragment
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
# fragment
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
# fragment
@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event: OrderPlaced) -> None:
    self.order_id = event.order_id
    self.status = "processing"
    current_domain.process(RequestPayment(order_id=event.order_id, amount=event.total))
    current_domain.process(ReserveInventory(order_id=event.order_id))
```

Each `process()` call issues one command. [Command persistence](#command-persistence) covers what happens to them if the handler fails.

## Related

- [Lifecycle Management](./lifecycle.md) - How completion interacts with commands
- [Correlation](./correlation.md) - How events reach the PM to trigger commands
- [Command skill](../../command/SKILL.md) - Defining command classes
- [Command Handler skill](../../command-handler/SKILL.md) - Processing commands issued by PMs
