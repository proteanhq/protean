# Compensation: undoing earlier steps on failure

A saga spans several aggregates, and each step commits on its own. There is no
shared transaction to roll back, so when a later step fails you undo the earlier
ones with compensating commands.

## The pattern

Add a handler for the failure event. It issues a compensating command for each
step already taken, then ends the saga.

```python
@handle(PaymentFailed, correlate="order_id", end=True)
def on_payment_failed(self, event: PaymentFailed) -> None:
    self.status = "cancelled"
    current_domain.process(CancelReservation(reservation_id=self.reservation_id))
    current_domain.process(CancelOrder(order_id=self.order_id))
```

By the time payment fails, the saga has already reserved stock, so it releases
that reservation and cancels the order.

Issuing a compensating command is not a rollback of the step it undoes. Each
command runs later as its own step against its target aggregate, so undoing the
earlier steps is a set of new steps, each committing on its own.

Whether a command issued just before the handler fails is written at all depends
on the event store. The memory store writes the command through the handler's
Unit of Work, so the failure discards it: raising inside a start handler that had
just issued a command left the store with zero commands and zero saga
transitions. Message-DB writes straight through on its own connection, so there
the command survives while the saga's transition does not. Do not design around
either case. Keep compensating commands idempotent so re-issuing one is safe.

## Points to keep in mind

- **A compensating command is a normal command.** The target aggregate's command
  handler decides how to undo the step. The saga only issues the command; it
  holds no business logic itself.
- **Compensate the steps that ran.** Track progress in the saga's state so the
  failure handler undoes the steps the flow actually reached. The handler above
  releases the reservation by the `reservation_id` the saga stored when the
  stock was reserved.
- **End every terminal path.** Mark the failure handler `end=True` so the saga
  closes after compensating. `check` reports `PROCESS_MANAGER_UNCLOSED` only when
  no handler in the whole process manager is marked `end=True`, so a closed
  success path hides an unclosed failure path from the check. Ending only the
  success path passes `check` while the failure path still leaves instances open.
  Mark each terminal handler `end=True` so every path that ends the flow closes
  its instance.

The full flow, with both the success terminal and the compensating failure
terminal, is in [saga_after_closed.py](../assets/saga_after_closed.py).
