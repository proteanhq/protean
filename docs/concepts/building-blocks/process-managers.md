# Process Managers

## The Problem They Solve

Event handlers react to domain events and execute side effects — updating
another aggregate, sending a notification, syncing a projection. Each handler
processes one event in isolation, with no memory of what happened before or
what should happen next.

This works for simple, one-step reactions. But many business processes are
multi-step workflows that span multiple aggregates:

- **Order fulfillment**: Accept order → reserve inventory → charge payment →
  create shipment → mark complete.
- **User onboarding**: Create account → verify email → provision resources →
  send welcome notification.
- **Payment reconciliation**: Receive payment → match to invoice → update
  ledger → notify customer.

These workflows share a common structure: each step produces an event, and
that event determines what the *next* step should be. If a step fails, earlier
steps may need to be reversed. The workflow needs to remember where it is.

Event handlers cannot do this. They are stateless — they don't know which step
they're on, what happened before, or what should happen next. You need
something that tracks the progress of the entire process, correlates events
from different aggregates to the same running instance, and decides what to do
next at each step. That is a process manager.

## When to Use a Process Manager vs. an Event Handler

| | Event Handler | Process Manager |
|---|---------------|----------------|
| **State** | Stateless — each event processed in isolation | Stateful — remembers what happened so far |
| **Steps** | Single reaction to one event | Multi-step workflow across many events |
| **Scope** | Reacts to events from one aggregate (`part_of`) | Reacts to events from multiple aggregates (`stream_categories`) |
| **Lifecycle** | No concept of "started" or "done" | Explicit lifecycle with `start`, `end`, `mark_as_complete()` |
| **Failure handling** | No built-in compensation | Coordinates compensating commands to undo earlier steps |
| **Correlation** | N/A — each event is independent | Routes events to the correct instance via correlation keys |

**Use an event handler** when a single event triggers a single reaction that
doesn't depend on past or future events. Examples: "When an order ships,
decrease inventory." "When a user registers, send a welcome email."

**Use a process manager** when you need to coordinate a sequence of steps
across multiple aggregates, track progress, and handle failures by unwinding
earlier steps. Examples: "When an order is placed, reserve inventory, then
charge payment, then create shipment — and if any step fails, undo the
previous ones."

## How the Event Chain Works

The core mechanism of a process manager is the **command-event loop**. The PM
doesn't call aggregate methods directly. Instead, it issues commands, and the
aggregates that process those commands raise events, which flow back to the PM
through its stream subscriptions.

Here is the complete round-trip for one step in an order fulfillment workflow:

```
                    ┌──────────────────────────────────────────────┐
                    │              Event Store                     │
                    │                                              │
                    │  ecommerce::order stream                     │
                    │    └─ OrderPlaced ──────────────────┐        │
                    │                                     │        │
                    │  ecommerce::payment stream          │        │
                    │    └─ PaymentConfirmed ─────────┐   │        │
                    │                                 │   │        │
                    │  ecommerce::shipping stream     │   │        │
                    │    └─ ShipmentDelivered ────┐   │   │        │
                    └────────────────────────────┼───┼───┼─────────┘
                                                 │   │   │
                              ┌──────────────────┘   │   │
                              │   ┌──────────────────┘   │
                              │   │   ┌──────────────────┘
                              ▼   ▼   ▼
                    ┌─────────────────────────────┐
                    │    OrderFulfillmentPM        │
                    │                             │
                    │  on_order_placed()           │──► RequestPayment command
                    │  on_payment_confirmed()      │──► CreateShipment command
                    │  on_shipment_delivered()      │──► mark_as_complete()
                    └─────────────────────────────┘
                              │           │
                              ▼           ▼
                    ┌─────────────┐ ┌─────────────┐
                    │   Payment   │ │  Shipping   │
                    │  aggregate  │ │  aggregate  │
                    │             │ │             │
                    │ Processes   │ │ Processes   │
                    │ command,    │ │ command,    │
                    │ raises      │ │ raises      │
                    │ event       │ │ event       │
                    └─────────────┘ └─────────────┘
```

Walking through the chain step by step:

1. **`OrderPlaced` event** is raised by the `Order` aggregate and written to
   the `ecommerce::order` stream.

2. The PM subscribes to `ecommerce::order`, so **the event is delivered to
   `on_order_placed()`**. The handler issues a `RequestPayment` command.

3. The `RequestPayment` command is processed by the `Payment` aggregate's
   command handler. The aggregate mutates and raises **`PaymentConfirmed`**,
   which is written to the `ecommerce::payment` stream.

4. The PM subscribes to `ecommerce::payment`, so **`PaymentConfirmed` is
   delivered to `on_payment_confirmed()`**. The handler issues a
   `CreateShipment` command.

5. The `CreateShipment` command is processed by the `Shipping` aggregate's
   command handler. The aggregate raises **`ShipmentDelivered`**, written to
   the `ecommerce::shipping` stream.

6. The PM subscribes to `ecommerce::shipping`, so **`ShipmentDelivered` is
   delivered to `on_shipment_delivered()`**. The handler calls
   `mark_as_complete()`. The workflow is done.

**This is why the PM subscribes to multiple stream categories.** Each command
the PM issues targets a different aggregate. That aggregate's response (an
event) appears on its own stream. The PM must subscribe to all those streams
to see the results of the commands it issued.

## Facts

### Process managers are stateful coordinators. { data-toc-label="Stateful" }

Each process manager instance has its own fields and persisted state. When
an event arrives, the framework loads the correct instance, runs the handler,
and saves the updated state. This lets the process manager remember what has
happened so far and decide what to do next.

### Process managers correlate events to instances. { data-toc-label="Correlation" }

Every handler declares a `correlate` parameter that extracts an identity
value from the incoming event (e.g., `correlate="order_id"`). This value is
used to find the correct process manager instance — or to create one when
a start event arrives.

### Process managers listen to multiple streams. { data-toc-label="Multi-Stream" }

A single process manager subscribes to events from several aggregate
streams because the commands it issues cause events on *those other
aggregates' streams*. The PM needs to see those response events to know when
to proceed to the next step.

### Process managers are event-sourced. { data-toc-label="Event-Sourced" }

State is persisted as a sequence of auto-generated transition events in the
event store. After each handler runs, the framework captures a snapshot of
the process manager's fields and appends it to the PM's own stream. Loading
an instance replays these transitions to rebuild state.

### Process managers have a lifecycle. { data-toc-label="Lifecycle" }

Every process manager begins with a **start** event — the handler marked
with `start=True`. It runs through intermediate states as subsequent events
arrive, and ends when either `mark_as_complete()` is called in a handler or
a handler is marked with `end=True`. Once complete, subsequent events for
that instance are skipped.

### Process managers issue commands, not mutations. { data-toc-label="Issue Commands" }

Handlers in a process manager issue commands via
`current_domain.process()` to trigger actions in other aggregates. This
keeps the PM as a pure coordinator — it decides *what* should happen next,
and the target aggregate's command handler decides *how*.

### Each handler processes one event type. { data-toc-label="Single Event Type" }

Like event handlers, each method in a process manager is bound to exactly
one event type through the `@handle` decorator. The decorator also carries
the `start`, `correlate`, and `end` parameters that govern lifecycle and
routing.

### Process managers run within a Unit of Work. { data-toc-label="Transactions" }

Each handler executes inside its own Unit of Work. The transition event and
any commands issued by the handler are committed atomically. If an error
occurs, the entire operation is rolled back.

## Best Practices

### Keep process managers focused on coordination. { data-toc-label="Coordination Only" }

A process manager should orchestrate — not contain — business logic. The
domain logic belongs in the aggregates and domain services. The process
manager's job is to decide which commands to issue and when, based on the
events it has seen.

### Always define a terminal state. { data-toc-label="Terminal State" }

Every process manager should have at least one path to completion, either
through `mark_as_complete()` or `end=True`. Without a terminal state, the
process manager will accept events indefinitely, which usually indicates a
design gap.

### Use meaningful correlation keys. { data-toc-label="Meaningful Keys" }

The correlation field should represent the natural identity of the business
process — typically the ID of the aggregate that initiated it. All events
participating in the process must carry this field so they can be routed to
the correct instance.

### Design for idempotency. { data-toc-label="Idempotency" }

Events may be delivered more than once. A well-designed process manager
handler should produce the same outcome whether it processes an event once
or multiple times, just like any other event handler.

### Handle compensation explicitly. { data-toc-label="Compensation" }

When a step fails (e.g., payment declined), the process manager should issue
compensating commands to undo earlier steps rather than leaving the process
in an inconsistent intermediate state. Use `end=True` or
`mark_as_complete()` to close out failed processes cleanly.

---

## Next steps

For practical details on defining and using process managers in Protean, see the guide:

- [Process Managers](../../guides/consume-state/process-managers.md) — Defining process managers, correlation, lifecycle management, and configuration.

For design guidance:

- [Coordinating Long-Running Processes](../../patterns/coordinating-long-running-processes.md) — Patterns for resilient multi-step workflows with idempotency, compensation, and timeout handling.
