# Dispatching Published Events to External Brokers

This guide shows how to deliver `published=True` domain events to external
message brokers so that other bounded contexts and partner systems can consume
them.

For the architectural rationale and trade-off analysis, see
[Publishing Events to External Brokers](../../patterns/publishing-events-to-external-brokers.md).

---

## Prerequisites

- A running Protean domain with the outbox enabled
  (`default_subscription_type = "stream"`)
- At least one event marked `published=True`
- An external broker configured in `domain.toml`

---

## 1. Mark events as published

Add `published=True` to any event that is part of your bounded context's
public API:

```python
@domain.event(part_of=Order, published=True)
class OrderShipped(BaseEvent):
    order_id: Identifier(required=True)
    shipped_at: DateTime(required=True)
    tracking_number: String(max_length=50)
```

Events without `published=True` are dispatched only to the internal broker.

---

## 2. Register the external broker

Define the external broker alongside your internal broker in `domain.toml`:

```toml
[brokers.default]
provider = "redis"
URI = "redis://localhost:6379/0"

[brokers.partner_events]
provider = "redis"
URI = "redis://partner-redis:6379/0"
```

The external broker can be any supported broker adapter (Redis Streams, Redis
PubSub, or a custom broker).

---

## 3. Configure external dispatch

Add `external_brokers` to the `[outbox]` section:

```toml
[outbox]
broker = "default"                       # Internal broker (existing)
external_brokers = ["partner_events"]    # NEW: external broker(s)
messages_per_tick = 50
tick_interval = 1
```

You can list multiple external brokers:

```toml
external_brokers = ["fulfillment_broker", "analytics_broker"]
```

Each published event will create one outbox row per external broker.

---

## 4. Set up the outbox table

If you haven't already, create the outbox table:

```bash
protean db setup --domain my_domain
```

The outbox table includes a `target_broker` column that routes each row to
the correct processor.

---

## 5. Start the server

```bash
protean server --domain=my_domain
```

The Engine creates one `OutboxProcessor` per broker per database provider.
With one database and two brokers (internal + one external), you'll see:

```
DEBUG: Creating outbox processor: outbox-processor-default-to-default
DEBUG: Creating external outbox processor: outbox-processor-default-to-partner_events-external
```

---

## 6. Verify

Raise a published event through your normal domain flow. Check the logs for:

```
DEBUG: Published to myapp::order: <message_id>     # Internal
DEBUG: Published to myapp::order: <message_id>     # External
```

Both rows advance through the outbox lifecycle independently. If the external
broker is temporarily down, the internal row publishes successfully while the
external row retries on its own schedule.

---

## What the external consumer receives

The external envelope strips internal metadata. A published `OrderShipped`
event arrives as:

```json
{
  "data": {
    "order_id": "ord-123",
    "shipped_at": "2026-03-05T10:30:00Z",
    "tracking_number": "1Z999AA10123456784"
  },
  "metadata": {
    "headers": {
      "id": "evt-abc-123",
      "type": "MyApp.Order.v1.OrderShipped.v1",
      "time": "2026-03-05T10:30:00.123456Z",
      "stream": "myapp::order-ord-123"
    },
    "domain": {
      "fqn": "myapp.orders.OrderShipped",
      "kind": "EVENT",
      "version": 1,
      "sequence_id": 3,
      "correlation_id": "corr-xyz",
      "causation_id": "cmd-456",
      "stream_category": "myapp::order"
    },
    "envelope": {
      "specversion": "1.0"
    },
    "extensions": {
      "tenant_id": "acme-corp"
    }
  }
}
```

Fields like `expected_version`, `asynchronous`, `priority`, and
`event_store` positions are removed. Consumers should use `headers.id` as
the deduplication key.

---

## Multiple external brokers

When you configure multiple external brokers, each published event creates
one outbox row per external broker. Each row is processed and retried
independently:

```toml
[outbox]
external_brokers = ["fulfillment_broker", "analytics_broker"]
```

```
Published event: OrderShipped
├── Row 1: target_broker = "default"            → internal handlers
├── Row 2: target_broker = "fulfillment_broker" → fulfillment BC
└── Row 3: target_broker = "analytics_broker"   → analytics pipeline
```

---

## Monitoring

External outbox processors emit distinct trace events:

| Trace Event | Meaning |
|-------------|---------|
| `outbox.published` | Internal message published successfully |
| `outbox.failed` | Internal message publish failed |
| `outbox.external_published` | External message published successfully |
| `outbox.external_failed` | External message publish failed |

Use these in the Observatory dashboard or your monitoring system to track
external dispatch health independently from internal processing.

---

## Validation warning

If your domain has events with `published=True` but no `external_brokers`
configured, Protean logs a warning during domain initialization:

```
WARNING: Domain has published events but no external_brokers configured
in outbox settings. Published events will only be dispatched internally.
```

This is a reminder, not an error. You can use `published=True` purely as a
semantic marker (for IR generation or documentation) without configuring
external brokers.

---

## Next steps

- [Publishing Events to External Brokers](../../patterns/publishing-events-to-external-brokers.md)
  -- Pattern: architecture, trade-offs, and anti-patterns
- [Outbox Pattern](../../concepts/async-processing/outbox.md) -- How the
  transactional outbox works
- [Consuming Events from Other Domains](../../patterns/consuming-events-from-other-domains.md)
  -- The consumer side: subscribers as anti-corruption layers
- [Server Configuration](../../reference/server/configuration.md) -- Full
  configuration reference
