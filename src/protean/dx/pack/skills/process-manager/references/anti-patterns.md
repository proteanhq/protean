# Anti-patterns

Common mistakes when defining process managers and how to avoid them.

## 1. Missing `correlate` on Handlers

Every handler in a process manager must specify a `correlate` parameter. Without it, the framework cannot route events to PM instances.

**Wrong:**
```python
@handle(OrderPlaced, start=True)  # Missing correlate!
def on_order_placed(self, event: OrderPlaced) -> None:
    self.order_id = event.order_id
```

**Right:**
```python
@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event: OrderPlaced) -> None:
    self.order_id = event.order_id
```

Protean raises `ConfigurationError` during `domain.init()` if any PM handler is missing `correlate`.

## 2. No `start=True` Handler

Every process manager must have exactly one handler marked with `start=True`. Without it, no new PM instances can be created.

**Wrong:**
```python
@domain.process_manager(stream_categories=["ecommerce::order"])
class OrderPM:
    @handle(OrderPlaced, correlate="order_id")  # No start=True!
    def on_order_placed(self, event) -> None:
        pass
```

**Right:**
```python
@domain.process_manager(stream_categories=["ecommerce::order"])
class OrderPM:
    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event) -> None:
        pass
```

Protean raises `IncorrectUsageError` during `domain.init()` if no handler has `start=True`.

## 3. Business Logic in the Process Manager

The PM should coordinate, not compute. If you find yourself validating business rules, calculating totals, or enforcing invariants inside a PM handler, move that logic into the aggregate or a domain service.

**Wrong:**
```python
@handle(PaymentConfirmed, correlate="order_id")
def on_payment_confirmed(self, event):
    if event.amount < self.total * 0.95:  # Business rule in PM!
        current_domain.process(RejectPayment(...))
    else:
        current_domain.process(ConfirmShipment(...))
```

**Right:**
The Payment aggregate enforces amount validation in its command handler. The PM only reacts to the resulting event (PaymentConfirmed or PaymentRejected).

## 4. Missing Terminal State

A process manager without `mark_as_complete()` or `end=True` on any handler will never finish. Its stream will grow indefinitely, and it will continue accepting events even after the business process is logically complete.

**Wrong:**
```python
@domain.process_manager(stream_categories=["ecommerce::order"])
class OrderPM:
    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event) -> None:
        self.status = "processing"

    @handle(OrderShipped, correlate="order_id")
    def on_shipped(self, event) -> None:
        self.status = "shipped"  # Logically done, but PM never completes!
```

**Right:**
```python
    @handle(OrderShipped, correlate="order_id")
    def on_shipped(self, event) -> None:
        self.status = "shipped"
        self.mark_as_complete()  # PM properly terminates
```

## 5. Inconsistent Correlation Keys

All events in a process must carry the same correlation field so they route to the same PM instance. If events from different aggregates use different field names, use dictionary correlation.

**Wrong:**
```python
@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event) -> None: ...

@handle(PaymentConfirmed, correlate="payment_order_id")  # Different field!
def on_payment(self, event) -> None: ...
```

The PM cannot route `PaymentConfirmed` because `payment_order_id` doesn't match PM's `order_id`.

**Right** — Use dictionary correlation:
```python
@handle(PaymentConfirmed, correlate={"order_id": "payment_order_id"})
def on_payment(self, event) -> None: ...
```

## 6. Using Event Handler When Process Manager Is Needed

If you find yourself:
- Tracking state in external stores from an event handler
- Needing to correlate events across multiple aggregates
- Building conditional logic based on what events have been seen before
- Managing compensation for multi-step processes

...you need a process manager, not an event handler with workarounds.

**Wrong:**
```python
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

**Right** — Use a process manager for stateful, multi-step coordination.

## 7. Returning Values from PM Handlers

Process manager handlers do not return values. Return values are silently discarded.

**Wrong:**
```python
@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event) -> None:
    return {"status": "started"}  # Discarded!
```

**Right:**
Update PM state directly and issue commands if needed.

## 8. Manually Wrapping in UnitOfWork

Each PM handler runs within an implicit UnitOfWork. Do not wrap manually.

**Wrong:**
```python
from protean.core.unit_of_work import UnitOfWork

@handle(OrderPlaced, start=True, correlate="order_id")
def on_order_placed(self, event) -> None:
    with UnitOfWork():  # Unnecessary and can cause issues
        self.status = "processing"
```

**Right:**
Let the framework manage the UnitOfWork automatically.

## Related

- [Correlation](./correlation.md) - Correct correlation patterns
- [Lifecycle Management](./lifecycle.md) - Terminal states and completion
- [Command Issuance](./command-issuance.md) - Coordinator pattern
