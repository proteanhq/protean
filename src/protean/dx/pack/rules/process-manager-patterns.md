---
description: Process manager patterns — lifecycle, correlation, state transitions, and completion rules
globs: "**/*.py"
---

# Process Manager Patterns

## Lifecycle Rules

Every `@handle` method on a process manager must specify `correlate`. Exactly one handler
must have `start=True`. Use `end=True` or `self.mark_as_complete()` for terminal states.

```python
@domain.process_manager(part_of=OrderFulfillment)
class OrderFulfillmentProcess:
    order_id = String(identifier=True)
    status = String(default="STARTED")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event):
        self.status = "AWAITING_PAYMENT"

    @handle(PaymentProcessed, correlate="order_id")
    def on_payment(self, event):
        self.status = "PAID"

    @handle(OrderShipped, correlate="order_id", end=True)
    def on_shipped(self, event):
        self.status = "COMPLETED"
```

## Correlation Identity

`correlate="field"` means the PM instance identity is derived from `event.field`. Events
with the same field value update the same PM instance.

## Completed PMs Skip Events

Once a PM reaches `end=True` or calls `self.mark_as_complete()`, subsequent events with
the same correlation ID are silently skipped.

## State Assertions Only

Process managers track state via transitions. Assert `.status`, `.is_complete`, and
`.transition_count` — PMs coordinate, they don't own business logic.
