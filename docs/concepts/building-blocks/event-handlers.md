# Event Handlers

Event handlers react to [domain events](./events.md) with work that runs
*after* a state change. That work includes orchestrating side effects, syncing
state across [aggregates](./aggregates.md), sending notifications, and
triggering downstream processes.

Event handlers follow a fire-and-forget pattern. They consume events
asynchronously and do not return values. The code that raised the original
event does not know which handlers will respond. This decoupling is what makes
event-driven architectures flexible and evolvable.

## Facts

### Event handlers are always associated with an aggregate. { data-toc-label="Linked to Aggregate" }

Every event handler declares the aggregate it belongs to. Protean uses this
aggregate to pick the stream of events the handler subscribes to by default.
The handler is also part of that aggregate's boundary.

### Event handlers process events asynchronously. { data-toc-label="Asynchronous" }

Event handlers are designed for asynchronous processing. The aggregate that
raised the event does not wait for the handler to finish. It commits its own
transaction, and the code that raised the event continues. The handler receives
the event later, usually through the server engine's subscription mechanism.

### Event handlers do not return values. { data-toc-label="No Return Values" }

Because handlers run asynchronously and an event can have multiple handlers,
there is no caller waiting for a result. Handlers perform their work and
either succeed silently or raise errors for the infrastructure to manage.

### Each handler method processes one event type. { data-toc-label="Single Event Type" }

A handler class can contain multiple methods. A decorator binds each method to
exactly one event type. This keeps each piece of reaction logic focused and
independently testable.

### Event handlers can listen across aggregate boundaries. { data-toc-label="Cross-Aggregate" }

While an event handler is associated with one aggregate, it can subscribe to
events from *other* aggregates by specifying a source stream or stream
category. This is the primary mechanism for eventual consistency. One aggregate
reacts to changes in another without direct coupling.

### Event handlers run within a Unit of Work. { data-toc-label="Transactions" }

Each handler method executes inside its own Unit of Work. If the handler
modifies an aggregate and persists it through a [repository](./repositories.md),
all changes are committed atomically. If an error occurs, the transaction
is rolled back.

### Event handlers enable eventual consistency. { data-toc-label="Eventual Consistency" }

When a business process spans multiple aggregates, event handlers propagate
changes from one aggregate to another. No single transaction locks multiple
aggregates. Each aggregate commits independently, and event handlers apply the
changes to the other aggregates asynchronously.

### Event handlers coordinate side effects. { data-toc-label="Side Effects" }

Beyond cross-aggregate state synchronization, event handlers run the work that
follows a domain event. That work includes sending emails, updating caches,
calling external APIs, writing audit logs, and publishing messages to
downstream systems.

A single handler method either persists or talks to an external system, never
both. The method runs inside a Unit of Work, so an external call after a
repository access holds the transaction open for the length of that call. Split
the two: a persisting method raises an event, and a calling method handles it.
See [Calling External Systems from
Handlers](../../patterns/calling-external-systems-from-handlers.md).

## How do event handlers differ from related elements?

| Aspect | Event Handler | Projector | Subscriber | Query Handler |
|--------|--------------|-----------|------------|---------------|
| **Purpose** | Side effects, cross-aggregate sync | Maintain read models | Anti-corruption layer for external messages | Structured read access |
| **Consumes** | Domain events | Domain events | Raw `dict` payloads | Queries (synchronous) |
| **Source** | Internal event store | Internal event store | External message broker | `domain.dispatch()` |
| **Association** | `part_of` (aggregate) | `projector_for` (projection) | `stream` (broker stream) | `part_of` (projection) |
| **Returns** | Nothing | Nothing | Nothing | Always returns data |
| **UoW** | Yes (per handler method) | Yes (per handler method) | No | No |

## How should you design event handlers?

### Keep handlers idempotent. { data-toc-label="Idempotency" }

Events may be delivered more than once, during retries, resubscriptions, or
infrastructure recovery. A well-designed handler produces the same outcome
whether it processes an event once or multiple times.

### Define what happens when a handler fails. { data-toc-label="Error Handling" }

Event handlers can define error-handling logic for when processing fails.
Unhandled exceptions should not silently disappear; they should be logged,
retried, or routed to a dead-letter mechanism so operators can investigate.

### Avoid mixing aggregate responsibilities. { data-toc-label="Single Responsibility" }

A single handler method should change only one aggregate's state. If you find a
handler method loading and modifying two different aggregates, split the work
into separate handlers or let the second aggregate react to its own event.

---

## Learn more about event handlers

For practical details on defining and using event handlers in Protean, see the guide:

- [Event Handlers](../../guides/consume-state/event-handlers.md): Defining handlers, configuration options, error handling, and subscription setup.

For design guidance:

- [Idempotent Event Handlers](../../patterns/idempotent-event-handlers.md): Ensuring handlers produce correct results even when events are delivered more than once.
- [Thin Handlers, Rich Domain](../../patterns/thin-handlers-rich-domain.md): Keeping handlers thin by delegating to domain logic.
