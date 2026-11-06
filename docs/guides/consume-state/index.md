# React to Changes

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

The reactive layer responds to state changes that have already happened. The
reactive layer carries changes across aggregates, updates read-optimized views,
coordinates multi-step processes, and connects to external systems. None of
this work couples back to the code that produced the original change.

## What can react to a change?

### Event Handlers

Event handlers consume domain events and orchestrate side effects, syncing
state across aggregates, sending notifications, or triggering downstream
processes. Event handlers follow a fire-and-forget pattern. Each event handler
runs within its own transaction boundary.

[Learn more about event handlers →](./event-handlers.md)

### Process Managers

Process managers coordinate multi-step business processes that span multiple
aggregates. Process managers react to events and keep their own state. They
issue commands that move other aggregates to the next step of the process.

[Learn more about process managers →](./process-managers.md)

### Projections <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Projections are read-optimized, denormalized views built from domain events. They provide fast query access without loading full aggregate graphs, forming the read side of CQRS.

[Learn more about projections →](./projections.md)

### Projectors <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Projectors are specialized event handlers responsible for maintaining
projections. They listen to domain events and update projection data, so the
read side of CQRS reflects the changes made on the write side.

[Learn more about projectors →](./projectors.md)

### Query Handlers <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Query handlers process named read intents (queries) and return results from projections. They are the read-side counterpart of command handlers, dispatched via `domain.dispatch(query)`.

[Learn more about query handlers →](./query-handlers.md)

### Subscribers

Subscribers consume messages from external message brokers and other systems outside the domain boundary. They serve as an anti-corruption layer, translating external data into domain operations.

[Learn more about subscribers →](./subscribers.md)

### Exchange events with other systems through CloudEvents <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Some events cross system boundaries to external APIs, Kafka topics, webhooks,
or other Protean domains. For those events, CloudEvents serialization
translates between Protean's internal metadata and the standard format. Protean
is a compliant CloudEvents v1.0 producer and consumer.

[Learn more about CloudEvents interoperability →](./cloudevents.md)

### Upcast old events to the current schema <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

When event schemas evolve, upcasters transform old event versions to match the current schema during replay. This is essential for long-lived event-sourced systems.

[Learn more about event upcasting →](./event-upcasting.md)

!!! seealso "See also"
    [Stream Categories](../../concepts/async-processing/stream-categories.md):
    how messages are organized and routed through named streams.
