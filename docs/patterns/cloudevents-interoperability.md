# CloudEvents as a Boundary Contract

## The Problem

Your order service raises an `OrderPlaced` event. An external fulfillment
system needs to consume it. The event carries Protean-specific metadata --
stream names, sequence IDs, causal chain identifiers, checksums -- structured
for DDD and event sourcing, not for generic consumers.

If you expose the internal metadata format directly:

- **Structural coupling.** External consumers depend on Protean's `metadata.headers`,
  `metadata.domain`, and `metadata.envelope` nesting. A refactor of your internal
  metadata breaks every consumer.

- **Vocabulary coupling.** Consumers must understand Protean-specific concepts
  like `stream_category`, `fqn`, and `expected_version` -- none of which are
  meaningful outside the bounded context.

- **No standard tooling.** Generic event routers, schema registries, and
  observability tools don't recognize Protean's format. You lose the ecosystem
  of CloudEvents-compatible middleware.

- **Bidirectional friction.** Consuming events *from* external systems requires
  ad-hoc parsing of whatever format they chose.

The root cause: **internal event metadata is optimized for the domain, not for
interoperability**. Exposing it directly couples every external consumer to your
framework's internals.

---

## The Pattern

Use [CloudEvents v1.0](https://cloudevents.io/) as the serialization format
**at system boundaries only**. Internal metadata stays DDD-native. CloudEvents
is an anti-corruption layer applied during serialization, not a structural
change to your domain model.

```
Your Domain                    Boundary                     External System
┌─────────────────┐    to_cloudevent()    ┌──────────────────┐
│ Protean Message  │ ──────────────────►  │ CloudEvents JSON │ ──► Kafka / HTTP / ...
│ (DDD metadata)   │                      │ (standard format)│
└─────────────────┘                      └──────────────────┘

External System                Boundary                     Your Domain
┌──────────────────┐   from_cloudevent()  ┌─────────────────┐
│ CloudEvents JSON │ ──────────────────►  │ Protean Message  │ ──► Subscriber / Handler
│ (standard format)│                      │ (DDD metadata)   │
└──────────────────┘                      └─────────────────┘
```

This mirrors the subscriber / ACL pattern that Protean already uses for
consuming external events -- except instead of translating external events
*inward*, we also translate internal events *outward*.

---

## How Protean Supports It

### Producing CloudEvents

Every `Message` has a `to_cloudevent()` method that derives all CloudEvents
attributes from existing Protean metadata:

```python
from protean.utils.eventing import Message

message = Message.from_domain_object(event)
cloud_event = message.to_cloudevent()

# Publish to external topic
kafka_producer.send("orders", json.dumps(cloud_event))
```

All required CloudEvents attributes (`specversion`, `id`, `type`, `source`)
are derived automatically. Protean-specific metadata (causal chains, checksums,
sequence tracking) rides alongside as `protean`-namespaced extension
attributes.

### Consuming CloudEvents

Parse incoming CloudEvents into Protean messages:

```python
message = Message.from_cloudevent(cloud_event_dict)

# For external events: access data directly
order_id = message.data["order_id"]

# For Protean-originated events: reconstruct the domain object
event = message.to_domain_object()
```

### Configuring source

The CloudEvents `source` attribute identifies your bounded context. Configure
it in `domain.toml`:

```toml
source_uri = "https://orders.example.com"
```

If not configured, Protean derives it from the domain name:
`urn:protean:<normalized_domain_name>`.

### Extension philosophy

CloudEvents deliberately has a small core (4 required attributes) with an
extension model for domain-specific concerns. Protean uses this exactly as
intended:

- **Core attributes** cover interoperability (who sent it, what type, when).
- **`protean`-prefixed extensions** carry DDD-specific metadata that Protean
  consumers understand but generic consumers can ignore.
- **User extensions** from [message enrichers](../guides/domain-behavior/message-enrichment.md)
  are merged directly into the CloudEvent.

---

## Applying the Pattern

### Publishing to an external Kafka topic

```python
@domain.event_handler(part_of=Order)
class OrderEventPublisher:

    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced) -> None:
        message = Message.from_domain_object(event)
        cloud_event = message.to_cloudevent()

        kafka_producer.send(
            topic="order-events",
            value=json.dumps(cloud_event).encode(),
        )
```

The external fulfillment system receives a standard CloudEvents JSON object.
It doesn't need to know about Protean, stream categories, or event sourcing
mechanics.

### Receiving from an external webhook

```python
@domain.subscriber(stream="payment-webhooks")
class PaymentWebhookSubscriber:

    def __call__(self, payload: dict) -> None:
        message = Message.from_cloudevent(payload)

        if message.metadata.headers.type == "com.stripe.payment.succeeded":
            current_domain.process(
                ConfirmPayment(
                    payment_id=message.data["payment_intent_id"],
                    amount=message.data["amount"],
                )
            )
```

### Multi-domain Protean system

Two Protean services communicate via CloudEvents over a message broker:

```python
# Service A: publish
message = Message.from_domain_object(event)
broker.publish("shared-topic", message.to_cloudevent())

# Service B: consume and reconstruct
cloud_event = broker.receive("shared-topic")
message = Message.from_cloudevent(cloud_event)
event = message.to_domain_object()  # Works if type is registered
```

The correlation ID, causation ID, and checksum survive the round-trip via
`protean`-prefixed extensions.

---

## Anti-Patterns

### Restructuring internal metadata for CloudEvents

> "Let's rename `headers.type` to `type` and `domain.stream_category` to
> `source` so our internal format matches CloudEvents."

Internal metadata is optimized for DDD and event sourcing. CloudEvents is
optimized for interoperability. These are different concerns. `to_cloudevent()`
bridges the gap without contaminating either model.

### Adding CloudEvents-only fields to internal metadata

> "Let's add `source`, `subject`, and `datacontenttype` fields to
> `MessageHeaders`."

These fields would always duplicate information already available elsewhere
(domain name, stream name, "application/json"). Redundant storage creates
maintenance burden and divergence risk. Derive them at serialization time.

### Using CloudEvents format for internal event storage

> "Let's store all events in CloudEvents format in the event store."

CloudEvents is a wire format, not a storage format. Protean's internal format
carries richer metadata (expected version, stream category, event store
positions, processing priority) that CloudEvents doesn't represent. Use
CloudEvents at the boundary; use Protean's native format internally.

---

## When Not to Use

- **Single-domain applications** with no external integrations. If all
  consumers are within the same bounded context, Protean's native format
  is simpler and carries more information.

- **Internal event handlers** that only consume events from the same domain.
  They receive typed domain objects directly -- no serialization needed.

- **Performance-critical internal paths** where the serialization overhead
  of `to_cloudevent()` is unnecessary. CloudEvents is for boundary crossing,
  not for hot internal loops.

---

## Summary

| Aspect | Guidance |
|---|---|
| **When** | Events cross bounded context boundaries |
| **How** | `to_cloudevent()` to produce, `from_cloudevent()` to consume |
| **Configure** | `source_uri` in `domain.toml` for stable source identification |
| **Extensions** | `protean`-prefixed for DDD metadata; user extensions from enrichers |
| **Internal format** | Unchanged -- CloudEvents is a serialization concern |
| **Round-trip** | Data, type, correlation/causation, checksum all preserved |

---

!!! note "Related"
    - [CloudEvents Interoperability Guide](../guides/consume-state/cloudevents.md) --
      Step-by-step instructions for producing and consuming CloudEvents.
    - [Consuming Events from Other Domains](consuming-events-from-other-domains.md) --
      The subscriber / ACL pattern for external event consumption.
    - [Fact Events as Integration Contracts](fact-events-as-integration-contracts.md) --
      Using fact events for cross-context state snapshots.
    - [Message Tracing](message-tracing.md) -- How correlation and causation IDs
      flow through causal chains.
    - [Message Enrichment](message-enrichment.md) -- Attaching custom metadata
      to events and commands.
