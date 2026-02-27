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

- **No idempotency.** If `PaymentConfirmed` is delivered twice (e.g., server
  crash before subscription position is persisted), `CreateShipment` is
  issued twice. Two shipments are created for one order.

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

Four aggregates participate in order fulfillment — `Order`, `Payment`,
`Inventory`, and `Shipping`. Each publishes events that the PM reacts to,
and each accepts commands that the PM issues:

```python
from protean.fields import Auto, Float, Identifier, String

# --- Events the PM reacts to ---

@domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    total = Float()

@domain.event(part_of=Payment)
class PaymentConfirmed:
    payment_id = Identifier(required=True)
    order_id = Identifier(required=True)
    amount = Float()

@domain.event(part_of=Payment)
class PaymentFailed:
    payment_id = Identifier(required=True)
    order_id = Identifier(required=True)
    reason = String()

@domain.event(part_of=Inventory)
class InventoryReserved:
    order_id = Identifier(required=True)
    product_id = Identifier(required=True)

@domain.event(part_of=Inventory)
class InventoryReservationFailed:
    order_id = Identifier(required=True)
    reason = String()

@domain.event(part_of=Shipping)
class ShipmentCreated:
    shipment_id = Identifier(required=True)
    order_id = Identifier(required=True)

@domain.event(part_of=Shipping)
class ShipmentDelivered:
    shipment_id = Identifier(required=True)
    order_id = Identifier(required=True)

@domain.event(part_of=Shipping)
class ShipmentRejected:
    shipment_id = Identifier(required=True)
    order_id = Identifier(required=True)
    reason = String()

# --- Timeout event (published by an external scheduled job) ---

@domain.event(part_of=Order)
class OrderFulfillmentTimedOut:
    order_id = Identifier(required=True)
    stalled_status = String()

# --- Commands the PM issues ---

@domain.command(part_of=Inventory)
class ReserveInventory:
    order_id = Identifier(required=True)

@domain.command(part_of=Inventory)
class ReleaseInventory:
    order_id = Identifier(required=True)

@domain.command(part_of=Payment)
class RequestPayment:
    order_id = Identifier(required=True)
    amount = Float()

@domain.command(part_of=Payment)
class RefundPayment:
    order_id = Identifier(required=True)
    payment_id = Identifier(required=True)

@domain.command(part_of=Shipping)
class CreateShipment:
    order_id = Identifier(required=True)

@domain.command(part_of=Shipping)
class CancelShipment:
    order_id = Identifier(required=True)
    shipment_id = Identifier(required=True)

@domain.command(part_of=Order)
class CancelOrder:
    order_id = Identifier(required=True)
    reason = String()
```

### The Process Manager

A production-ready PM is built around five principles: design it as a state
machine, make every handler idempotent, handle out-of-order events, design
compensation explicitly, and handle timeouts.

```python
from protean import handle
from protean.fields import Identifier, String
from protean.globals import current_domain


@domain.process_manager(
    stream_categories=[
        "ecommerce::order",
        "ecommerce::payment",
        "ecommerce::inventory",
        "ecommerce::shipping",
    ]
)
class OrderFulfillmentPM:
    order_id = Identifier()
    payment_id = Identifier()
    shipment_id = Identifier()
    status = String(default="new")

    # -----------------------------------------------------------
    # Step 1: Order placed -- start the process
    # -----------------------------------------------------------
    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_order_placed(self, event: OrderPlaced) -> None:
        if self.status != "new":
            return  # Idempotent: already started

        self.order_id = event.order_id
        self.status = "awaiting_inventory"
        current_domain.process(
            ReserveInventory(order_id=event.order_id)
        )

    # -----------------------------------------------------------
    # Step 2a: Inventory reserved -- request payment
    # -----------------------------------------------------------
    @handle(InventoryReserved, correlate="order_id")
    def on_inventory_reserved(self, event: InventoryReserved) -> None:
        if self.status != "awaiting_inventory":
            return  # Idempotent or out-of-order

        self.status = "awaiting_payment"
        current_domain.process(
            RequestPayment(
                order_id=self.order_id,
                amount=0.0,  # Amount resolved by Payment aggregate
            )
        )

    # -----------------------------------------------------------
    # Step 2b: Inventory reservation failed -- cancel order
    # -----------------------------------------------------------
    @handle(InventoryReservationFailed, correlate="order_id", end=True)
    def on_inventory_failed(self, event: InventoryReservationFailed) -> None:
        if self.status not in ("awaiting_inventory", "new"):
            return

        self.status = "cancelled"
        current_domain.process(
            CancelOrder(
                order_id=self.order_id,
                reason=f"Inventory unavailable: {event.reason}",
            )
        )

    # -----------------------------------------------------------
    # Step 3a: Payment confirmed -- create shipment
    # -----------------------------------------------------------
    @handle(PaymentConfirmed, correlate="order_id")
    def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
        if self.status != "awaiting_payment":
            return  # Idempotent: already past payment step

        self.payment_id = event.payment_id
        self.status = "awaiting_shipment"
        current_domain.process(
            CreateShipment(order_id=self.order_id)
        )

    # -----------------------------------------------------------
    # Step 3b: Payment failed -- release inventory, cancel order
    # -----------------------------------------------------------
    @handle(PaymentFailed, correlate="order_id", end=True)
    def on_payment_failed(self, event: PaymentFailed) -> None:
        if self.status != "awaiting_payment":
            return

        self.status = "cancelled"
        current_domain.process(
            ReleaseInventory(order_id=self.order_id)
        )
        current_domain.process(
            CancelOrder(
                order_id=self.order_id,
                reason=f"Payment failed: {event.reason}",
            )
        )

    # -----------------------------------------------------------
    # Step 4a: Shipment created -- record shipment ID
    # -----------------------------------------------------------
    @handle(ShipmentCreated, correlate="order_id")
    def on_shipment_created(self, event: ShipmentCreated) -> None:
        if self.status != "awaiting_shipment":
            return

        self.shipment_id = event.shipment_id
        self.status = "awaiting_delivery"

    # -----------------------------------------------------------
    # Step 4b: Shipment rejected -- refund payment, release
    #          inventory, cancel order
    # -----------------------------------------------------------
    @handle(ShipmentRejected, correlate="order_id", end=True)
    def on_shipment_rejected(self, event: ShipmentRejected) -> None:
        if self.status not in ("awaiting_shipment", "awaiting_delivery"):
            return

        self.status = "cancelled"

        # Compensate: refund the payment
        current_domain.process(
            RefundPayment(
                order_id=self.order_id,
                payment_id=self.payment_id,
            )
        )
        # Compensate: release inventory
        current_domain.process(
            ReleaseInventory(order_id=self.order_id)
        )
        # Compensate: cancel the order
        current_domain.process(
            CancelOrder(
                order_id=self.order_id,
                reason=f"Shipment rejected: {event.reason}",
            )
        )

    # -----------------------------------------------------------
    # Step 5: Shipment delivered -- process complete
    # -----------------------------------------------------------
    @handle(ShipmentDelivered, correlate="order_id")
    def on_shipment_delivered(self, event: ShipmentDelivered) -> None:
        if self.status != "awaiting_delivery":
            return

        self.status = "completed"
        self.mark_as_complete()

    # -----------------------------------------------------------
    # Timeout: external timer detected a stalled process
    # -----------------------------------------------------------
    @handle(OrderFulfillmentTimedOut, correlate="order_id")
    def on_timeout(self, event: OrderFulfillmentTimedOut) -> None:
        if self.status in ("completed", "cancelled"):
            return  # Already terminal

        # Compensate based on how far the process progressed
        if self.shipment_id:
            current_domain.process(
                CancelShipment(order_id=self.order_id, shipment_id=self.shipment_id)
            )
        if self.payment_id:
            current_domain.process(
                RefundPayment(order_id=self.order_id, payment_id=self.payment_id)
            )
        if self.status != "new":
            current_domain.process(ReleaseInventory(order_id=self.order_id))

        self.status = "cancelled"
        self.mark_as_complete()
        current_domain.process(
            CancelOrder(
                order_id=self.order_id,
                reason=f"Timed out in '{event.stalled_status}' status",
            )
        )
```

---

## What Happens at Runtime

### The happy path

The PM acts as a state machine that advances one step per event:

```
States:     new ──► awaiting_inventory ──► awaiting_payment ──► awaiting_shipment ──► awaiting_delivery ──► completed
                           │                      │                    │                    │
                           ▼                      ▼                    ▼                    ▼
                       cancelled              cancelled            cancelled            cancelled
```

1. `OrderPlaced` arrives → PM is created (`start=True`), status set to
   `awaiting_inventory`, `ReserveInventory` command issued.

2. `InventoryReserved` arrives → PM loaded via `order_id` correlation,
   status set to `awaiting_payment`, `RequestPayment` command issued.

3. `PaymentConfirmed` arrives → status set to `awaiting_shipment`,
   `CreateShipment` command issued.

4. `ShipmentCreated` arrives → `shipment_id` recorded, status set to
   `awaiting_delivery`.

5. `ShipmentDelivered` arrives → status set to `completed`,
   `mark_as_complete()` called. Future events for this `order_id` are skipped.

### A failure path

If `PaymentFailed` arrives instead of `PaymentConfirmed`:

1. The PM finds `status == "awaiting_payment"` — the guard passes.
2. The PM issues `ReleaseInventory` (compensating the earlier reservation)
   and `CancelOrder`.
3. `end=True` auto-completes the PM. The shipping step never happens.

### Why Each Design Principle Matters

**Idempotent handlers.** `PaymentConfirmed` is delivered twice. The first
delivery finds `status == "awaiting_payment"` and transitions to
`"awaiting_shipment"`. The second delivery finds `"awaiting_shipment"` and
returns immediately. No duplicate shipment.

**Compensation.** `ShipmentRejected` arrives after payment was confirmed
and inventory was reserved. The PM issues `RefundPayment`,
`ReleaseInventory`, and `CancelOrder` — unwinding every forward step.

**Out-of-order events.** `PaymentConfirmed` arrives before the PM exists.
Protean cannot load a PM instance for that `order_id` and skips the event.
When `OrderPlaced` creates the PM, the subscription redelivers
`PaymentConfirmed` and the PM processes it normally.

**Timeouts.** An external cron job publishes `OrderFulfillmentTimedOut`
for PMs stalled longer than a threshold. The timeout handler compensates
based on how far the process progressed.

**Terminal state protection.** Once `mark_as_complete()` is called,
Protean sets `_is_complete = True`. The framework checks this flag before
dispatching subsequent events — late events are silently skipped.

---

## Design Principles

### 1. Design as a state machine

Each handler checks the PM's current status before acting. This makes every
handler idempotent — processing the same event twice produces the same
result because the PM has already transitioned past the relevant state.

```
States:     new -> awaiting_payment -> awaiting_shipment -> completed
                        |                    |
                        v                    v
                    cancelled             cancelled
```

A handler for `PaymentConfirmed` only acts when status is
`awaiting_payment`. If the PM is already in `awaiting_shipment` (because
the event was delivered twice), the handler is a no-op.

### 2. Handle out-of-order events

Events from different aggregate streams have no guaranteed ordering.
`PaymentConfirmed` can arrive before `OrderPlaced`. Two strategies:

- **Ignore and rely on redelivery.** If the PM does not exist when
  `PaymentConfirmed` arrives (because `OrderPlaced` has not created it
  yet), the event is skipped. Protean's subscription will redeliver
  unacknowledged events. Design the PM so that when `OrderPlaced` finally
  creates the instance, subsequent events are reprocessed correctly.

- **Design correlation to make ordering irrelevant.** Structure each
  handler to set state based on what it knows, not on what it assumes
  happened before. If `PaymentConfirmed` arrives first, record the payment
  details. When `OrderPlaced` arrives, check whether payment is already
  recorded and skip the `RequestPayment` step.

### 3. Design compensation explicitly

For every "forward" step the PM orchestrates, document the compensating
action. When a step fails, the PM issues compensation commands to undo
previous steps.

| Forward step | Compensating action |
|---|---|
| `RequestPayment` | `RefundPayment` |
| `ReserveInventory` | `ReleaseInventory` |
| `CreateShipment` | `CancelShipment` |

Compensation is not automatic. Each failure event (`PaymentFailed`,
`ShipmentRejected`) must have an explicit handler that issues the
appropriate compensation commands and transitions the PM to a terminal
state.

### 4. Handle timeouts

A process manager has no internal clock. It reacts to events. If an
expected event never arrives, the PM waits forever.

The solution is an **external timer**: a scheduled job or a separate
aggregate that publishes timeout events. The PM subscribes to these timeout
events and handles them like any other event — checking state and issuing
compensation if the process has stalled.

### 5. Keep PM fields minimal

Store only the data the PM needs for routing and state decisions:

- The correlation identity (`order_id`)
- The current status
- References to sub-processes (`payment_id`, `shipment_id`)

Do not store the full order amount, customer address, item list, or other
business data. The PM is a coordinator, not a cache. When a command needs
business data, the receiving aggregate's command handler should load it from
its own repository.

---

## Anti-Patterns

### Non-idempotent handlers

```python
# Anti-pattern: no status check, command issued unconditionally
@handle(PaymentConfirmed, correlate="order_id")
def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
    self.status = "awaiting_shipment"
    current_domain.process(CreateShipment(order_id=self.order_id))
```

If delivered twice, `CreateShipment` is issued twice — a duplicate
shipment. **Fix:** guard every handler with a status check so the second
delivery is a no-op.

### Business logic in the process manager

```python
# Anti-pattern: PM validates payment amount
@handle(PaymentConfirmed, correlate="order_id")
def on_payment_confirmed(self, event: PaymentConfirmed) -> None:
    if event.amount < self.total * 0.95:
        current_domain.process(RejectPayment(...))
        return
    self.status = "awaiting_shipment"
```

Payment validation belongs in the `Payment` aggregate. The PM reacts to
outcomes (`PaymentConfirmed` or `PaymentFailed`), it does not judge
whether the payment was valid.

### Storing full business data

```python
# Anti-pattern: PM caches order details it never needs for routing
class OrderFulfillmentPM:
    order_id = Identifier()
    customer_email = String()       # Not used for state decisions
    shipping_address = String()     # Not used for state decisions
    items = List()                  # Not used for state decisions
    total = Float()                 # Not used for state decisions
    status = String(default="new")
```

**Fix:** Keep only `order_id`, `payment_id`, `shipment_id`, and `status`.
Commands carry enough context for the receiving aggregate to load business
data from its own repository.

### Ignoring terminal states

```python
# Anti-pattern: no end=True, no mark_as_complete()
@handle(ShipmentDelivered, correlate="order_id")
def on_shipment_delivered(self, event: ShipmentDelivered) -> None:
    self.status = "completed"
    # Forgot to signal completion to the framework
```

The PM is logically finished but Protean does not know that. Future events
for this `order_id` are still dispatched, potentially causing unexpected
behavior. **Fix:** always call `self.mark_as_complete()` or use `end=True`.

### Missing failure handlers

```python
# Anti-pattern: only happy path handled -- no handler for PaymentFailed
@handle(PaymentConfirmed, correlate="order_id")
def on_payment_confirmed(self, event): ...
```

When payment fails, the PM stays in `awaiting_payment` forever. Inventory
remains reserved. **Fix:** for every forward command, implement a handler
for its failure event that compensates and transitions to a terminal state.

---

## Summary

| Concern | Without PM | With PM |
|---------|-----------|---------|
| State tracking | None — reconstruct from logs | Built-in, event-sourced |
| Correlation | Manual, error-prone | Declarative `correlate` parameter |
| Lifecycle | No concept of "done" | `start`, `end`, `mark_as_complete()` |
| Compensation | Scattered across handlers | Centralized in PM handlers |
| Multi-stream | Multiple independent handlers | Single PM subscribes to all |

### Design checklist

| Principle | Question | What to check |
|---|---|---|
| State machine | Does every handler check `self.status` before acting? | Guard at top of each handler |
| Idempotency | Will processing the same event twice produce the same result? | Status guard prevents duplicate commands |
| Compensation | For every forward step, is there a failure handler? | Failure events mapped to compensating commands |
| Terminal states | Does every success/failure path call `mark_as_complete()` or use `end=True`? | `_is_complete` flag set on all exit paths |
| Out-of-order | What happens if events arrive in unexpected order? | PM skips events it cannot handle in current status |
| Timeouts | What happens if an expected event never arrives? | External timer publishes timeout event |
| Minimal fields | Does the PM store only routing and state data? | No business data cached in PM fields |
| No business logic | Does the PM coordinate or compute? | Validation and rules live in aggregates |

---

!!! tip "Related reading"
    **Concepts:**

    - [Process Managers](../concepts/building-blocks/process-managers.md) — Why process managers exist, when to use them vs. event handlers, and how the event chain works.

    **Guides:**

    - [Process Managers](../guides/consume-state/process-managers.md) — Defining and configuring PMs.
    - [Message Tracing](../guides/domain-behavior/message-tracing.md) — Correlation and causation IDs for end-to-end traceability, with programmatic causation chain traversal.

    **Related patterns:**

    - [Idempotent Event Handlers](idempotent-event-handlers.md) — Safe replay applies to PM handlers too.
    - [One Aggregate Per Transaction](one-aggregate-per-transaction.md) — PMs coordinate across aggregate boundaries.
