# Events

Domain events are immutable facts that indicate a state change in the
business domain. They capture meaningful changes and convey the state
transitions of aggregates, ensuring that all parts of the system remain
consistent and informed.

## Facts

### Events are always associated with aggregates. { data-toc-label="Linked to Aggregates" }
An event is always associated to the aggregate that emits it. Events of an
event type are emitted to the aggregate stream that the event type is
associated with.

### Events are essentially Data Transfer Objects (DTO). { data-toc-label="Data Transfer Objects" }
They can only hold simple fields and Value Objects.

### Events are named using past-tense verbs. { data-toc-label="Named in Past-Tense" }
Events should be named in past tense, because we observe domain events _after
the fact_. `StockDepleted` is a better choice than the imperative
`DepleteStock` as an event name.

### Events contain only necessary information. { data-toc-label="Minimal" }
Events should only include the data necessary to describe the change that
occurred. This keeps them lightweight and focused.

### Events are immutable. { data-toc-label="Immutable" }
Once created, events cannot be changed. They are a factual record of something
that has occurred in the past within the domain.

### Events communicate state changes. { data-toc-label="Propagate State Change" }
Events inform other parts of the system about significant state changes in
aggregates, ensuring all interested components can respond appropriately.

### Events act as API contracts. { data-toc-label="Act as API Contracts" }

Events define a clear and consistent structure for data that is shared
between different components of the system. This promotes system-wide
interoperability and integration between components.

### Events help preserve context boundaries. { data-toc-label="Sync across Boundaries" }

Events propagate information across bounded contexts, thus helping to
sync changes throughout the application domain. This allows each domain
to be modeled in the architecture pattern that is most appropriate for its
use case.

### Events enable decoupled communication. { data-toc-label="Decouple services" }
Systems and components communicate through events, reducing direct dependencies
and fostering a more modular architecture.

Events, thus, can be used as a mechanism to implement eventual consistency,
within and across bounded contexts. This promotes loose coupling by decoupling
the producer (e.g., an aggregate that raises an event) from the consumers
(e.g., various components that handle the event).

Such a design eliminates the need for two-phase commits (global
transactions) across bounded contexts, optimizing performance at the level
of each transaction.

## Structure

### Events have **metadata**. { data-toc-label="Metadata" }
Metadata such as timestamps, unique event identifiers, and version numbers are
included to ensure precise tracking and processing.

### Events are **versioned**. { data-toc-label="Versioning" }
Each event is assigned a version number, ensuring that consumers can handle
them in the correct order and manage compatibility between event producers and
consumers.

### Events are **timestamped**. { data-toc-label="Timestamp" }
Each event carries a timestamp indicating when the event occurred, which is
crucial for tracking and ordering events chronologically.

### Events are identifiable uniquely.  { data-toc-label="Identifiers" }
Each event carries a structured unique identifier that indicates the origin of
the event and the unique identity of the aggregate that generated the event.

### Events are written into streams.  { data-toc-label="Event Streams" }
Events are written to and read from streams. Review the section on
[Streams](../foundations/streams.md) for a deep-dive.

## Event Types

Events are categorized into two different types based on their purpose and the
kind of information they carry.

### Delta Events

Delta events capture incremental changes that have occurred in the state of
an aggregate. They provide detailed information about the specific
modifications made, allowing systems to apply only the necessary updates.

Delta type events record precise changes, such as  attribute updates or
modifications to collections within an aggregate. By focusing on incremental
changes, Delta Events enable efficient updates and reduce the overhead
associated with processing entire aggregates.

Delta events are a good choice when composing internal state via Event Sourcing
or notifying external consumers for choice events, like `LowInventoryAlert`.
They are also appropriate for composing a custom projection of the state based on
events (for example in Command Query Resource Separation).

#### Multiple Event Types

Aggregates usually emit events of multiple delta event types. Each event
is individually associated with the aggregate.

### Fact Events

A fact event encloses the entire state of the aggregate at that specific point
in time. It contains all of the attributes and values necessary to completely
describe the fact in the context of your business.

A fact event is similar to a row in a database: a complete set of data
pertaining to the row at that point in time.

Fact events enable a pattern known as **Event-carried State Transfer**. With
these events, consumers do not have to build up the state themselves from
multiple delta event types, which can be risky and error-prone, especially as
data schemas evolve and change over time. Instead, they rely on the owning
service to compute and produce a fully detailed fact event.


## Persistence

### Events are stored in an Event Store. { data-toc-label="Event Store" }
Events are often persisted in an Event Store, which acts as an append-only
log of all events, ensuring a reliable history of changes.

### Events support Event Sourcing. { data-toc-label="Event Sourcing" }
In Event Sourcing, the state of a domain entity is reconstructed by replaying
the sequence of events from the Event Store, ensuring a complete and accurate
history.

### Events are part of the transaction boundary. { data-toc-label="Transactions" }
Events are typically included in the transaction boundary, ensuring that they
are only published if the transaction is successful.

### Events trigger side effects. { data-toc-label="Side Effects" }
Events often lead to side effects, such as updating read models, triggering
workflows, or invoking external systems. These side effects are managed by
[event handlers](./event-handlers.md) and [projectors](./projectors.md).

### Events can be used to build local state in a different bounded context. { data-toc-label="Read-only Models" }
Other bounded contexts should be listen to interested events and construct
read-only structures within themselves to take decisions later. A receiver
should not query the current state from the sender because the sender's state
could have already mutated.

---

## Next steps

For practical details on defining and working with events in Protean, see the guides:

- [Events](../../guides/domain-definition/events.md) — Defining events, event structure, metadata, versioning, and fact events.
- [Raising Events](../../guides/domain-behavior/raising-events.md) — Raising events from aggregates and entities, dispatching, and event sourcing patterns.

For design guidance:

- [Design Events for Consumers](../../patterns/design-events-for-consumers.md) — Structuring events so consumers can process them reliably.
- [Event Versioning and Evolution](../../patterns/event-versioning-and-evolution.md) — Managing event schema changes over time.
