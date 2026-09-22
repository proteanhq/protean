---
name: add-saga-flow
description: Build a complete saga in Protean using a process manager that coordinates a multi-step flow across several aggregates. The saga reacts to domain events, issues commands to drive each aggregate forward, tracks its own state, and closes on a terminal handler with a compensating path for failures. Use when the user asks to "add a saga", "coordinate a multi-step process", "orchestrate a workflow across aggregates", "manage order fulfillment", "add a process manager flow", "compensate on failure", "roll back a distributed transaction", or when they describe a flow like "reserve stock, take payment, then ship, and undo the reservation if payment fails".
license: Apache-2.0
compatibility: Requires Python 3.11+, protean framework
metadata:
  author: proteanhq
  version: "0.1"
  category: workflow
  composes: [process-manager, event, command, command-handler, event-handler]
  diagnostic_codes: [PROCESS_MANAGER_UNCLOSED]
---

# Add Saga Flow

A saga coordinates a business process that spans several aggregates. Each step
commits on its own, so there is no single transaction across the whole flow. A
process manager runs the saga: it reacts to events, keeps its own state, issues
the command for the next step, and closes when the flow reaches a terminal state.

This skill sequences the [process-manager](../process-manager/SKILL.md) element
skill into an end-to-end flow. Read that skill for the process manager itself.
This one shows how to build the whole saga around it.

## Worked example: order fulfillment

The saga coordinates four aggregates: Order, Inventory, Payment, and Shipping.
It is broker-free, so it initializes and runs the flow without any external
broker.

| Step | Event it reacts to | Command it issues | Handler kind |
|------|--------------------|-------------------|--------------|
| Start | `OrderPlaced` | `ReserveStock` | start |
| Reserve | `StockReserved` | `RequestPayment` | intermediate |
| Pay | `PaymentConfirmed` | `DispatchShipment` | intermediate |
| Ship | `ShipmentDispatched` | (none) | end (success) |
| Fail | `PaymentFailed` | `ReleaseReservation`, `CancelOrder` | end (compensating) |

The full flow is in [saga_after_closed.py](assets/saga_after_closed.py).

## Steps

### 1. Define the events and commands

The saga reacts to one [event](../event/SKILL.md) per step and issues one
[command](../command/SKILL.md) to drive the next aggregate. Name events in the
past tense (`OrderPlaced`, `StockReserved`) and commands in the imperative
(`ReserveStock`, `RequestPayment`). Every event carries the correlation field,
here `order_id`, so the saga can route each event to the right instance.

### 2. Pick the correlation key

Every handler names the field that ties events to one running saga instance:
`correlate="order_id"`. When a step's event names the field differently, map it
with a dict, for example `correlate={"order_id": "ext_order_ref"}`.

### 3. Write the start handler

Exactly one handler opens the saga. Mark it `start=True`. It stores the fields
the later steps need and issues the first command.

```python
@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event: OrderPlaced) -> None:
    self.order_id = event.order_id
    self.total = event.total
    self.status = "reserving_stock"
    current_domain.process(ReserveStock(order_id=event.order_id))
```

### 4. Write the intermediate handlers

Each intermediate handler advances the saga's state and issues the next command.
It carries only `correlate`. The command it issues is processed by that
aggregate's [command-handler](../command-handler/SKILL.md), which does the actual
work.

```python
@handle(StockReserved, correlate="order_id")
def on_stock_reserved(self, event: StockReserved) -> None:
    self.status = "awaiting_payment"
    current_domain.process(RequestPayment(order_id=self.order_id, amount=self.total))
```

### 5. Close the saga

Mark a terminating handler `end=True` on every path that ends the flow. The
success path closes when the shipment goes out:

```python
@handle(ShipmentDispatched, correlate="order_id", end=True)
def on_shipment_dispatched(self, event: ShipmentDispatched) -> None:
    self.status = "fulfilled"
```

The [saga lifecycle reference](references/saga-lifecycle.md) covers the start,
intermediate, and end handler kinds in full.

### 6. Compensate on the failure path

When a later step fails, the earlier steps have already committed. Undo them with
compensating commands, then end the saga. Here, a failed payment releases the
stock reservation and cancels the order:

```python
@handle(PaymentFailed, correlate="order_id", end=True)
def on_payment_failed(self, event: PaymentFailed) -> None:
    self.status = "cancelled"
    current_domain.process(ReleaseReservation(order_id=self.order_id))
    current_domain.process(CancelOrder(order_id=self.order_id))
```

The [compensation reference](references/compensation.md) covers the pattern in
full.

## The anti-pattern: an unclosed saga

A saga with handlers but no `end=True` on any of them never retires an instance.
Its stream grows without bound and it keeps accepting events. `check` reports
`PROCESS_MANAGER_UNCLOSED` for it.

[saga_before_unclosed.py](assets/saga_before_unclosed.py) is the flow with the
terminal handlers removed. It advances through every step and sets a `fulfilled`
status, yet no handler is marked `end=True`, so `check` flags it:

```
PROCESS_MANAGER_UNCLOSED  Process manager `OrderFulfillmentPM` has no handler
                          marked `end=True` to close its instances
```

The fix is [saga_after_closed.py](assets/saga_after_closed.py): mark a
terminating handler `end=True` on the success path and on the failure path.
Once each terminal path has an `end=True` handler, `check` no longer reports the
code.

`mark_as_complete()` inside a handler also completes an instance at run time. The
`PROCESS_MANAGER_UNCLOSED` rule looks for `end=True`, so mark the terminating
handler `end=True` to clear the diagnostic.

## Related skills

- [process-manager](../process-manager/SKILL.md): the element this saga is built
  from, with correlation, lifecycle, and command-issuance detail.
- [event](../event/SKILL.md): the events the saga reacts to.
- [command](../command/SKILL.md): the commands the saga issues.
- [command-handler](../command-handler/SKILL.md): processes the commands the saga
  issues.
- [event-handler](../event-handler/SKILL.md): the stateless alternative for a
  single event with no state to track across steps.

## Verify your work

- [Verify with check](../../references/verify-with-check.md): run `check` and
  resolve what it reports, including any `PROCESS_MANAGER_UNCLOSED`.
