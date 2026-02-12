# Event Handlers

Event handlers react to [domain events](./events.md) by orchestrating side
effects — syncing state across [aggregates](./aggregates.md), sending
notifications, triggering downstream processes, or any other work that should
happen *after* a state change has occurred.

Event handlers follow a fire-and-forget pattern. They consume events
asynchronously, they do not return values, and the code that raised the
original event has no knowledge of which handlers will respond. This
decoupling is what makes event-driven architectures flexible and evolvable.

## Facts

### Event handlers are always associated with an aggregate. { data-toc-label="Linked to Aggregate" }

Every event handler declares the aggregate it belongs to. This association
determines the stream of events the handler subscribes to by default and
anchors the handler within a specific aggregate's boundary.

### Event handlers process events asynchronously. { data-toc-label="Asynchronous" }

Event handlers are designed for asynchronous processing. The aggregate that
raised the event does not wait for the handler to finish — it commits its own
transaction and moves on. The handler picks up the event later, typically
through the server engine's subscription mechanism.

### Event handlers do not return values. { data-toc-label="No Return Values" }

Because handlers run asynchronously and an event can have multiple handlers,
there is no caller waiting for a result. Handlers perform their work and
either succeed silently or raise errors for the infrastructure to manage.

### Each handler method processes one event type. { data-toc-label="Single Event Type" }

A handler class can contain multiple methods, but each method is bound to
exactly one event type through a decorator. This keeps each piece of reaction
logic focused and independently testable.

### Event handlers can listen across aggregate boundaries. { data-toc-label="Cross-Aggregate" }

While an event handler is associated with one aggregate, it can subscribe to
events from *other* aggregates by specifying a source stream or stream
category. This is the primary mechanism for eventual consistency — one
aggregate reacts to changes in another without direct coupling.

### Event handlers run within a Unit of Work. { data-toc-label="Transactions" }

Each handler method executes inside its own Unit of Work. If the handler
modifies an aggregate and persists it through a [repository](./repositories.md),
all changes are committed atomically. If an error occurs, the transaction
is rolled back.

### Event handlers enable eventual consistency. { data-toc-label="Eventual Consistency" }

When a business process spans multiple aggregates, event handlers are the
mechanism that propagates changes from one aggregate to another. Instead of
a single transaction that locks multiple aggregates, each aggregate commits
independently and event handlers bridge the gap asynchronously.

### Event handlers coordinate side effects. { data-toc-label="Side Effects" }

Beyond cross-aggregate state synchronization, event handlers are the right
place for any work that should happen in response to a domain event:
sending emails, updating caches, calling external APIs, writing audit logs,
or publishing messages to downstream systems.

## Best Practices

### Keep handlers idempotent. { data-toc-label="Idempotency" }

Events may be delivered more than once — during retries, resubscriptions, or
infrastructure recovery. A well-designed handler produces the same outcome
whether it processes an event once or multiple times.

### Handle errors gracefully. { data-toc-label="Error Handling" }

Event handlers can define error-handling logic for when processing fails.
Unhandled exceptions should not silently disappear; they should be logged,
retried, or routed to a dead-letter mechanism so operators can investigate.

### Avoid mixing aggregate responsibilities. { data-toc-label="Single Responsibility" }

A single handler method should concern itself with one aggregate's state. If
you find a handler method loading and modifying two different aggregates,
split the work into separate handlers or let the second aggregate react to
its own event.
