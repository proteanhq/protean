# Message Enrichment

!!! abstract "Applies to: CQRS · Event Sourcing"


In event-driven systems, every event and command often needs cross-cutting
metadata that has nothing to do with the event's business payload -- who
performed the action, which tenant it belongs to, the originating IP address,
or custom audit context. Without a central mechanism, developers must sprinkle
this logic into every `raise_()` call, which is repetitive and easy to forget.

**Message enrichment hooks** solve this by letting you register callables on
the domain that automatically add custom metadata to every event and command.
The enriched data is stored in `metadata.extensions` -- a user-space dict that
is persisted alongside all other metadata in the event store and survives
serialization round-trips.

## Event Enrichers

An **event enricher** is a callable that receives the event being raised and
the aggregate instance, and returns a `dict[str, Any]` of key-value pairs
to merge into `metadata.extensions`.

### Registration

Register enrichers with `domain.register_event_enricher()` or the
`@domain.event_enricher` decorator:

```python
# Functional registration
def add_user_context(event, aggregate):
    """Enrich every event with the current user."""
    user = get_current_user()
    return {
        "user_id": user.id if user else "system",
        "tenant_id": get_current_tenant_id(),
    }

domain.register_event_enricher(add_user_context)
```

```python
# Decorator registration
@domain.event_enricher
def add_audit_context(event, aggregate):
    return {"ip_address": get_client_ip()}
```

### How It Works

Enrichers run inside `aggregate.raise_()`, **after** the event's full metadata
(headers, envelope, domain meta) is constructed but **before** the event is
appended to `aggregate._events`. This means:

- Enrichers have access to the **event payload** (e.g., `event.email`)
- Enrichers have access to the **aggregate** (e.g., `aggregate.tenant_id`, `aggregate.id`)
- The event's core metadata (correlation ID, stream, sequence) is already set
- Extensions are included when the event is stored in the event store

### Enricher Signature

```python
def enricher(event: BaseEvent, aggregate: BaseAggregate) -> dict[str, Any]:
    """Return key-value pairs to merge into metadata.extensions."""
```

| Parameter   | Description |
|-------------|-------------|
| `event`     | The domain event being raised, with its payload fields accessible |
| `aggregate` | The aggregate instance raising the event |
| **Returns** | A `dict[str, Any]` merged into `metadata.extensions` |

### Multiple Enrichers

You can register any number of enrichers. They execute in registration order
(FIFO), and their results are merged. If two enrichers set the same key, the
later one wins:

```python
@domain.event_enricher
def add_user(event, aggregate):
    return {"source": "user-enricher", "user_id": "u-123"}

@domain.event_enricher
def add_tenant(event, aggregate):
    return {"source": "tenant-enricher", "tenant_id": "t-456"}

# Result: {"source": "tenant-enricher", "user_id": "u-123", "tenant_id": "t-456"}
```

## Command Enrichers

A **command enricher** works the same way but for commands processed via
`domain.process()`. Since commands haven't reached a handler yet, enrichers
receive only the command (no aggregate):

```python
@domain.command_enricher
def add_request_context(command):
    return {
        "request_id": get_request_id(),
        "ip_address": get_client_ip(),
    }
```

### Enricher Signature

```python
def enricher(command: BaseCommand) -> dict[str, Any]:
    """Return key-value pairs to merge into metadata.extensions."""
```

## Accessing Extensions

After raising an event, extensions are available on the metadata:

```python
user.register()
event = user._events[0]
print(event._metadata.extensions)
# {"user_id": "u-123", "tenant_id": "acme-corp"}
```

Extensions are included in the serialized form and survive round-trips
through the event store:

```python
message = Message.from_domain_object(event)
msg_dict = message.to_dict()
print(msg_dict["metadata"]["extensions"])
# {"user_id": "u-123", "tenant_id": "acme-corp"}

# Deserialize back
restored = Message.deserialize(msg_dict)
print(restored.metadata.extensions)
# {"user_id": "u-123", "tenant_id": "acme-corp"}
```

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Enricher returns `None` | Treated as no-op, extensions unchanged |
| Enricher returns `{}` | Treated as no-op, extensions unchanged |
| Enricher raises an exception | Exception propagates; event is not appended / command is not processed |
| No enrichers registered | `extensions` defaults to `{}` |
| Legacy messages (pre-enrichment) | Deserialize with `extensions: {}` |

## Fact Events

Event enrichers also run on [fact events](../domain-definition/events.md#fact-events).
Since fact events pass through `raise_()` like any other event, they
are enriched automatically.

## Best Practices

1. **Keep enrichers fast** -- they run synchronously inside `raise_()` for
   every event. Avoid I/O calls; prefer reading from thread-local context
   (like Flask's `g` or Protean's `g`).

2. **Use enrichers for cross-cutting concerns only** -- user context, tenant
   ID, request tracing, audit metadata. Don't use them for business logic
   that belongs in the aggregate or event itself.

3. **Use `metadata.extensions` for querying** -- the Outbox and event store
   persist extensions, making them available for filtering and correlation
   in downstream processing.

4. **Combine with [message tracing](message-tracing.md)** -- enrichers
   complement correlation and causation IDs. Use correlation_id for causal
   chains and extensions for contextual metadata (who, where, why).

---

!!! tip "See also"
    **Related guides:**

    - [Message Tracing](message-tracing.md) -- Correlation and causation IDs for distributed tracing, plus the programmatic causation chain API
    - [Raising Events](raising-events.md) -- How aggregates raise domain events
    - [Commands](../../guides/change-state/commands.md) -- Command processing via `domain.process()`
