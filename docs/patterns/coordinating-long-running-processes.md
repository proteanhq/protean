# Coordinating Long-Running Processes

## The Problem

An e-commerce system has three aggregates — Order, Payment, and Shipping —
each enforcing its own invariants and persisting independently. When a customer
places an order, the system must:

1. Accept the order
2. Request and confirm payment
3. Create and track shipment
4. Handle failures (declined payment, shipping delay) with compensation

The naive approach uses an event handler that hard-codes the entire workflow:

```python
@domain.event_handler(part_of=Order)
class OrderWorkflow:
    @handle(OrderPlaced)
    def start_payment(self, event):
        current_domain.process(RequestPayment(order_id=event.order_id, amount=event.total))

    @handle(PaymentConfirmed)
    def start_shipping(self, event):
        current_domain.process(CreateShipment(order_id=event.order_id))

    @handle(PaymentFailed)
    def cancel_order(self, event):
        current_domain.process(CancelOrder(order_id=event.order_id))
```

This breaks down quickly:

- **No state tracking.** The handler has no memory. If payment is confirmed
  but shipping fails, there is no record of what step the process is on.
  Debugging requires reconstructing the sequence from scattered event logs.

- **No correlation.** Each handler processes events in isolation. If two
  orders are in progress simultaneously, there is no built-in mechanism to
  ensure `PaymentConfirmed` is matched to the correct `OrderPlaced`.

- **No lifecycle.** There is no concept of "this process is done." The
  handler will process events for a completed order the same way it processes
  events for an active one.

- **No compensation.** When a step fails mid-process, there is no structured
  way to undo previous steps. Compensation logic gets scattered across
  multiple handlers with no central coordination point.

---

## The Pattern

A **Process Manager** is a stateful, event-driven coordinator that:

1. **Reacts to events** from multiple aggregate streams
2. **Correlates events** to the correct running instance via a shared identity
3. **Maintains its own state** — tracking which steps have completed and what
   data has been collected
4. **Issues commands** to drive other aggregates forward
5. **Manages its own lifecycle** — starting when an initiating event arrives
   and completing when the process reaches a terminal state

The process manager does not contain business logic. It is a coordinator:
it decides *what* should happen next based on the events it has seen, and
delegates the *how* to the appropriate aggregate via commands.

This is a well-established pattern in DDD and event-driven architectures,
documented by Vaughn Vernon, Greg Young, and the NServiceBus / MassTransit
communities. The key insight is that a multi-step process needs its own
first-class identity and state, separate from the aggregates it coordinates.

---

## How Protean Supports It

Protean provides a first-class `@domain.process_manager` element with:

- **Declarative correlation** via the `correlate` parameter on `@handle`
- **Automatic lifecycle** via `start=True`, `end=True`, and
  `mark_as_complete()`
- **Event-sourced persistence** — state is captured as transition events in
  the PM's own stream
- **Multi-stream subscriptions** — one PM listens to events from multiple
  aggregate streams
- **Command issuance** — handlers call `current_domain.process()` to drive
  other aggregates

---

## Applying the Pattern

### The Aggregates

Three aggregates, each with their own events:

```python
@domain.aggregate
class Order:
    customer_id = Identifier()
    total = Float()
    status = String(default="new")

@domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier()
    customer_id = Identifier()
    total = Float()

@domain.aggregate
class Payment:
    order_id = Identifier()
    amount = Float()

@domain.event(part_of=Payment)
class PaymentConfirmed:
    payment_id = Identifier()
    order_id = Identifier()
    amount = Float()

@domain.event(part_of=Payment)
class PaymentFailed:
    payment_id = Identifier()
    order_id = Identifier()
    reason = String()

@domain.aggregate
class Shipping:
    order_id = Identifier()

@domain.event(part_of=Shipping)
class ShipmentDelivered:
    order_id = Identifier()
```

### The Process Manager

```python
@domain.process_manager(
    stream_categories=[
        "ecommerce::order",
        "ecommerce::payment",
        "ecommerce::shipping",
    ]
)
class OrderFulfillmentPM:
    order_id = Identifier()
    payment_id = Identifier()
    status = String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event):
        self.order_id = event.order_id
        self.status = "awaiting_payment"
        current_domain.process(
            RequestPayment(order_id=event.order_id, amount=event.total)
        )

    @handle(PaymentConfirmed, correlate="order_id")
    def on_payment_confirmed(self, event):
        self.payment_id = event.payment_id
        self.status = "awaiting_shipment"
        current_domain.process(
            CreateShipment(order_id=self.order_id)
        )

    @handle(PaymentFailed, correlate="order_id", end=True)
    def on_payment_failed(self, event):
        self.status = "cancelled"
        current_domain.process(
            CancelOrder(order_id=self.order_id)
        )

    @handle(ShipmentDelivered, correlate="order_id")
    def on_shipment_delivered(self, event):
        self.status = "completed"
        self.mark_as_complete()
```

### What Happens at Runtime

1. `OrderPlaced` arrives → PM is created (`start=True`), status set to
   `awaiting_payment`, `RequestPayment` command issued.

2. `PaymentConfirmed` arrives → PM is loaded via `order_id` correlation,
   status set to `awaiting_shipment`, `CreateShipment` command issued.

3. `ShipmentDelivered` arrives → PM is loaded, status set to `completed`,
   `mark_as_complete()` called. Future events for this `order_id` are skipped.

**Failure path:** If `PaymentFailed` arrives instead of `PaymentConfirmed`,
the PM sets status to `cancelled`, issues `CancelOrder`, and `end=True`
auto-completes the PM. The shipping step never happens.

---

## Anti-Patterns

### Business Logic in the Process Manager

The PM should coordinate, not compute. If you find yourself validating
business rules, calculating totals, or enforcing invariants inside a PM
handler, move that logic into the aggregate or a domain service.

**Wrong:**
```python
def on_payment_confirmed(self, event):
    if event.amount < self.total * 0.95:
        # Business rule: reject underpayments
        current_domain.process(RejectPayment(...))
```

**Right:** The Payment aggregate enforces amount validation in its own
command handler. The PM only reacts to the resulting event.

### Missing Terminal States

A process manager without `mark_as_complete()` or `end=True` on any handler
will never finish. Its stream will grow indefinitely, and it will continue
accepting events even after the business process is logically complete.

### Inconsistent Correlation Keys

All events in a process must carry the same correlation field. If
`OrderPlaced` uses `order_id` but `PaymentConfirmed` uses `payment_order_id`,
the PM cannot route them to the same instance. Use a dictionary correlate to
map different field names: `correlate={"order_id": "payment_order_id"}`.

---

## Summary

| Concern | Without PM | With PM |
|---------|-----------|---------|
| State tracking | None — reconstruct from logs | Built-in, event-sourced |
| Correlation | Manual, error-prone | Declarative `correlate` parameter |
| Lifecycle | No concept of "done" | `start`, `end`, `mark_as_complete()` |
| Compensation | Scattered across handlers | Centralized in PM handlers |
| Multi-stream | Multiple independent handlers | Single PM subscribes to all |

---

!!! tip "Related reading"
    **Concepts:**

    - [Process Managers](../core-concepts/domain-elements/process-managers.md) — Coordinating multi-step processes across aggregates.

    **Guides:**

    - [Process Managers](../guides/consume-state/process-managers.md) — Defining process managers, correlation, lifecycle, and configuration.
