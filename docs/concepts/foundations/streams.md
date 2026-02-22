# Streams

Streams are the primary unit of organization in evented systems. A stream is an ordered, append-only sequence of events that represents the history of a single aggregate instance or a category of aggregates. Streams serve as both the storage mechanism and the message delivery channel in event-driven architectures. When aggregates are event-sourced, the stream *is* the aggregate's persistence -- there is no separate database row, only the sequence of events that produced the current state.

Understanding streams is essential for working with event sourcing and CQRS because they determine how events are stored, how aggregates are reconstituted, and how downstream consumers subscribe to changes.

## Streams Are Created When a Message Is Written

Streams are created implicitly by writing a message to them. Messages are appended to the end of the stream. If the stream does not exist when an event is appended, it is created and the event is written at position 0. If the stream already exists, the event is appended at the next position number. There is no explicit "create stream" operation -- streams come into existence through use.

## Entity Streams

An entity stream contains the events for a single aggregate instance. The stream name includes both the aggregate type and the instance's unique identity -- for example, `Order-abc123`. This stream holds every event that has ever been raised by that specific order: `OrderPlaced`, `ItemAdded`, `OrderShipped`, and so on.

To reconstitute an aggregate, the system reads the entity stream from the beginning and replays each event in order, rebuilding the aggregate's current state from its complete history. This is the fundamental mechanism of event sourcing.

## Category Streams

A category stream groups all entity streams of the same aggregate type. For example, the `Order` category stream contains events from every order in the system -- `Order-abc123`, `Order-def456`, and all others.

Category streams are the primary subscription mechanism. Subscribers and event handlers typically subscribe to a category rather than to individual entity streams. This allows a single subscriber to process events from all instances of an aggregate type -- for example, a projector that maintains an order summary table subscribes to the `Order` category and receives events from every order as they occur.

## Stream Names

Stream names follow a structured convention: the category name, a separator, and the entity identity. The category is typically the aggregate type name, and the identity is the aggregate's unique identifier. This naming structure makes it possible to derive an aggregate's stream name from its type and identity alone.

Stream names must be unique within a message store. There is no separate namespacing mechanism -- if the same stream name must be used for different purposes, those streams should either be stored in separate message store databases, or the names should include a distinguishing prefix or suffix.

## Event Streams Are Typically Safe

### Immutable, Append-Only Writes

Because all events are appended in chronological order and never updated in place, a valid history will normally remain intact over time. Each event is written with a version number (often called an "aggregate version"), so the event store can enforce optimistic concurrency and ensure no two updates conflict or overwrite each other.

### Validation at the Aggregate

Each aggregate enforces its own [invariants](./invariants.md) and rejects invalid changes before they can be turned into events. Consequently, only valid events are ever committed to the event store.

### Version Control and Concurrency Checks

When an event is appended, the system checks if the current version of the stream matches the version expected by the command (for example, "I expect the `Order-abc123` stream to be at version 3 before adding a new event"). If the versions do not match, the commit is rejected. This prevents partial or out-of-sequence writes and guarantees that the stream remains a consistent, ordered record of the aggregate's history.

## Further Reading

- [Event Sourcing](../architecture/event-sourcing.md) -- the architectural pattern that uses streams as the primary persistence mechanism
- [Stream Categories Guide](../async-processing/stream-categories.md) -- configuring and working with stream categories in Protean
- [Events](../building-blocks/events.md) -- the messages that streams contain
