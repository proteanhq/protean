# Message Enrichment

<span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

In event-driven systems, every event and command often needs cross-cutting
metadata that has nothing to do with the event's business payload, who
performed the action, which tenant it belongs to, the originating IP address,
or custom audit context. Without a central mechanism, developers must sprinkle
this logic into every `raise_()` call, which is repetitive and easy to forget.

**Message enrichment hooks** solve this by letting you register callables on
the domain that automatically add custom metadata to every event and command.
The enriched data is stored in `metadata.extensions`. A user-space dict that is
persisted alongside all other metadata in the event store and survives
serialization round-trips.

## Event Enrichers

An **event enricher** is a callable that receives the event being raised and
the aggregate instance, and returns a `dict[str, Any]` of key-value pairs
to merge into `metadata.extensions`.

### Registration

Register enrichers with `domain.register_event_enricher()` or the
`@domain.event_enricher` decorator. In these examples, helpers such as
`get_current_user()` and `get_client_ip()` read request values that your app
put on Protean's `g`:

```python
--8<-- "guides/domain-behavior/message-enrichment/001.py:functional"
```

```python
--8<-- "guides/domain-behavior/message-enrichment/001.py:decorator"
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
# fragment
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
--8<-- "guides/domain-behavior/message-enrichment/002.py:fifo"
```

## Command Enrichers

A **command enricher** works the same way but for commands processed via
`domain.process()`. Since commands haven't reached a handler yet, enrichers
receive only the command (no aggregate):

```python
--8<-- "guides/domain-behavior/message-enrichment/001.py:command"
```

### Enricher Signature

```python
# fragment
def enricher(command: BaseCommand) -> dict[str, Any]:
    """Return key-value pairs to merge into metadata.extensions."""
```

## Aggregate Pre-Persist Enrichers

Event and command enrichers write to `metadata.extensions`. When you instead
need to stamp fields **on the aggregate itself** (audit columns like
`updated_by`, or lifecycle timestamps) register an **aggregate enricher**. It
runs in the persistence path just before an aggregate is saved (on both create
and update), and unlike the enrichers above it **mutates the aggregate in
place** rather than returning a dict:

```python
--8<-- "guides/domain-behavior/message-enrichment/003.py:stamp_audit"
```

Put the acting user on the context so the enricher can read it:

```python
--8<-- "guides/domain-behavior/message-enrichment/003.py:save_as"
```

Aggregate enrichers run in registration order and fire only for aggregates (not
child entities). If one raises, the save is aborted.

The aggregate's `@invariant.pre` checks do not run on an enricher's writes,
because stamping an audit field is not a business change. So a closed aggregate
whose pre-invariant rejects changes can still be saved. The `@invariant.post`
checks run once after each enricher, and the status-transition rules still
apply to a status field it changes. When one of them fails, the enricher's
writes are undone and the save is aborted with a `ValidationError` whose
`location` names the enricher, for example
`aggregate enricher myapp.audit.stamp_audit`. `auto_now` and `auto_now_add`
stamping works the same way, and its `location` names the stamped fields.

Aggregate enrichers also fire for the records Protean itself saves through
repositories, such as outbox rows and the message records of the in-memory event
store. That is why the example skips an aggregate without `updated_by`.

Keep them to cross-cutting lifecycle/audit metadata; they are not a hook for
business logic or for raising events. For the complete recipe (an abstract audit
base with `auto_now`/`auto_now_add` timestamps plus `created_by`/`updated_by`),
see [Track Audit and Lifecycle Fields](../../patterns/track-audit-fields.md).

## Accessing Extensions

After raising an event, extensions are available on the metadata:

```python
--8<-- "guides/domain-behavior/message-enrichment/001.py:extensions"
```

Extensions are included in the serialized form and survive round-trips
through the event store:

```python
--8<-- "guides/domain-behavior/message-enrichment/001.py:round_trip"
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

1. **Keep enrichers fast**: They run synchronously inside `raise_()` for
   every event. Avoid I/O calls; prefer reading from thread-local context
   (like Flask's `g` or Protean's `g`).

2. **Use enrichers for cross-cutting concerns only**: User context, tenant
   ID, request tracing, audit metadata. Don't use them for business logic
   that belongs in the aggregate or event itself.

3. **Use `metadata.extensions` for querying**: The Outbox and event store
   persist extensions, making them available for filtering and correlation
   in downstream processing.

4. **Combine with [message tracing](message-tracing.md)**: Enrichers
   complement correlation and causation IDs. Use correlation_id for causal
   chains and extensions for contextual metadata (who, where, why).

---

!!! tip "See also"
    **Related guides:**

    - [Message Tracing](message-tracing.md): Correlation and causation IDs for distributed tracing, plus the programmatic causation chain API
    - [Correlation and Causation IDs](../observability/correlation-and-causation.md): Complete guide covering HTTP headers, OTEL spans, Observatory, logging, and cross-service propagation
    - [Raising Events](raising-events.md): How aggregates raise domain events
    - [Commands](../../guides/change-state/commands.md): Command processing via `domain.process()`
