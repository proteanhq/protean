# Projectors

A projector is a specialized [event handler](./event-handlers.md) whose sole
job is to maintain a [projection](./projections.md). It listens to
[domain events](./events.md) from one or more [aggregates](./aggregates.md)
and translates each event into the appropriate create, update, or delete
operation on a projection record.

Projectors are the bridge between the write side and the read side of a CQRS
architecture. They ensure that projections stay consistent with the domain
state as events flow through the system.

## Facts

### Projectors are always associated with a projection. { data-toc-label="Linked to Projection" }

Every projector declares the projection it maintains. This explicit
association makes the relationship between the event consumer and the read
model it produces clear and traceable.

### Projectors listen to events from one or more aggregates. { data-toc-label="Multiple Aggregates" }

A projector can subscribe to event streams from multiple aggregates. This is
what allows a single projection to incorporate data from across the domain —
for example, a dashboard view that combines order, customer, and product data.

### Projectors use a handler decorator to process events. { data-toc-label="Handler Decorator" }

Each method in a projector is bound to a specific event type through a
decorator. When an event of that type is received, the corresponding method
is invoked to update the projection.

### Projectors can subscribe to multiple stream categories. { data-toc-label="Stream Categories" }

Beyond subscribing to individual aggregate streams, a projector can listen
to entire stream categories. This is useful when a projection needs to track
a broad set of events across many instances of an aggregate type.

### Projectors keep projections consistent with domain state. { data-toc-label="Consistency" }

As domain events are emitted by aggregates and persisted to the event store,
projectors consume those events — typically asynchronously — and apply the
corresponding changes to their projection. The projection is eventually
consistent with the write-side state.

### Projectors are similar to event handlers but target projections. { data-toc-label="vs. Event Handlers" }

Both projectors and event handlers consume domain events. The difference is
intent: event handlers orchestrate side effects and cross-aggregate
coordination, while projectors exist solely to build and maintain read models.
This distinction keeps the read-side logic separate from the reactive
domain logic.

## Best Practices

### Keep projection logic idempotent. { data-toc-label="Idempotency" }

Events may be replayed during recovery, resubscription, or catch-up
processing. A projector should produce the same projection state whether it
processes an event once or multiple times.

### Handle event ordering carefully. { data-toc-label="Ordering" }

Projections often depend on events arriving in the correct order — an
"OrderShipped" event makes no sense without the preceding "OrderPlaced." Design
projectors to handle ordering constraints, and be aware that cross-aggregate
events may not have a guaranteed global order.

### Design projections for specific query needs. { data-toc-label="Purpose-built" }

Resist the temptation to build a general-purpose projection that serves every
possible query. Each projection should be tailored to a specific read
use-case. Multiple small, focused projections are easier to maintain and
perform better than a single monolithic one.
