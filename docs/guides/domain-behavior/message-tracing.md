# Message Tracing

!!! abstract "Applies to: CQRS · Event Sourcing"


In event-driven systems, a single user action can trigger a chain of commands
and events that cascade across multiple aggregates and handlers. **Message
tracing** lets you follow the full causal chain -- from the initial request
through every command and event it spawns -- using two identifiers that Protean
attaches to every message automatically:

- **`correlation_id`**: A constant identifier shared by *every* message in the
  chain. It answers: "Which business operation does this message belong to?"
- **`causation_id`**: The `headers.id` of the *immediate parent* message. It
  answers: "What directly caused this message?"

Together, they let you reconstruct the full tree of messages for any request,
which is invaluable for debugging, auditing, and understanding system behavior.

## How It Works

When you submit a command via `domain.process()`, Protean generates a
`correlation_id` (a UUID4 hex string, 32 characters) and sets `causation_id`
to `None` (since this is the root of the chain). As the command triggers events
and those events trigger further commands, both IDs are propagated automatically:

```
PlaceOrder (correlation=a1b2c3d4, causation=None)         <-- root
  +-- OrderPlaced (correlation=a1b2c3d4, causation=cmd-123)
        +-- ReserveInventory (correlation=a1b2c3d4, causation=evt-456)
              +-- InventoryReserved (correlation=a1b2c3d4, causation=cmd-789)
```

Every message shares the same `correlation_id`, while each `causation_id`
points to the message that directly caused it.

## Supplying an External Correlation ID

In production, the `correlation_id` often originates outside Protean -- from an
API gateway, frontend client, or upstream service. You can pass it into
`domain.process()`:

```python
# Accept correlation_id from the HTTP request header
correlation_id = request.headers.get("X-Correlation-ID")

domain.process(
    PlaceOrder(customer_id="cust-123", items=items),
    correlation_id=correlation_id,
)
```

When a `correlation_id` is provided, Protean uses it as-is instead of
generating a new one. This lets you trace a request across service boundaries.

If no `correlation_id` is provided, Protean auto-generates one (UUID4 hex, no
dashes).

## Where Trace IDs Are Stored

Both IDs live in `DomainMeta`, the domain-specific section of message metadata:

```json
{
    "_metadata": {
        "headers": {
            "id": "myapp::order-abc123-0.1",
            "type": "MyApp.OrderPlaced.v1",
            "stream": "myapp::order-abc123",
            "time": "2026-02-22T10:30:00+00:00"
        },
        "domain": {
            "fqn": "myapp.events.OrderPlaced",
            "kind": "EVENT",
            "version": "v1",
            "sequence_id": "0.1",
            "correlation_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            "causation_id": "myapp::order:command-abc123"
        }
    }
}
```

### Accessing Trace IDs in Code

```python
# On a command or event object
event._metadata.domain.correlation_id
event._metadata.domain.causation_id

# On a deserialized Message
message.metadata.domain.correlation_id
message.metadata.domain.causation_id
```

## Propagation Rules

The trace context flows through all message construction paths:

| Entry point | `correlation_id` | `causation_id` |
|-------------|-------------------|-----------------|
| `domain.process(cmd)` | Auto-generated or caller-provided | `None` (root) |
| `domain.process(cmd, correlation_id="ext-123")` | `"ext-123"` | `None` (root) |
| Command handler raises event | Inherited from command | Command's `headers.id` |
| Event handler processes new command | Inherited from event | Event's `headers.id` |

The propagation happens through Protean's global context (`g.message_in_context`),
which the engine sets before invoking each handler. This works in both
synchronous and asynchronous processing modes.

## Relationship to W3C TraceParent

Protean maintains two distinct tracing layers:

| Layer | Location | Purpose | Format |
|-------|----------|---------|--------|
| **Domain tracing** | `DomainMeta.correlation_id` + `causation_id` | Protean-internal causation chain | Flexible strings |
| **Distributed tracing** | `MessageHeaders.traceparent` | External tool integration (Jaeger, Zipkin) | W3C hex format |

`correlation_id` bridges both layers -- it identifies the same business
operation whether you're looking at Protean's domain metadata or a W3C trace.
`causation_id`, however, is domain-layer only because Protean's message IDs
(like `"myapp::order-abc123-0.1"`) are intentionally human-readable and cannot
fit in W3C's 16-hex-char `parent_id` format.

## Using Trace IDs in the Test DSL

The [test DSL](../testing/event-sourcing-tests.md) supports correlation IDs for
verifying trace propagation:

```python
from protean.testing import given

result = (
    given(Order)
    .when(PlaceOrder(customer_id="cust-1", items=[...]))
    .then_events(OrderPlaced)
)

# Follow the chain with the same correlation_id
result.process(
    ReserveInventory(order_id=result.aggregate.id),
    correlation_id=result.events[0]._metadata.domain.correlation_id,
)
```

## Inspecting Traces via CLI

The `protean events` CLI commands support a `--trace` flag to display
correlation and causation IDs alongside event data:

```bash
# Read events with trace context
protean events read "myapp::order-abc123" --trace --domain=myapp

# Search events with trace context
protean events search --type=OrderPlaced --trace --domain=myapp
```

To follow an entire causal chain by correlation ID:

```bash
protean events trace "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" --domain=myapp
```

This scans all events matching the given `correlation_id` and displays them in
chronological order, showing the full causation tree.

See [`protean events`](../../reference/cli/data/events.md) for the complete CLI
reference.

## Outbox Integration

When events are committed to the outbox (for reliable message delivery), the
`correlation_id` and `causation_id` are denormalized into the outbox record
for efficient querying:

```python
# Find all outbox messages for a business operation
outbox_repo.find_by_correlation_id("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")

# Find all messages caused by a specific message
outbox_repo.find_by_causation_id("myapp::order-abc123-0.1")
```

This is useful for operational dashboards and debugging delivery issues.

---

!!! tip "See also"
    **Related guide:** [Message Enrichment](message-enrichment.md) -- Automatically add custom metadata (user context, tenant ID, audit data) to every event and command via enricher hooks.

    **Pattern:** [Message Tracing in Event-Driven Systems](../../patterns/message-tracing.md) -- Design considerations, when to use external vs generated IDs, and multi-service tracing strategies.

    **Reference:** [`protean events trace`](../../reference/cli/data/events.md) -- CLI command for following causal chains.

    **Concept:** [Observability](../../reference/server/observability.md) -- Real-time tracing and monitoring with the Protean Observatory.
