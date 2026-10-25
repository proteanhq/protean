# Command Issuance

Process managers drive other aggregates forward by issuing commands. The PM decides *what* should happen next, and the target aggregate's command handler decides *how*.

## Overview

Inside any PM handler method, call `current_domain.process()` to issue a command. Build the command from event data (`RequestPayment(order_id=event.order_id, amount=event.total)`) or from PM state an earlier handler stored (`CancelOrder(order_id=self.order_id)`).

## Import Path

Import `current_domain` from `protean` (the public API): `from protean import current_domain`. Do NOT import from `protean.utils.globals`. That is an internal module.

## Command persistence

Each PM handler runs inside a Unit of Work:

1. Handler runs, updating PM state and calling `current_domain.process()` to issue commands
2. When the handler returns, the framework appends the PM's transition event to the PM's own stream

If the handler raises after issuing a command, the Unit of Work rolls back the PM's state change. Whether the command is written at all depends on the event store. The memory store writes the command through the handler's Unit of Work, so the failure discards it. Message-DB writes straight through on its own connection, so there the command survives while the transition does not. Do not rely on either behavior. Keep issued commands idempotent so re-issuing one is safe.

## The Coordinator Pattern

The SKILL.md's `on_order_placed` shows the right shape: the PM issues `RequestPayment`, and the Payment aggregate handles the details. A PM that branches on a business rule (`if event.total > 10000: ...`) is doing the aggregate's job. [Anti-patterns](./anti-patterns.md) shows the fix.

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

- [Lifecycle Management](./lifecycle.md): How completion interacts with commands
- [Correlation](./correlation.md): How events reach the PM to trigger commands
- [Command skill](../../command/SKILL.md): Defining command classes
- [Command Handler skill](../../command-handler/SKILL.md): Processing commands issued by PMs
