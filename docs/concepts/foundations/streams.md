# What is a stream?

Streams are the primary unit of organization in evented systems. A stream is an
ordered, append-only sequence of events that represents the history of a single
aggregate instance or a category of aggregates. Streams serve as both the
storage mechanism and the message delivery channel in event-driven
architectures. When aggregates are event-sourced, the stream *is* the
aggregate's persistence. There is no separate database row, only the sequence
of events that produced the current state.

You need to understand streams to work with event sourcing and CQRS. Streams
determine how events are stored, how aggregates are reconstituted, and how
downstream consumers subscribe to changes.

## Streams Are Created When a Message Is Written

Streams are created implicitly by writing a message to them. Messages are
appended to the end of the stream. If the stream does not exist yet, the first
append creates it. That first event is written at position 0. If the stream
already exists, the event is appended at the next position number. There is no
explicit "create stream" operation, streams come into existence through use.

## An entity stream holds one aggregate's events

An entity stream contains the events for a single aggregate instance. The
stream name includes both the aggregate type and the instance's unique
identity, for example, `Order-abc123`. This stream holds every event that has ever been
raised by that specific order: `OrderPlaced`, `ItemAdded`, `OrderShipped`, and so on.

To reconstitute an aggregate, the system reads the entity stream from the beginning and replays each event in order, rebuilding the aggregate's current state from its complete history. This is the fundamental mechanism of event sourcing.

## A category stream groups all streams of one aggregate type

A category stream groups all entity streams of the same aggregate type. For
example, the `Order` category stream contains events from every order in the
system, `Order-abc123`, `Order-def456`, and all others.

Category streams are the primary subscription mechanism. Subscribers and event
handlers typically subscribe to a category rather than to individual entity
streams. By subscribing to a category, a single subscriber processes events
from all instances of an aggregate type. For example, a projector that
maintains an order summary table subscribes to the `Order` category and
receives events from every order as they occur.

## How stream names are built

Stream names follow a structured convention: the category name, a separator,
and the entity identity. The category is typically the aggregate type name. The
identity is the aggregate's unique identifier. With this naming structure, you
can derive an aggregate's stream name from its type and identity alone.

Stream names must be unique within a message store. The message store has no
separate namespacing mechanism. If you need the same stream name for different
purposes, store those streams in separate message store databases, or add a
distinguishing prefix or suffix to the names.

## Event Streams Are Typically Safe

### Writes are immutable and append-only

Because all events are appended in chronological order and never updated in
place, a valid history will normally remain intact over time. The event store
writes each event with a version number (often called an "aggregate version").
With that number, the event store enforces optimistic concurrency and stops two
updates from conflicting with or overwriting each other.

### The aggregate validates changes before they become events

Each aggregate enforces its own [invariants](./invariants.md) and rejects invalid changes before they can be turned into events. Consequently, only valid events are ever committed to the event store.

### The event store checks the stream version on every append

On each append, the system compares the current version of the stream with the
version expected by the command. For example, the command says "I expect the
`Order-abc123` stream to be at version 3 before adding a new event". If the
versions do not match, the commit is rejected. With this version check, the
system prevents partial or out-of-sequence writes. The stream stays a
consistent, ordered record of the aggregate's history.

## See also

- [Event Sourcing](../architecture/event-sourcing.md): The architectural pattern that uses streams as the primary persistence mechanism
- [Stream Categories Guide](../async-processing/stream-categories.md): Defining
  stream categories in Protean and using them in handlers and subscriptions
- [Events](../building-blocks/events.md): The messages that streams contain
