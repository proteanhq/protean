# Publishing Events to External Brokers

## The Problem

Your bounded context raises domain events that drive internal reactions —
event handlers sync state across aggregates, projectors update read models,
and process managers coordinate workflows. All of these flow through a single
internal broker (typically Redis Streams via the outbox pattern).

But some events are part of your **public contract**. Other bounded contexts,
partner systems, or downstream services need to consume them. You mark events
with `published=True` to signal this intent:

```python
@domain.event(part_of=Order, published=True)
class OrderShipped(BaseEvent):
    order_id: Identifier(required=True)
    shipped_at: DateTime(required=True)
    tracking_number: String(max_length=50)
```

Without external dispatch, `published=True` is a semantic marker with no
runtime effect. The event only flows through the internal broker. External
consumers never see it.

You could work around this by writing an event handler that manually publishes
to a second broker:

```python
# Anti-pattern: manual relay handler
@domain.event_handler(part_of=Order)
class ExternalRelayHandler(BaseEventHandler):

    @handle(OrderShipped)
    def relay(self, event: OrderShipped):
        external_broker = current_domain.brokers["partner_kafka"]
        external_broker.publish(
            stream="orders",
            data=event.payload,
        )
```

This has several problems:

1. **Coupled to broker internals.** The handler bypasses Protean's outbox,
   losing transactional guarantees. If the relay handler succeeds but the
   internal side fails (or vice versa), you get split-brain.

2. **No independent retry.** A transient failure on the external broker
   fails the handler, which blocks internal processing.

3. **Metadata leaks.** The event's internal metadata (`expected_version`,
   `priority`, `asynchronous`) is irrelevant — and potentially confusing — to
   external consumers.

4. **Every published event needs a handler.** As the public surface grows,
   you accumulate boilerplate relay handlers.

---

## The Pattern

**Fork at the outbox.** When a `published=True` event is persisted, create
one outbox row per target broker — one for internal dispatch and one for each
configured external broker. Each row is processed independently by its own
`OutboxProcessor`, with independent retry, independent status tracking, and an
external-specific message envelope that strips internal metadata.

The producing bounded context's responsibility ends at broker push. It does
not track whether external consumers have read the message. The external broker
handles delivery semantics from that point.

### Core Principles

1. **Transactional atomicity.** Internal and external outbox rows are written
   in the same database transaction as the aggregate mutation. No event is
   ever partially published.

2. **Independent failure isolation.** External broker downtime does not block
   internal event processing. Each outbox row advances through the lifecycle
   independently.

3. **Clean external envelope.** External consumers receive only the fields
   they need: headers for deduplication, domain context for routing, and
   user-provided extensions. Internal routing fields (`expected_version`,
   `asynchronous`, `priority`) are stripped.

4. **Zero-change backward compatibility.** The feature activates only when
   `external_brokers` is explicitly configured. Existing deployments are
   unaffected.

---

## How Protean Supports It

### Configuration

Add the external broker(s) to your outbox configuration:

```toml
# domain.toml
[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"

[brokers.partner_events]
provider = "redis"
URI = "redis://partner-redis:6379/0"

[outbox]
broker = "default"                       # Internal broker
external_brokers = ["partner_events"]    # External broker(s) for published events
messages_per_tick = 50
tick_interval = 1
```

That's the only configuration change. No code changes to aggregates, events,
or handlers.

### What Happens at Commit Time

When a Unit of Work commits an aggregate that raised a `published=True` event:

```
┌─────────────────────────────────────────────────────────────┐
│                   Database Transaction                       │
│                                                             │
│  ┌─────────────┐  ┌──────────────────────────────────────┐  │
│  │ Aggregate   │  │ Outbox Table                         │  │
│  │ mutation    │  │                                      │  │
│  │ (orders)    │  │  Row 1: target_broker = "default"    │  │
│  │             │  │  Row 2: target_broker = "partner"    │  │
│  └─────────────┘  └──────────────────────────────────────┘  │
│                                                             │
│  Both written in the same transaction                       │
└─────────────────────────────────────────────────────────────┘
```

For a non-published event, only the internal row (Row 1) is created.

### Outbox Processing

The Engine creates separate `OutboxProcessor` instances for each broker:

```
Internal Processor                    External Processor
─────────────────                    ──────────────────
Polls: target_broker = "default"     Polls: target_broker = "partner_events"
Publishes to: default (Redis)        Publishes to: partner_events (Redis)
Envelope: full internal metadata     Envelope: stripped external metadata
Priority lanes: yes                  Priority lanes: no (external only)
Trace event: outbox.published        Trace event: outbox.external_published
```

Each processor runs independently. If the external broker is down, the
external row retries on its own schedule while internal processing continues
uninterrupted.

### External Message Envelope

The external envelope strips internal-only fields while preserving everything
an external consumer needs:

| Field | Kept | Stripped | Why |
|-------|------|---------|-----|
| `headers.id` | Yes | | Idempotency / deduplication key |
| `headers.type` | Yes | | Event type for routing |
| `headers.time` | Yes | | Event timestamp |
| `headers.stream` | Yes | | Origin stream |
| `headers.traceparent` | Yes | | Distributed tracing |
| `domain.fqn` | Yes | | Fully qualified event name |
| `domain.kind` | Yes | | MESSAGE / EVENT / COMMAND |
| `domain.version` | Yes | | Schema version |
| `domain.sequence_id` | Yes | | Event ordering |
| `domain.correlation_id` | Yes | | Correlation tracking |
| `domain.causation_id` | Yes | | Causal chain |
| `domain.origin_stream` | Yes | | Where the event originated |
| `domain.stream_category` | Yes | | Routing category |
| `domain.expected_version` | | Yes | Internal concurrency control |
| `domain.asynchronous` | | Yes | Internal processing flag |
| `domain.priority` | | Yes | Internal priority routing |
| `event_store.*` | | Yes | Internal store positions |
| `envelope.checksum` | | Yes | Internal integrity check |
| `extensions.*` | Yes | | User-provided enrichments |
| `envelope.specversion` | Yes (hardcoded `"1.0"`) | | Protocol version |

---

## Applying the Pattern

### Step 1: Mark events as published

```python
@domain.event(part_of=Order, published=True)
class OrderShipped(BaseEvent):
    order_id: Identifier(required=True)
    shipped_at: DateTime(required=True)
    tracking_number: String(max_length=50)


@domain.event(part_of=Order)
class OrderNoteAdded(BaseEvent):
    """Internal-only event — not published."""
    order_id: Identifier(required=True)
    note: Text()
```

Only `OrderShipped` will be dispatched to external brokers.
`OrderNoteAdded` flows only through the internal broker.

### Step 2: Configure external brokers

```toml
[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"

[brokers.fulfillment_broker]
provider = "redis"
URI = "redis://fulfillment-redis:6379/0"

[brokers.analytics_broker]
provider = "redis"
URI = "redis://analytics-redis:6379/0"

[outbox]
broker = "default"
external_brokers = ["fulfillment_broker", "analytics_broker"]
```

With this configuration, `OrderShipped` creates three outbox rows:

1. `target_broker = "default"` — internal event handlers, projectors
2. `target_broker = "fulfillment_broker"` — fulfillment bounded context
3. `target_broker = "analytics_broker"` — analytics pipeline

### Step 3: Start the server

```bash
protean server --domain=my_domain
```

The Engine automatically creates outbox processors for each broker. No
additional flags or commands needed.

### Step 4: Consume on the other side

In the consuming bounded context, use a subscriber to receive the event:

```python
# In the Fulfillment domain
@fulfillment.subscriber(broker="default", stream="myapp::order")
class OrderEventSubscriber(BaseSubscriber):

    def __call__(self, payload: dict) -> None:
        event_type = payload.get("metadata", {}).get("headers", {}).get("type", "")
        if "OrderShipped" in event_type:
            data = payload.get("data", {})
            fulfillment.process(
                CreateShipment(
                    order_id=data["order_id"],
                    tracking_number=data["tracking_number"],
                )
            )
```

The subscriber acts as an anti-corruption layer, translating the external
event into a domain command. The consuming domain never depends on the
producing domain's internal event classes.

---

## Anti-Patterns

### Manual relay handlers

```python
# Bad: bypasses outbox guarantees
@domain.event_handler(part_of=Order)
class ManualRelay(BaseEventHandler):
    @handle(OrderShipped)
    def relay(self, event):
        external_broker.publish(...)  # No transactional guarantee
```

Use `external_brokers` configuration instead. The outbox handles
transactional guarantees, retries, and failure isolation automatically.

### Publishing all events externally

```python
# Bad: every event is published
@domain.event(part_of=Order, published=True)
class OrderNoteAdded(BaseEvent):
    ...  # Internal detail, not a contract
```

Be selective. Only mark events as `published` when they are part of your
bounded context's **public API**. Internal implementation details should not
leak to external consumers. Every published event is a contract you must
maintain.

### Relying on internal metadata in consumers

```python
# Bad: consumer depends on internal fields
def __call__(self, payload: dict):
    priority = payload["metadata"]["domain"]["priority"]  # Stripped!
    if priority > 5:
        ...
```

External envelopes intentionally strip `priority`, `expected_version`, and
other internal fields. Design your public events to carry all the context
consumers need in the event `data` and `extensions`.

---

## When to Use

- **Cross-bounded-context communication.** Other domains need to react to your
  events.
- **Partner integrations.** External systems consume events from your message
  broker.
- **Event-driven data pipelines.** Analytics, reporting, or data lake ingestion
  from your event stream.
- **Gradual migration.** You're splitting a monolith and need to publish events
  from the first extracted service.

## When Not to Use

- **Single bounded context.** If all consumers are internal event handlers
  within the same domain, external dispatch adds unnecessary overhead.
- **Synchronous API responses.** If the consumer needs a synchronous response,
  use an API call, not event dispatch.
- **Shared database.** If two services share a database (not recommended in
  DDD, but sometimes pragmatic), you don't need broker-based event dispatch.

---

## Trade-offs

| Dimension | Impact |
|-----------|--------|
| **Storage** | One additional outbox row per external broker per published event. For N external brokers and M published events per transaction, this adds N×M rows. |
| **Latency** | External dispatch runs on the outbox tick interval (default 1 second), same as internal. No additional latency. |
| **Ordering** | Events are published in outbox insertion order per broker. Cross-broker ordering is not guaranteed. |
| **Exactly-once** | The outbox provides at-least-once delivery. External consumers should be idempotent (use `headers.id` for deduplication). |
| **Schema evolution** | Published events are contracts. Use [event versioning](event-versioning-and-evolution.md) to evolve them without breaking consumers. |

---

## Summary

| Aspect | Recommendation |
|--------|---------------|
| Mark public events | `@domain.event(part_of=Agg, published=True)` |
| Configure external brokers | `outbox.external_brokers = ["broker_name"]` |
| Message envelope | Internal fields stripped automatically |
| Failure isolation | External broker failure doesn't block internal processing |
| Consumer responsibility | Use subscribers as anti-corruption layers |
| Ordering | Preserved per-broker, not cross-broker |
| Delivery guarantee | At-least-once; consumers must be idempotent |

---

!!! tip "Related reading"

    - [Outbox Pattern](../concepts/async-processing/outbox.md) -- How the
      transactional outbox works
    - [Fact Events as Integration Contracts](fact-events-as-integration-contracts.md)
      -- Using fact events instead of delta events for external consumers
    - [Consuming Events from Other Domains](consuming-events-from-other-domains.md)
      -- The consumer side: subscribers as anti-corruption layers
    - [CloudEvents as a Boundary Contract](cloudevents-interoperability.md) --
      Standardized envelope format for interoperability
    - [Idempotent Event Handlers](idempotent-event-handlers.md) -- Why external
      consumers must handle duplicates
    - [External Dispatch Guide](../guides/server/external-event-dispatch.md) --
      Step-by-step setup instructions
