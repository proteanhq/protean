# Message Tracing

<span class="pathway-tag pathway-tag-cqrs">CQRS</span> <span class="pathway-tag pathway-tag-es">ES</span>

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

## Traversing the Causation Chain Programmatically

The event store provides three methods for traversing causation chains in code.
These are inspection/debugging utilities that operate on the event store
directly.

### Walking up: `trace_causation()`

Given a message, walk **up** the causation chain to the root command:

```python
store = domain.event_store.store

# From a message ID string
chain = store.trace_causation("myapp::order-abc123-0.1")

# From a Message object
chain = store.trace_causation(some_message)

# chain = [root_command, ..., target_message]
for msg in chain:
    print(f"{msg.metadata.headers.type} (caused by {msg.metadata.domain.causation_id})")
```

The result is a list of `Message` objects ordered root-first, target-last. The
root command (with `causation_id=None`) is always the first element, and the
target message is always the last.

### Walking down: `trace_effects()`

Given a message, walk **down** to find everything it caused:

```python
# All downstream effects (recursive)
effects = store.trace_effects("myapp::order:command-abc123-0")

# Only direct children (one level)
direct = store.trace_effects("myapp::order:command-abc123-0", recursive=False)
```

Effects are returned in chronological order (by `global_position`). The target
message itself is **not** included in the result.

### Building the full tree: `build_causation_tree()`

For a complete picture of a business operation, build the full causation tree
from a `correlation_id`:

```python
from protean.port.event_store import CausationNode

root = store.build_causation_tree("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")

if root:
    print(f"{root.kind} {root.message_type}")  # e.g., "COMMAND App.PlaceOrder.v1"
    for child in root.children:
        print(f"  {child.kind} {child.message_type}")
```

`CausationNode` is a dataclass with these attributes:

| Attribute | Type | Description |
|-----------|------|-------------|
| `message_id` | `str` | The message's `headers.id` |
| `message_type` | `str` | The fully-qualified message type |
| `kind` | `str` | `"EVENT"` or `"COMMAND"` |
| `stream` | `str` | The stream name |
| `time` | `str \| None` | Write timestamp |
| `global_position` | `int \| None` | Global position in the event store |
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
# Tree view (default) — shows parent-child causation structure
protean events trace "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" --domain=myapp

# Flat table view — chronological list with trace columns
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
    **Complete guide:** [Correlation and Causation IDs](../observability/correlation-and-causation.md) -- End-to-end guide covering HTTP headers, OTEL span attributes, Observatory traces, structured logging, and cross-service propagation.

    **Related guide:** [Message Enrichment](message-enrichment.md) -- Automatically add custom metadata (user context, tenant ID, audit data) to every event and command via enricher hooks.

    **Pattern:** [Message Tracing in Event-Driven Systems](../../patterns/message-tracing.md) -- Design considerations, when to use external vs generated IDs, and multi-service tracing strategies.

    **Reference:** [`protean events trace`](../../reference/cli/data/events.md) -- CLI command for following causal chains.

    **Internals:** [Causation Chain Traversal](../../concepts/internals/event-sourcing.md#causation-chain-traversal) -- Algorithm details for the traversal methods.

    **API:** [BaseEventStore](../../api/ports/event-store.md) -- Auto-generated API reference for `trace_causation`, `trace_effects`, `build_causation_tree`, and `CausationNode`.

    **Concept:** [Observability](../../reference/server/observability.md) -- Real-time tracing and monitoring with the Protean Observatory.
