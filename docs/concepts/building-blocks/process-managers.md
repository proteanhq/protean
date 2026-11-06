# Process Managers

## What problem do process managers solve?

Event handlers react to domain events and execute side effects, updating
another aggregate, sending a notification, syncing a projection. Each handler
processes one event in isolation. The handler keeps no memory of earlier steps
or of the next step.

This works for simple, one-step reactions. But many business processes are
multi-step workflows that span multiple aggregates:

- **Order fulfillment**: Accept order → reserve inventory → charge payment →
  create shipment → mark complete.
- **User onboarding**: Create account → verify email → provision resources →
  send welcome notification.
- **Payment reconciliation**: Receive payment → match to invoice → update
  ledger → notify customer.

These workflows share a common structure: each step produces an event, and that
event determines what the *next* step should be. If a step fails, the workflow
may need to reverse earlier steps. The workflow needs to record which step it
has reached.

Event handlers cannot do this. They are stateless. They don't know which step
they're on, what happened before, or what should happen next. You need a
component that tracks the progress of the entire process. The component also
correlates events from different aggregates to the same running instance, and
picks the next action at each step. That is a process manager.

## When to Use a Process Manager vs. an Event Handler

| | Event Handler | Process Manager |
|---|---------------|----------------|
| **State** | Stateless, each event processed in isolation | Stateful, remembers what happened so far |
| **Steps** | Single reaction to one event | Multi-step workflow across many events |
| **Scope** | Reacts to events from one aggregate (`part_of`) | Reacts to events from multiple aggregates (`stream_categories`) |
| **Lifecycle** | No concept of "started" or "done" | Explicit lifecycle with `start`, `end`, `mark_as_complete()` |
| **Failure handling** | No built-in compensation | Coordinates compensating commands to undo earlier steps |
| **Correlation** | N/A; each event is independent | Routes events to the correct instance via correlation keys |

When a single event triggers a single reaction, and the reaction does not
depend on past or future events, **use an event handler**. Examples: "When an
order ships, decrease inventory." "When a user registers, send a welcome
email."

When you need to coordinate a sequence of steps across multiple aggregates,
track progress, and undo earlier steps after a failure, **use a process
manager**. Examples: "When an order is placed, reserve inventory, then charge
payment, then create shipment, and if any step fails, undo the previous ones."

## How the Event Chain Works

The core mechanism of a process manager is the **command-event loop**. The PM
doesn't call aggregate methods directly. Instead, the PM issues commands. The
aggregates process those commands and raise events. The PM receives those
events through its stream subscriptions.

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
                    │  on_shipment_delivered()      │──► end=True: complete
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

The chain runs in six steps:

1. **`OrderPlaced` event** is raised by the `Order` aggregate and written to
   the `ecommerce::order` stream.

2. The PM subscribes to `ecommerce::order`, so **the framework delivers the
   event to `on_order_placed()`**. The handler issues a `RequestPayment`
   command.

3. The `RequestPayment` command is processed by the `Payment` aggregate's
   command handler. The aggregate mutates and raises **`PaymentConfirmed`**,
   which is written to the `ecommerce::payment` stream.

4. The PM subscribes to `ecommerce::payment`, so **the framework delivers
   `PaymentConfirmed` to `on_payment_confirmed()`**. The handler issues a
   `CreateShipment` command.

5. The `CreateShipment` command is processed by the `Shipping` aggregate's
   command handler. The aggregate raises **`ShipmentDelivered`**, written to
   the `ecommerce::shipping` stream.

6. The PM subscribes to `ecommerce::shipping`, so **the framework delivers
   `ShipmentDelivered` to `on_shipment_delivered()`**. That handler is marked
   `end=True`, so the PM is complete once it returns. The workflow is done.

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

Every handler declares a `correlate` parameter that extracts an identity value
from the incoming event (e.g., `correlate="order_id"`). The framework uses this
value to find the correct process manager instance, or to create one when a
start event arrives.

### Process managers listen to multiple streams. { data-toc-label="Multi-Stream" }

A single process manager subscribes to events from several aggregate streams.
It does this because its commands cause events on *those other aggregates'
streams*. The PM needs to see those response events to know when to proceed to
the next step.

### Process managers can span bounded contexts. { data-toc-label="Cross-Domain" }

When multiple domains are co-located in the same repository and share the same
event store, a process manager can handle events from other bounded contexts
using `register_external_event()`. This gives the PM typed access to external
events without importing from the other domain's package. When domains are
distributed as independent services, use subscribers to translate external
messages into internal commands or events. The PM then reacts to those commands
or events. See [Multi-Domain
Applications](../../guides/multi-domain-applications.md#communicate-across-domains)
for guidance on choosing between the two approaches.

### Process managers are event-sourced. { data-toc-label="Event-Sourced" }

State is persisted as a sequence of auto-generated transition events in the
event store. After each handler runs, the framework captures a snapshot of the
process manager's fields and appends it to the PM's own stream. When the
framework loads an instance, it replays the transition events to rebuild state.

### Process managers have a lifecycle. { data-toc-label="Lifecycle" }

Every process manager begins with a **start** event, handled by a handler
marked with `start=True`. A process manager can have more than one start
handler. The process manager runs through intermediate states as subsequent
events arrive. It ends when a handler marked with `end=True` returns or a
handler calls `mark_as_complete()`. Once complete, subsequent events for that
instance are skipped. Mark at least one terminating handler `end=True`:
`protean check` reports a process manager without one as
`PROCESS_MANAGER_UNCLOSED`.

### Process managers issue commands, not mutations. { data-toc-label="Issue Commands" }

Handlers in a process manager issue commands via `current_domain.process()` to
trigger actions in other aggregates. This keeps the PM as a pure coordinator.
It decides *what* should happen next, and the target aggregate's command
handler decides *how*.

### Each handler processes one event type. { data-toc-label="Single Event Type" }

Like event handlers, each method in a process manager is bound to exactly
one event type through the `@handle` decorator. The decorator also carries
the `start`, `correlate`, and `end` parameters that govern lifecycle and
routing.

### Process managers run within a Unit of Work. { data-toc-label="Transactions" }

Each handler executes inside its own Unit of Work. If the handler fails, the
PM's transition is rolled back. On the memory event store, the rollback also
discards any command the handler issued before the failure. Message-DB writes
such a command on its own connection, so the command survives the rollback.
Keep issued commands idempotent so re-issuing one is safe.

## Follow these practices when you design a process manager

### Keep process managers focused on coordination. { data-toc-label="Coordination Only" }

A process manager should orchestrate (not contain) business logic. The domain
logic belongs in the aggregates and domain services. The process manager
decides which commands to issue, and when to issue them, from the events it has
seen.

### Always define a terminal state. { data-toc-label="Terminal State" }

Every process manager should have at least one path to completion, either
through `mark_as_complete()` or `end=True`. Without a terminal state, the
process manager will accept events indefinitely, which usually indicates a
design gap.

### Use meaningful correlation keys. { data-toc-label="Meaningful Keys" }

The correlation field should represent the natural identity of the business
process, typically the ID of the aggregate that initiated it. All events
participating in the process must carry this field so they can be routed to the
correct instance.

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

## Read more about process managers

For practical details on defining and using process managers in Protean, see the guide:

- [Process Managers](../../guides/consume-state/process-managers.md): Defining process managers, correlation, lifecycle management, and configuration.

For design guidance:

- [Coordinating Long-Running Processes](../../patterns/coordinating-long-running-processes.md): Patterns for resilient multi-step workflows with idempotency, compensation, and timeout handling.
