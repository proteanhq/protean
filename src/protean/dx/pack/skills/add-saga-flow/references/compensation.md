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
    current_domain.process(ReleaseReservation(order_id=self.order_id))
    current_domain.process(CancelOrder(order_id=self.order_id))
```

By the time payment fails, the saga has already reserved stock, so it releases
that reservation and cancels the order. Commands issued inside a handler commit
atomically with the saga's own transition, in one Unit of Work.

## Points to keep in mind

- **A compensating command is a normal command.** The target aggregate's command
  handler decides how to undo the step. The saga only issues the command; it
  holds no business logic itself.
- **Compensate the steps that ran.** Track progress in the saga's state so the
  failure handler undoes the steps the flow actually reached.
- **End the failure path.** Mark the failure handler `end=True` so the saga
  closes after compensating. A failure path with no terminal leaves the saga
  open and `check` reports `PROCESS_MANAGER_UNCLOSED`.

The full flow, with both the success terminal and the compensating failure
terminal, is in [saga_after_closed.py](../assets/saga_after_closed.py).
