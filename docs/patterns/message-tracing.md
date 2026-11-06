# Trace messages through an event-driven system

In event-driven architectures, a single user action often triggers a cascade of
commands and events across multiple aggregates and services. Without tracing,
you debug a production issue by piecing together log entries, database records,
and event store messages by hand. Protean adds two metadata fields
(`correlation_id` and `causation_id`) to every message in the chain, so you can
follow the chain without that manual work.

## The Problem

Consider an e-commerce checkout: when a customer places an order, the system
processes the payment, reserves inventory, and sends a shipping notification.
If the shipping notification fails, you need to answer:

1. **Which user request caused this?** (correlation)
2. **What was the immediate trigger?** (causation)
3. **What other effects did that request produce?** (chain traversal)

Without explicit tracing, the only clue is `origin_stream`, a single string
recording where a command came from. That tells you the source aggregate but
not the full chain.

## The Pattern

Attach two identifiers to every command and event:

- **`correlation_id`**: Constant across the entire causal chain. Generated at
  the earliest entry point (often the API gateway or frontend) and carried
  through every subsequent message. All messages belonging to the same business
  operation share one `correlation_id`.

- **`causation_id`**: Points to the immediate parent. When a command handler
  raises an event, the event's `causation_id` is the command's message ID.
  When an event handler dispatches a new command during asynchronous
  processing, the command's `causation_id` is the event's message ID.

Together, the `correlation_id` and `causation_id` links form a **causation
tree**:

```
PlaceOrder [corr=X, cause=None]              <-- root command
  +-- OrderPlaced [corr=X, cause=PlaceOrder.id]
        +-- ReserveInventory [corr=X, cause=OrderPlaced.id]
        |     +-- InventoryReserved [corr=X, cause=ReserveInventory.id]
        +-- NotifyCustomer [corr=X, cause=OrderPlaced.id]
              +-- NotificationSent [corr=X, cause=NotifyCustomer.id]
```

## How Protean designs the tracing fields

### Where to Generate correlation_id

The `correlation_id` should be generated as early as possible, ideally by the caller (API
gateway, frontend, CLI). This lets you trace a request from the moment it
enters the system.

The examples on this page use this ordering domain. Commands are processed
synchronously, so `domain.process()` returns the command handler's result:

```python
--8<-- "patterns/message-tracing/001.py:model"
```

A FastAPI endpoint reads the caller's ID from the `X-Correlation-ID` header:

```python
--8<-- "patterns/message-tracing/001.py:endpoint"
```

When you call `domain.process()` without an external `correlation_id`, Protean
generates one automatically. This means every message chain always has a
`correlation_id`. You never have to check for `None`.

### Correlation IDs accept any string format

The `correlation_id` is a flexible string, not strictly a UUID. It can be:

- A UUID4 hex (`a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6`), Protean's default
- A request ID from an API gateway (`req-abc-123-def`)
- A trace ID from an external tracing system (`00-4bf92f3577b34da6a3ce929d0e0e4736-...`)

This flexibility lets you integrate with existing infrastructure without
reformatting IDs.

The `causation_id` is always a Protean message ID (e.g.,
`myapp::order-abc123-0.1`), which is intentionally human-readable for
debugging.

### Keep domain tracing separate from W3C TraceParent

Protean supports W3C `TraceParent` in `MessageHeaders.traceparent` for
integration with distributed tracing tools (Jaeger, Zipkin, Datadog). The
domain-level `correlation_id` and `causation_id` serve a different purpose:

| Concern | Domain tracing | Distributed tracing |
|---------|---------------|-------------------|
| **Location** | `DomainMeta.correlation_id` / `causation_id` | `MessageHeaders.traceparent` |
| **Purpose** | Business operation tracking | Infrastructure span tracking |
| **Format** | Flexible strings | W3C 32-hex / 16-hex |
| **Required** | Always present | Optional integration |

The same `correlation_id` value can serve both domain tracing and distributed
tracing. It identifies the same operation. But you cannot store `causation_id`
in `TraceParent.parent_id`, because Protean's message IDs are human-readable
strings and `TraceParent.parent_id` takes a 16-hex-char span ID.

## How Protean Supports It

Protean implements the tracing pattern automatically. No opt-in required.

### Protean propagates trace context automatically

Protean copies trace context into every message it constructs, through
`g.message_in_context`:

1. **`domain.process(command)`**: Generates or accepts `correlation_id`,
   sets `causation_id = None` (root command)
2. **Command handler raises events**: Events inherit `correlation_id` from
   the command, `causation_id` = command's `headers.id`
3. **Event handler dispatches commands**: New commands inherit
   `correlation_id` from the event, `causation_id` = event's `headers.id`

The `correlation_id` carries through in both sync and async processing modes.
Step 3's `causation_id` holds only in async mode. In sync mode the event
handler runs inside the original command's handler, so the new command records
that original command as its cause.

### The outbox stores trace IDs as indexed columns

The outbox stores `correlation_id` and `causation_id` as indexed columns
alongside the full message metadata. This enables efficient queries:

```python
# fragment
# Find all messages from a business operation
outbox_repo.find_by_correlation_id("a1b2c3d4...")

# Find all messages caused by a specific parent
outbox_repo.find_by_causation_id("myapp::order-abc123-0.1")
```

### Causation Chain API

The event store provides methods to traverse causation chains programmatically:

```python
--8<-- "patterns/message-tracing/001.py:causation_api"
```

These methods answer the three debugging questions directly:

1. **"Which user request caused this?"**: `trace_causation()` walks up to the root
2. **"What was the immediate trigger?"**: Check `causation_id` on the message
3. **"What other effects did that request produce?"**: `trace_effects()` walks down

### Inspect traces from the CLI

The `protean events` CLI supports tracing with both tree and flat views:

```bash
# Show trace IDs alongside events
protean events read "myapp::order-abc123" --trace

# Follow a full causal chain (tree view, default)
protean events trace "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"

# Flat table view for chronological listing
protean events trace "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" --flat
```

The tree view reconstructs parent-child relationships from `causation_id` links:

```
CMD App.PlaceOrder.v1 (myapp::order:command-abc123-0) @ 2026-02-22 10:30:00
├── EVT App.OrderPlaced.v1 (myapp::order-abc123-0) @ 2026-02-22 10:30:00
│   └── CMD App.ReserveInventory.v1 (myapp::inventory:command-inv456-0) @ 2026-02-22 10:30:01
│       └── EVT App.InventoryReserved.v1 (myapp::inventory-inv456-0) @ 2026-02-22 10:30:02
```

## When to Use External Correlation IDs

**Always prefer external IDs when available.** If your API gateway or frontend
generates request IDs, pass them through as `correlation_id`. This gives you
end-to-end traceability from the user's browser to the last event handler.

Only in the following cases should you generate IDs at the Protean boundary:

- The entry point is a scheduled job or cron task
- The message originates from an external system that doesn't provide trace IDs
- You're in development/testing and don't have an API gateway

## Trace messages across services

When one Protean service consumes events from another (via subscribers),
forward the `correlation_id` from the source event. A subscriber receives the
published message as a `dict`:

```python
--8<-- "patterns/message-tracing/001.py:subscriber"
```

With the forwarded `correlation_id`, you can follow one causal chain across
service boundaries. When the Engine delivers a broker message, it already puts
the message's `correlation_id` in context and then calls the subscriber. A
command that the subscriber processes picks up that `correlation_id`. Passing
it explicitly keeps the link when the subscriber runs some other way, such as a
direct call in a test or a script. The Engine looks for the ID at
`metadata.domain.correlation_id`, then `metadata.correlation_id`, then a
top-level `correlation_id`. A message with none of these starts a new chain
with a generated ID.

## Test trace propagation

Protean's test DSL runs a command through `given(...).process()` and records
the events it raised, with their trace metadata:

```python
--8<-- "patterns/message-tracing/001.py:dsl_generated"
```

For multi-step chains, pass the correlation ID to the next `process()` call
explicitly:

```python
--8<-- "patterns/message-tracing/001.py:dsl_forward"
```

## Summary

- **`correlation_id`** groups all messages from one business operation.
  Generate early, propagate everywhere.
- **`causation_id`** links each message to its direct parent, forming a tree.
- Protean propagates both IDs automatically. If you have an external
  `correlation_id`, you only need to supply it at the entry point.
- Use `trace_causation()`, `trace_effects()`, and `build_causation_tree()` to
  traverse chains programmatically.
- Use `protean events trace` to follow a full chain in the event store.
- Prefer external (caller-provided) correlation IDs for end-to-end
  traceability across services.

---

!!! tip "Related reading"
    **Complete guide:** [Correlation and Causation IDs](../guides/observability/correlation-and-causation.md): End-to-end guide covering HTTP headers, OTEL spans, Observatory traces, structured logging, and cross-service propagation.

    **Guide:** [Message Tracing](../guides/domain-behavior/message-tracing.md): How-to guide with code examples for setting up tracing.

    **Reference:** [`protean events trace`](../reference/cli/data/events.md): CLI command for following causal chains.

    **Internals:** [Causation Chain Traversal](../concepts/internals/event-sourcing.md#trace-the-causation-chain): Algorithm details for `trace_causation`, `trace_effects`, and `build_causation_tree`.

    **Related patterns:**

    - [Coordinating Long-Running Processes](coordinating-long-running-processes.md): Process managers use correlation to track multi-step workflows.
    - [Consuming Events from Other
      Domains](consuming-events-from-other-domains.md): Subscribers as
      anti-corruption layers, with correlation IDs that link messages across
      services.
