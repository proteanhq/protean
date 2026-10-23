# Message Tracing

<span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

In event-driven systems, a single user action can trigger a chain of commands
and events that cascade across multiple aggregates and handlers. **Message
tracing** lets you follow the full causal chain (from the initial request
through every command and event it spawns) using two identifiers that Protean
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

In production, the `correlation_id` often originates outside Protean, from an API gateway,
frontend client, or upstream service. You can pass it into `domain.process()`:

```python
--8<-- "guides/domain-behavior/message-tracing/001.py:external"
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
            "version": 1,
            "sequence_id": "0.1",
            "correlation_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            "causation_id": "myapp::order:command-abc123"
        }
    }
}
```

### Accessing Trace IDs in Code

```python
--8<-- "guides/domain-behavior/message-tracing/001.py:access"
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
which the engine sets before invoking each handler. The `correlation_id` carries
through in both synchronous and asynchronous processing modes. The
`causation_id` of a command sent from an event handler differs between them.
With asynchronous processing it is the event's `headers.id`, as the table
shows. With synchronous processing the event handler runs inside the original
command's handler, so the new command records that original command as its
cause.

## Relationship to W3C TraceParent

Protean maintains two distinct tracing layers:

| Layer | Location | Purpose | Format |
|-------|----------|---------|--------|
| **Domain tracing** | `DomainMeta.correlation_id` + `causation_id` | Protean-internal causation chain | Flexible strings |
| **Distributed tracing** | `MessageHeaders.traceparent` | External tool integration (Jaeger, Zipkin) | W3C hex format |

`correlation_id` bridges both layers. It identifies the same business operation
whether you're looking at Protean's domain metadata or a W3C trace.
`causation_id`, however, is domain-layer only because Protean's message IDs
(like `"myapp::order-abc123-0.1"`) are intentionally human-readable and cannot
fit in W3C's 16-hex-char `parent_id` format.

## Using Trace IDs in the Test DSL

The [test DSL](../testing/event-sourcing-tests.md) supports correlation IDs for
verifying trace propagation. Pass the same `correlation_id` to each `process()`
call to group the commands under one business operation. Each call still starts
its own causation chain, with `causation_id=None` on its command:

```python
--8<-- "guides/domain-behavior/message-tracing/001.py:dsl"
```

## Traversing the Causation Chain Programmatically

The event store provides three methods for traversing causation chains in code.
These are inspection/debugging utilities that operate on the event store
directly.

### Walking up: `trace_causation()`

Given a message, walk **up** the causation chain to the root command:

```python
--8<-- "guides/domain-behavior/message-tracing/001.py:trace_causation"
```

The result is a list of `Message` objects ordered root-first, target-last. The
root command (with `causation_id=None`) is always the first element, and the
target message is always the last.

### Walking down: `trace_effects()`

Given a message, walk **down** to find everything it caused:

```python
--8<-- "guides/domain-behavior/message-tracing/001.py:trace_effects"
```

Effects are returned in chronological order (by `global_position`). The target
message itself is **not** included in the result.

### Building the full tree: `build_causation_tree()`

For a complete picture of a business operation, build the full causation tree
from a `correlation_id`:

```python
--8<-- "guides/domain-behavior/message-tracing/001.py:tree"
```

`CausationNode` is a dataclass with these attributes:

| Attribute | Type | Description |
|-----------|------|-------------|
| `message_id` | `str` | The message's `headers.id` |
| `message_type` | `str` | The fully-qualified message type |
| `kind` | `str` | `"EVENT"` or `"COMMAND"` |
| `stream` | `str` | The stream name |
| `time` | <code>str &#124; None</code> | Write timestamp |
| `global_position` | <code>int &#124; None</code> | Global position in the event store |
| `children` | `list[CausationNode]` | Child messages caused by this message |

Returns `None` if no messages exist for the given `correlation_id`.

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
# Tree view (default): shows parent-child causation structure
protean events trace "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" --domain=myapp

# Flat table view: chronological list with trace columns
protean events trace "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" --flat --domain=myapp
```

The default tree view reconstructs the parent-child causation relationships and
displays them as an indented tree:

```
CMD App.PlaceOrder.v1 (myapp::order:command-abc123-0) @ 2026-02-22 10:30:00
├── EVT App.OrderPlaced.v1 (myapp::order-abc123-0) @ 2026-02-22 10:30:00
│   └── CMD App.ReserveInventory.v1 (myapp::inventory:command-inv456-0) @ 2026-02-22 10:30:01
│       └── EVT App.InventoryReserved.v1 (myapp::inventory-inv456-0) @ 2026-02-22 10:30:02

Causation tree: 4 message(s) for correlation ID 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'
```

Use `--flat` for a chronological table view when you need exact positions and
timestamps.

See [`protean events`](../../reference/cli/data/events.md) for the complete CLI
reference.

## Outbox Integration

When events are committed to the outbox (for reliable message delivery), the
`correlation_id` and `causation_id` are denormalized into the outbox record
for efficient querying. Each database provider has its own outbox repository,
looked up by the provider's name. Protean has no public method for this lookup
yet, so the example calls the internal `_get_outbox_repo()`, which may change
between releases:

```python
--8<-- "guides/domain-behavior/message-tracing/002.py:outbox"
```

This is useful for operational dashboards and debugging delivery issues.

---

!!! seealso "See also"
    **Complete guide:** [Correlation and Causation IDs](../observability/correlation-and-causation.md): End-to-end guide covering HTTP headers, OTEL span attributes, Observatory traces, structured logging, and cross-service propagation.

    **Related guide:** [Message Enrichment](message-enrichment.md): Automatically add custom metadata (user context, tenant ID, audit data) to every event and command via enricher hooks.

    **Pattern:** [Message Tracing in Event-Driven Systems](../../patterns/message-tracing.md): Design considerations, when to use external vs generated IDs, and multi-service tracing strategies.

    **Reference:** [`protean events trace`](../../reference/cli/data/events.md): CLI command for following causal chains.

    **Internals:** [Causation Chain Traversal](../../concepts/internals/event-sourcing.md#causation-chain-traversal): Algorithm details for the traversal methods.

    **API:** [BaseEventStore](../../api/ports/event-store.md): Auto-generated API reference for `trace_causation`, `trace_effects`, `build_causation_tree`, and `CausationNode`.

    **Concept:** [Observability](../../reference/server/observability.md): Real-time tracing and monitoring with the Protean Observatory.
