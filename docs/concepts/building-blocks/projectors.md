# Projectors

A projector is a specialized [event handler](./event-handlers.md) whose sole
job is to maintain a [projection](./projections.md). It listens to
[domain events](./events.md) from one or more [aggregates](./aggregates.md)
and translates each event into the appropriate create, update, or delete
operation on a projection record.

Projectors update the read side of a CQRS architecture from the events the
write side raises. Each projector updates its projection on every event it
receives. The projection then stays consistent with the domain state.

## Facts

### Projectors are always associated with a projection. { data-toc-label="Linked to Projection" }

Every projector declares the projection it maintains. With this explicit
declaration, you can trace each projection back to the projector that produces
it.

### Projectors listen to events from one or more aggregates. { data-toc-label="Multiple Aggregates" }

A projector can subscribe to event streams from multiple aggregates. A single
projection can then incorporate data from across the domain. For example, a
dashboard view can combine order, customer, and product data.

### Projectors use a handler decorator to process events. { data-toc-label="Handler Decorator" }

Each method in a projector is bound to a specific event type through a
decorator. When the projector receives an event of that type, Protean calls the
corresponding method to update the projection.

### Projectors can subscribe to multiple stream categories. { data-toc-label="Stream Categories" }

Beyond subscribing to individual aggregate streams, a projector can listen
to entire stream categories. This is useful when a projection needs to track
a broad set of events across many instances of an aggregate type.

### Projectors keep projections consistent with domain state. { data-toc-label="Consistency" }

Aggregates emit domain events, and the event store persists them. Projectors
consume those events (typically asynchronously) and apply the corresponding
changes to their projection. The projection is eventually consistent with the
write-side state.

### Projectors are similar to event handlers but target projections. { data-toc-label="vs. Event Handlers" }

Both projectors and event handlers consume domain events. The difference is
intent: event handlers orchestrate side effects and cross-aggregate
coordination, while projectors exist solely to build and maintain read models.
With projectors as a separate element, you keep the read-side logic apart from
the reactive domain logic.

## Best Practices

### Keep projection logic idempotent. { data-toc-label="Idempotency" }

Events may be replayed during recovery, resubscription, or catch-up
processing. A projector should produce the same projection state whether it
processes an event once or multiple times.

### Handle event ordering carefully. { data-toc-label="Ordering" }

Projections often depend on events arriving in the correct order. An
"OrderShipped" event makes no sense without the preceding "OrderPlaced." Design
projectors to handle ordering constraints, and be aware that cross-aggregate
events may not have a guaranteed global order.

### Design projections for specific query needs. { data-toc-label="Purpose-built" }

Do not build a general-purpose projection that serves every possible query.
Each projection should be tailored to a specific read use-case. Multiple small,
focused projections are easier to maintain and perform better than a single
monolithic one.

---

## Next steps

For practical details on defining and using projectors in Protean, see the guide:

- [Projectors](../../guides/consume-state/projectors.md): Projector definition, the @on decorator, error handling, multi-aggregate projectors, and testing.

For design guidance:

- [Idempotent Event Handlers](../../patterns/idempotent-event-handlers.md): Ensuring projectors produce correct results even when events are replayed.
