# Process Managers

Process managers coordinate multi-step business processes that span multiple
[aggregates](./aggregates.md). They react to [domain events](./events.md),
track the progress of a running process, and issue
[commands](./commands.md) to drive other aggregates forward — all while
maintaining their own persisted state.

Unlike [event handlers](./event-handlers.md), which are stateless and handle
each event in isolation, process managers correlate related events to the
same running instance, making them the right tool for workflows like order
fulfillment, payment reconciliation, or onboarding sequences.

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

A single process manager can subscribe to events from several aggregate
streams. An order fulfillment process manager, for example, might listen to
order, payment, and shipping streams, reacting to events from each to drive
the process forward.

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

### Process managers issue commands. { data-toc-label="Issue Commands" }

Handlers in a process manager can issue commands via
`current_domain.process()` to trigger actions in other aggregates. This is
the primary mechanism for driving the business process forward — the process
manager decides *what* should happen next, and the target aggregate's command
handler decides *how*.

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

- [Coordinating Long-Running Processes](../../patterns/coordinating-long-running-processes.md) — Patterns for orchestrating multi-step workflows across aggregates.
