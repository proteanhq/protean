# Saga lifecycle: start, intermediate, end

A saga is a process manager that coordinates a multi-step flow across several
aggregates. It has three kinds of handler, set by parameters on `@handle`.

## Start

A start handler opens the saga. Mark it `start=True`. When no instance exists yet
for that correlation value it creates one; when an open instance already exists
it loads that instance and runs on it. Once an instance is complete it is
skipped, so a repeated start event does not reopen a closed saga.

A saga needs at least one start handler, and it can have more than one: mark
every event that can begin the flow `start=True`, and whichever arrives first
creates the instance.

```python
@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event: OrderPlaced) -> None:
    self.order_id = event.order_id
    self.total = event.total
    self.status = "reserving_stock"
    current_domain.process(CreateReservation(order_id=event.order_id))
```

## Intermediate

An intermediate handler advances the flow: it updates the saga's state and
issues the command for the next step. It does not open or close the saga, so it
carries only `correlate`.

```python
@handle(StockReserved, correlate="order_id")
def on_stock_reserved(self, event: StockReserved) -> None:
    self.status = "awaiting_payment"
    current_domain.process(RequestPayment(order_id=self.order_id, amount=self.total))
```

## End

A terminal handler closes the saga. Mark it `end=True`. After it runs, the
framework marks the instance complete, and any later event for that correlation
value is skipped.

```python
@handle(ShipmentDispatched, correlate="order_id", end=True)
def on_shipment_dispatched(self, event: ShipmentDispatched) -> None:
    self.status = "fulfilled"
```

A saga usually has more than one terminal handler: one for the success path and
one for each failure path.

## PROCESS_MANAGER_UNCLOSED

`check` reports `PROCESS_MANAGER_UNCLOSED` when a process manager has handlers
but none is marked `end=True`. The rule reads handler metadata, not run-time
behavior. When no handler calls `mark_as_complete()` either, nothing retires an
instance: its instances stay open and it keeps matching later events for them.

Mark a terminating handler `end=True` on every path that ends the flow, and the
code clears. `mark_as_complete()` inside a handler also completes an instance at
run time, but the rule looks specifically for `end=True`, so use `end=True` to
clear the diagnostic. See [saga_before_unclosed.py](../assets/saga_before_unclosed.py)
for the flagged version and [saga_after_closed.py](../assets/saga_after_closed.py)
for the fix.
