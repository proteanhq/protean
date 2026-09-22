# Saga lifecycle: start, intermediate, end

A saga is a process manager that coordinates a multi-step flow across several
aggregates. It has three kinds of handler, set by parameters on `@handle`.

## Start

Exactly one handler opens the saga. Mark it `start=True`. It runs when an event
arrives and no instance exists yet for that correlation value, so it creates a
new instance.

```python
@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event: OrderPlaced) -> None:
    self.order_id = event.order_id
    self.total = event.total
    self.status = "reserving_stock"
    current_domain.process(ReserveStock(order_id=event.order_id))
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
but none is marked `end=True`. Such a saga never retires an instance: its stream
grows without bound and it keeps accepting events forever.

Mark a terminating handler `end=True` on every path that ends the flow, and the
code clears. `mark_as_complete()` inside a handler also completes an instance at
run time, but the rule looks specifically for `end=True`, so use `end=True` to
clear the diagnostic. See [saga_before_unclosed.py](../assets/saga_before_unclosed.py)
for the flagged version and [saga_after_closed.py](../assets/saga_after_closed.py)
for the fix.
