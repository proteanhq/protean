# CloudEvents Interoperability

<span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

Protean is a compliant [CloudEvents v1.0](https://cloudevents.io/) producer and
consumer. When events need to cross bounded context boundaries (external APIs,
Kafka topics, webhooks, or other Protean domains) `to_cloudevent()` and
`from_cloudevent()` translate between Protean's internal metadata and the
CloudEvents standard without modifying your domain model.

Internally, Protean uses its own metadata structure (headers, domain meta,
envelope) optimized for DDD, event sourcing, and causal chain tracking.
CloudEvents serialization is an **anti-corruption layer** at the boundary:
your domain code stays DDD-native, while external consumers see a
standards-compliant event format.

## Producing CloudEvents

Any Protean `Message` can be serialized to a CloudEvents v1.0 JSON object.
Here an `Order` raises an `OrderPlaced` event, and the event goes out as a
CloudEvent:

```python
--8<-- "guides/consume-state/cloudevents/001.py:produce"
```

The resulting dict is a valid CloudEvents v1.0 JSON object:

```json
{
    "specversion": "1.0",
    "id": "myapp::order-abc123-0.1",
    "type": "MyApp.OrderPlaced.v1",
    "source": "https://orders.example.com",
    "time": "2026-03-02T10:30:00+00:00",
    "subject": "abc123",
    "datacontenttype": "application/json",
    "proteankind": "EVENT",
    "proteanchecksum": "sha256...",
    "sequence": "0.1",
    "proteansequencetype": "DotNotation",
    "data": {
        "order_id": "abc123",
        "customer_id": "cust-456",
        "total": 99.99
    }
}
```

Every CloudEvents attribute is **derived** from existing Protean metadata.
Nothing is stored redundantly. Attributes with no value are left out. Here
the event was raised outside a command handler, so it has no
`proteancorrelationid` or `proteancausationid`.

## Attribute Mapping

### Required attributes

| CloudEvents | Derived from | Notes |
|---|---|---|
| `specversion` | Literal `"1.0"` | Always CloudEvents v1.0 |
| `id` | `metadata.headers.id` | Protean's composite message ID |
| `type` | `metadata.headers.type` | Protean format `Domain.Event.v1`, valid per spec |
| `source` | `source_uri` config or domain name | See [Configuring source](#configuring-source) |

### Optional attributes

| CloudEvents | Derived from | Notes |
|---|---|---|
| `time` | `metadata.headers.time` | RFC 3339 / ISO 8601 string |
| `subject` | Parsed from stream name | Aggregate identifier |
| `datacontenttype` | Literal `"application/json"` | Protean always uses JSON |

### Protean extensions

Protean-specific metadata that has no CloudEvents equivalent is carried as
`protean`-namespaced extension attributes:

| Extension | Derived from | Purpose |
|---|---|---|
| `traceparent` | `metadata.headers.traceparent` | W3C distributed trace context |
| `sequence` | `metadata.domain.sequence_id` | Event position in aggregate |
| `proteansequencetype` | Inferred from `sequence_id` | `"Integer"` (ES) or `"DotNotation"` (non-ES) |
| `proteancorrelationid` | `metadata.domain.correlation_id` | Constant across causal chain |
| `proteancausationid` | `metadata.domain.causation_id` | Parent message that caused this |
| `proteanchecksum` | `metadata.envelope.checksum` | SHA-256 payload integrity hash |
| `proteankind` | `metadata.domain.kind` | `"EVENT"` or `"COMMAND"` |

User-supplied extensions from [message enrichers](../domain-behavior/message-enrichment.md)
(`metadata.extensions`) are merged into the top level of the CloudEvent.

## Configuring source

The CloudEvents `source` attribute identifies the context in which the event
occurred, in DDD terms, the bounded context. Protean derives it automatically,
but you can configure an explicit URI:

```toml title="domain.toml"
source_uri = "https://orders.example.com"
```

**Fallback chain** (when `source_uri` is not configured):

1. Domain name → `urn:protean:<normalized_domain_name>`
2. Stream category prefix → `urn:protean:<domain_part>`
3. Last resort → `"urn:protean:unknown"`

For production multi-domain systems, always configure `source_uri` explicitly
so external consumers see a meaningful, stable identifier.

## Consuming CloudEvents

Parse an incoming CloudEvents JSON object into a Protean `Message`:

```python
--8<-- "guides/consume-state/cloudevents/001.py:consume"
```

### External events

When consuming events from a non-Protean system, the `type` string won't match
any registered Protean event. Access the data directly:

```python
--8<-- "guides/consume-state/cloudevents/002.py:subscriber"
```

### Protean-to-Protean round-trip

When two Protean services communicate via CloudEvents, the type string
is in Protean format and can be resolved back to the original domain object:

```python
--8<-- "guides/consume-state/cloudevents/001.py:to-domain-object"
```

### What gets preserved

When parsing a CloudEvent, Protean maps attributes back to their internal
locations:

| CE Attribute | Protean Destination |
|---|---|
| `id` | `headers.id` |
| `type` | `headers.type` |
| `time` | `headers.time` |
| `source` | `extensions["ce_source"]` |
| `subject` | `extensions["ce_subject"]` |
| `traceparent` | `headers.traceparent` |
| `proteancorrelationid` | `domain.correlation_id` |
| `proteancausationid` | `domain.causation_id` |
| `proteanchecksum` | `envelope.checksum` |
| `proteankind` | `domain.kind` |
| `sequence` | `domain.sequence_id` |
| Unknown extensions | `extensions` (preserved as-is) |

## Round-tripping

A CloudEvent produced by Protean can be consumed back with full fidelity:

```python
--8<-- "guides/consume-state/cloudevents/001.py:round-trip"
```

The `source` attribute is re-derived during the next `to_cloudevent()` call
(from domain config), so it is preserved in `extensions["ce_source"]` for
reference but not mapped to a dedicated internal field.

## Validation

`from_cloudevent()` validates the incoming CloudEvent:

- **Required attributes** (`specversion`, `id`, `type`, `source`) must be
  present, raises `ValueError` if missing.
- **Spec version** must be `"1.0"`. Anything else raises `ValueError`.
- **Checksum** is computed from `data` if not provided via `proteanchecksum`.

---

!!! note "Related"
    - [Message Tracing](../domain-behavior/message-tracing.md): How `correlation_id` and
      `causation_id` flow through causal chains.
    - [Message Enrichment](../domain-behavior/message-enrichment.md): How to attach custom
      metadata to events and commands.
    - [Consuming Events from Other Domains](../../patterns/consuming-events-from-other-domains.md):
      The subscriber / anti-corruption layer pattern.
    - [CloudEvents as a Boundary Contract](../../patterns/cloudevents-interoperability.md):
      When and why to use CloudEvents at system boundaries.
