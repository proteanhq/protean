---
description: Process manager patterns — lifecycle, correlation, state transitions, and completion rules
globs: "**/*.py"
---

# Process Manager Patterns

## Lifecycle Rules

Every `@handle` method on a process manager must specify `correlate`. At least one handler
must have `start=True`. Mark the terminating handler `end=True`. `self.mark_as_complete()`
also completes an instance, but `check` reports `PROCESS_MANAGER_UNCLOSED` for a process
manager with no `end=True` handler.

```python
@domain.aggregate
class Order:
    status = String(default="NEW")

@domain.event(part_of=Order)
class OrderPlaced:
    order_id = String(required=True)

@domain.event(part_of=Order)
class PaymentProcessed:
    order_id = String(required=True)

@domain.event(part_of=Order)
class OrderShipped:
    order_id = String(required=True)

@domain.process_manager(aggregates=[Order])
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
