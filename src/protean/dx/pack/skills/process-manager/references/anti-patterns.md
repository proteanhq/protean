# Anti-patterns

## 1. Missing `correlate` on Handlers

Every handler in a process manager must specify a `correlate` parameter. Without it, the framework cannot route events to PM instances.

**Wrong:**
```python
# fragment
@handle(OrderPlaced, start=True)  # Missing correlate!
def on_order_placed(self, event: OrderPlaced) -> None:
    self.order_id = event.order_id
```

Protean raises `IncorrectUsageError` during `domain.init()` if any PM handler is missing `correlate`.

## 2. Business Logic in the Process Manager

The PM should coordinate, not compute. If you find yourself validating business rules, calculating totals, or enforcing invariants inside a PM handler, move that logic into the aggregate or a domain service.

**Wrong:**
```python
# fragment
from decimal import Decimal as D


@handle(PaymentConfirmed, correlate="order_id")
def on_payment_confirmed(self, event):
    if event.amount < self.total * D("0.95"):  # Business rule in PM!
        current_domain.process(RejectPayment(...))
    else:
        current_domain.process(ConfirmShipment(...))
```

**Right:**
The Payment aggregate enforces amount validation in its command handler. The PM only reacts to the resulting event (PaymentConfirmed or PaymentRejected).

## 3. Using Event Handler When Process Manager Is Needed

If you find yourself:
- Tracking state in external stores from an event handler
- Needing to correlate events across multiple aggregates
- Building conditional logic based on what events have been seen before
- Managing compensation for multi-step processes

...you need a process manager, not an event handler with workarounds.

**Wrong:**
```python
# fragment
@domain.event_handler(part_of=Order)
class OrderWorkflow:
    # Stateless handler trying to do stateful work
    @handle(OrderPlaced)
    def start_payment(self, event):
        current_domain.process(RequestPayment(order_id=event.order_id))

    @handle(PaymentFailed)
    def cancel_order(self, event):
        # No state tracking, no correlation, no lifecycle
        current_domain.process(CancelOrder(order_id=event.order_id))
```

**Right**: Use a process manager for stateful, multi-step coordination.

## 4. Manually Wrapping in UnitOfWork

Each PM handler runs within an implicit UnitOfWork. Do not wrap manually.

**Wrong:**
```python
# fragment
from protean.core.unit_of_work import UnitOfWork

@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event) -> None:
    with UnitOfWork():  # Unnecessary and can cause issues
        self.status = "processing"
```

**Right:**
Let the framework manage the UnitOfWork automatically.

## Related

- [Correlation](./correlation.md): Correct correlation patterns
- [Lifecycle Management](./lifecycle.md): Terminal states and completion
- [Command Issuance](./command-issuance.md): Coordinator pattern
