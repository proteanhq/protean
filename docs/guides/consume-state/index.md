# React to Changes

<span class="pathway-tag pathway-tag-ddd">DDD</span> <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

The reactive layer responds to state changes that have already happened. It propagates changes across aggregates, maintains read-optimized views, coordinates multi-step processes, and bridges to external systems — all without coupling back to the code that produced the original change.

## Core Concepts

### Event Handlers

Event handlers consume domain events and orchestrate side effects — syncing state across aggregates, sending notifications, or triggering downstream processes. They follow a fire-and-forget pattern and operate within their own transaction boundaries.

[Learn more about event handlers →](./event-handlers.md)

### Process Managers

Process managers coordinate multi-step business processes that span multiple aggregates. They react to events, maintain their own state, and issue commands to drive other aggregates forward.

[Learn more about process managers →](./process-managers.md)

### Projections <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Projections are read-optimized, denormalized views built from domain events. They provide fast query access without loading full aggregate graphs, forming the read side of CQRS.

[Learn more about projections →](./projections.md)

### Projectors <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Projectors are specialized event handlers responsible for maintaining projections. They listen to domain events and update projection data, bridging the write and read sides of CQRS.

[Learn more about projectors →](./projectors.md)

### Query Handlers <span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Query handlers process named read intents (queries) and return results from projections. They are the read-side counterpart of command handlers, dispatched via `domain.dispatch(query)`.

[Learn more about query handlers →](./query-handlers.md)

### Subscribers

Subscribers consume messages from external message brokers and other systems outside the domain boundary. They serve as an anti-corruption layer, translating external data into domain operations.

[Learn more about subscribers →](./subscribers.md)

## Supporting Topics

- [Stream Categories](../../concepts/async-processing/stream-categories.md) — How messages are organized and routed through named streams.
- [Event Upcasting](./event-upcasting.md) <span class="pathway-tag pathway-tag-es">ES</span> — Transforming old event schemas to match the current version during replay.
